"""Exhaustive input-only SURE comparison, independent of stock initialisation."""
from __future__ import annotations

import itertools
import shutil
import warnings

import numpy as np

from .common import CONFIG, ROOT, RUNTIME, YEARS, dump, read, digest, run_logged, experiment_hashes


def prepare(target):
    from pysd.translators.vensim.vensim_file import VensimFile
    from pysd.translators.structures.abstract_expressions import GetDataStructure, GetLookupsStructure
    from pysd.builders.julia.julia_model_builder import JuliaSectionBuilder
    from . import builder_patch, external_patch
    builder_patch.apply()
    external_patch.apply()
    target.mkdir(parents=True, exist_ok=True)
    source = target / "SURE_pysd_v3.mdl"
    shutil.copy2(ROOT / "Vensim/SURE_pysd_v3.mdl", source)
    for path in (ROOT / "Vensim").glob("*_pysd_v3.csv"):
        shutil.copy2(path, target / path.name)
    parsed = VensimFile(source, encoding="latin-1")
    parsed.parse()
    builder = JuliaSectionBuilder(parsed.get_abstract_model().sections[0], data_format="json", backend="ode")
    for elem in builder.abstract_elements:
        builder.namespace.add_to_namespace(elem.name)
    variables = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for elem in builder.abstract_elements:
            external = [isinstance(c.ast, (GetDataStructure, GetLookupsStructure)) for c in elem.components]
            if not any(external):
                continue
            if not all(external):
                raise ValueError(f"Mixed input definitions: {elem.name}")
            identifier = builder.namespace.namespace[elem.name]
            if isinstance(elem.components[0].ast, GetDataStructure):
                builder._process_get_data(elem, identifier, elem.components[0])
                kind = "data"
            else:
                builder._process_get_lookups(elem, identifier)
                kind = "lookup"
            specification = builder._json_data["external"][identifier]
            variables.append({"name": elem.name, "identifier": identifier, "kind": kind,
                              "dimensions": specification["dimensions"],
                              "coordinates": specification["coordinates"],
                              "interpolation": specification["interpolation"]})
    builder._write_data_json()
    text = (CONFIG / "external_data.jl").read_text() + '\nusing JSON3\nconst _model_data = JSON3.read(read(joinpath(@__DIR__, "SURE_pysd_v3_data.json"), String))\n'
    text += builder._lookup_block()
    (target / "inputs.jl").write_text(text)
    dump(target / "variables.json", variables)
    dump(target / "translation-warnings.json", [str(w.message) for w in caught])
    dump(target / "sources.json", {str(p.relative_to(ROOT)): digest(p) for p in
                                   [ROOT / "Vensim/SURE_pysd_v3.mdl", ROOT / "Vensim/SURE_pysd_v3.py",
                                    *sorted((ROOT / "Vensim").glob("*_pysd_v3.csv"))]})


def oracle(target):
    import pysd
    from pysd.py_backend.external import ExtData, ExtLookup
    if pysd.__version__ != "3.14.3":
        raise ValueError("Wrong SURE input oracle")
    model = pysd.load(ROOT / "Vensim/SURE_pysd_v3.py", initialize=False)
    available = {item.py_name: item for item in model._external_elements
                 if isinstance(item, (ExtData, ExtLookup))}
    variables = read(target / "variables.json")
    claimed = set()
    records = []
    arrays = {}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for item in variables:
            key = "_ext_" + item["kind"] + "_" + item["identifier"]
            if key not in available:
                raise ValueError(f"Missing Python input reader: {key}")
            claimed.add(key)
            ext = available[key]
            ext.initialize()
            if ext.interp != item["interpolation"]:
                raise ValueError(f"SURE input interpolation mismatch: {item['name']}")
            if list(ext.final_coords) != item["dimensions"] or ext.final_coords != item["coordinates"]:
                raise ValueError(f"SURE input coordinate mismatch: {item['name']}")
            rows = []
            for year in YEARS:
                value = ext(year)
                if item["dimensions"]:
                    if list(value.dims) != item["dimensions"]:
                        raise ValueError(f"Python dimension order changed: {item['name']}")
                    for dim in item["dimensions"]:
                        if value.coords[dim].values.tolist() != item["coordinates"][dim]:
                            raise ValueError(f"Python label order changed: {item['name']}/{dim}")
                rows.append(np.asarray(value, dtype=np.float64).ravel(order="C"))
            array = np.asarray(rows, dtype=np.float64)
            if np.isinf(array).any() or (np.isnan(array).any() and ext.interp != "raw"):
                raise ValueError(f"Nonfinite SURE input: {item['name']}")
            arrays[item["identifier"]] = array
            records.append({**item, "years": YEARS, "shape": list(array.shape)})
    if claimed != set(available):
        raise ValueError(f"Unverified Python external readers: {set(available)-claimed}")
    np.savez_compressed(target / "python-values.npz", **arrays)
    dump(target / "oracle.json", records)
    dump(target / "python-warnings.json", [str(w.message) for w in caught])


def compare(target):
    records = read(target / "oracle.json")
    julia_metadata = read(target / "julia-metadata.json")
    if records != julia_metadata:
        raise ValueError("Julia SURE input metadata differs from Python")
    results = []
    with np.load(target / "python-values.npz", allow_pickle=False) as archive:
        for item in records:
            expected = archive[item["identifier"]]
            path = target / "julia" / f"{item['identifier']}.bin"
            actual = np.fromfile(path, dtype="<f8")
            if actual.size != expected.size:
                raise ValueError(f"Julia SURE input truncated: {item['name']}")
            actual = actual.reshape(expected.shape)
            finite = np.isfinite(expected)
            # RAW inputs intentionally produce NaN away from their source grid.
            # Every such cell is checked for the same NaN semantics; none is
            # silently dropped. SURE output/state validation remains finite-only.
            semantics_match = (not np.isinf(actual).any() and np.array_equal(np.isnan(actual), np.isnan(expected)))
            safe_expected = np.where(finite, expected, 0.)
            safe_actual = np.where(finite, actual, 0.)
            scale = np.maximum(1., np.max(np.abs(safe_expected), axis=0))
            tolerance = 1e-12 * scale + 1e-9 * np.abs(safe_expected)
            absolute = np.abs(safe_actual - safe_expected)
            mismatch = np.argwhere((absolute > tolerance) | (np.isnan(actual) != np.isnan(expected)))
            result = {"name": item["name"], "pass": semantics_match and not len(mismatch), "values": int(expected.size),
                      "expected_raw_nan_values": int(np.isnan(expected).sum()),
                      "nonfinite_semantics_match": semantics_match,
                      "max_absolute_error": float(np.max(absolute)),
                      "max_scaled_error": float(np.max(absolute / tolerance))}
            if len(mismatch):
                row, column = map(int, mismatch[0])
                cells = list(itertools.product(*item["coordinates"].values()))
                result["first_divergence"] = {"year": YEARS[row], "coordinates": cells[column],
                                             "python": float(expected[row, column]) if np.isfinite(expected[row, column]) else "NaN",
                                             "julia": float(actual[row, column]) if np.isfinite(actual[row, column]) else "NaN",
                                             "tolerance": float(tolerance[row, column])}
            results.append(result)
    summary = {"pass": all(item["pass"] for item in results), "variables": len(results),
               "values": sum(item["values"] for item in results), "years": YEARS,
               "expected_raw_nan_values": sum(item["expected_raw_nan_values"] for item in results),
               "results": results, "experiment": experiment_hashes(),
               "source_hashes": read(target / "sources.json"),
               "evidence_hashes": {str(p.relative_to(target)): digest(p) for p in
                                   [target / "oracle.json", target / "python-values.npz",
                                    target / "variables.json", target / "SURE_pysd_v3_data.json",
                                    target / "inputs.jl", target / "julia-metadata.json",
                                    *sorted((target / "julia").glob("*.bin"))]}}
    dump(target / "results.json", summary)
    return summary


def run(directory):
    from .execution import julia_command
    target = directory / "sure-external"
    for function, environment in (("prepare", "python-julia"), ("oracle", "python-reference")):
        command = f"from pathlib import Path; from scripts.julia_repro.sure_external import {function}; {function}(Path({str(target)!r}))"
        run_logged([RUNTIME / environment / "bin/python", "-B", "-c", command], target / f"{function}.log")
    run_logged([*julia_command(), CONFIG / "test_sure_external.jl", target], target / "julia.log")
    return compare(target)
