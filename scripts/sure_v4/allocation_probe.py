"""Prepare a native Vensim allocator experiment with no dynamic feedback.

Synthetic SURE-scale boundary cases compare ALLOCATE AVAILABLE against
ALLOCATE BY PRIORITY, including a common priority shift. Native execution is
deliberately separate: publish the generated MDL in Vensim DSS, then export.
"""
from pathlib import Path
import argparse
import ast
import difflib
import re
import warnings

from scripts.julia_repro.common import digest, dump, read


def priority_mdl(text):
    """Equivalent candidate only for the audited SURE rectangular profiles."""
    for name, value in (("Supplier priority type", "1"), ("Supplier priority width", "0.1")):
        if not re.search(rf"(?m)^{name}\s*=\s*{re.escape(value)}\s*~", text):
            raise ValueError(f"Unsupported allocation profile: {name}")
    pattern = (r"Electricity dispatched\[Month,Hour,Supplier\]\s*=\s*"
               r"ALLOCATE AVAILABLE\(\s*Hourly available supply by Supplier\[Month,Hour,Supplier\],\s*"
               r"Priority vector by supplier\[Supplier,ptype\]\s*,\s*Hourly demand and PHS\[Month,Hour\]\s*\)")
    replacement = """Nonnegative available supply[Month,Hour,Supplier]=
    MAX(0, Hourly available supply by Supplier[Month,Hour,Supplier]) ~~|

Electricity dispatched[Month,Hour,Supplier]=
    ALLOCATE BY PRIORITY(Nonnegative available supply[Month,Hour,Supplier],
    Ppriority by supplier[Supplier], ELMCOUNT(Supplier), Supplier priority width,
    Hourly demand and PHS[Month,Hour])"""
    result, count = re.subn(pattern, replacement, text)
    if count != 1 or "Nonnegative available supply" in text:
        raise ValueError("Expected the original SURE allocation equation exactly once")
    return result


def make_cases():
    import numpy as np
    from pysd.py_backend.allocation import _allocate_by_priority_1d
    rng = np.random.default_rng(20261012)
    # Explicit short decimals survive the Vensim/PySD constant-array syntax
    # without relying on NumPy's shortened array repr in the Python builder.
    request = np.round(rng.uniform(.02, .4, 9), 6)
    # Separated priorities model SURE's narrow rectangular merit profiles;
    # these values are synthetic, not an observed native SURE input vector.
    original = -np.array([2., 6., 11., 18., 19., 30., 80., 120., 150.])
    cases = []
    for shift in (0., 200.):
        for edge in (1, 4, 8):
            for epsilon in (-.011, -.005, -.0001, 0., .0001, .005, .011):
                priority = original + shift
                supply = float(request[:edge].sum() + epsilon)
                expected = _allocate_by_priority_1d(request, priority, .1, supply)
                cases.append({"id": f"C{len(cases):03d}", "request": request.tolist(),
                              "priority": priority.tolist(), "width": .1, "supply": supply,
                              "shift": shift, "boundary": edge, "offset": epsilon,
                              "expected": expected.tolist()})
    # Equal and overlapping profiles must retain proportional sharing.
    for priority in (np.full(9, 10.), np.round(np.linspace(10., 10.15, 9), 6)):
        for supply in (0., .2, float(request.sum()), float(request.sum() + 1)):
            cases.append({"id": f"C{len(cases):03d}", "request": request.tolist(),
                          "priority": priority.tolist(), "width": .1, "supply": supply,
                          "expected": _allocate_by_priority_1d(request, priority, .1, supply).tolist()})
    return cases


def render(cases):
    lines = ["{UTF-8}", "Case : " + ",".join(c["id"] for c in cases) + " ~~|",
             "Supplier : " + ",".join(f"S{i}" for i in range(9)) + " ~~|",
             "Profile : ptype,ppriority,pwidth,pextra ~~|"]
    for case in cases:
        label = case["id"]
        for name in ("request", "priority"):
            lines.append(f"{name.title()}[{label},Supplier]=" + ",".join(format(x, ".17g") for x in case[name]) + " ~~|")
        for name in ("width", "supply"):
            lines.append(f"{name.title()}[{label}]={case[name]:.17g} ~~|")
    lines += ["PP[Case,Supplier,ptype]=1 ~~|", "PP[Case,Supplier,ppriority]=Priority[Case,Supplier] ~~|",
              "PP[Case,Supplier,pwidth]=Width[Case] ~~|", "PP[Case,Supplier,pextra]=0 ~~|",
              "Available allocation[Case,Supplier]=ALLOCATE AVAILABLE(Request[Case,Supplier], PP[Case,Supplier,ptype], Supply[Case]) ~~|",
              "Priority allocation[Case,Supplier]=ALLOCATE BY PRIORITY(Request[Case,Supplier], Priority[Case,Supplier], ELMCOUNT(Supplier), Width[Case], Supply[Case]) ~~|",
              "INITIAL TIME=0 ~ Year ~|", "FINAL TIME=1 ~ Year ~|", "TIME STEP=1 ~ Year ~|", "SAVEPER=TIME STEP ~ Year ~|"]
    return "\n\n".join(lines) + "\n"


def prepare(directory, source):
    directory.mkdir(parents=True, exist_ok=False)
    cases = make_cases()
    dump(directory / "cases.json", cases)
    (directory / "allocation_probe.mdl").write_text(render(cases))
    original = source.read_text()
    candidate = priority_mdl(original)
    (directory / "SURE_priority_candidate.mdl").write_text(candidate)
    (directory / "SURE_priority_candidate.patch").write_text("".join(difflib.unified_diff(
        original.splitlines(keepends=True), candidate.splitlines(keepends=True),
        fromfile="SURE.mdl", tofile="SURE_priority_candidate.mdl")))
    dump(directory / "manifest.json", {
        "purpose": "Synthetic boundary diagnostic, not new native SURE evidence",
        "source_sha256": digest(source), "generator_sha256": digest(Path(__file__)),
        "files": {p.name: digest(p) for p in directory.iterdir() if p.is_file()},
        "native_executed": False})


def check_python(directory, v4_source):
    """Check the candidate equation against the actual v4 wrapper on all fixtures."""
    import numpy as np
    import xarray as xr
    import pysd
    from pysd.py_backend.allocation import allocate_available, allocate_by_priority
    fn = next(n for n in ast.parse(v4_source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "allocate_available")
    ns = {"np": np, "xr": xr, "_pysd_allocate_available": allocate_available, "_pysd_allocate_by_priority": allocate_by_priority}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(v4_source), "exec"), ns)
    # Prune the unsupported native comparison branch before initialization:
    # here only BY PRIORITY is the candidate whose translation is verified.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = pysd.read_vensim(str(directory / "allocation_probe.mdl"), initialize=False)
        model.select_submodel(vars=["Priority allocation", "Request", "Priority", "Width", "Supply"])
        result = model.run(return_columns=["Priority allocation"], return_timestamps=[0.], flatten_output=False)
    recorded = [{"category": w.category.__name__, "message": str(w.message)} for w in caught]
    dump(directory / "python-warnings.json", recorded)
    for w in recorded:
        if not (w["message"].startswith("Variable 'PP' is defined with different types:")
                or w["message"] == "Selecting submodel, to run the full model again use model.reload()"):
            raise ValueError(f"Unreviewed warning: {w}")
    calculated = result.iloc[0, 0].values
    cases = read(directory / "cases.json")
    assert list(result.iloc[0, 0].coords["Case"].values) == [c["id"] for c in cases]
    assert list(result.iloc[0, 0].coords["Supplier"].values) == [f"S{i}" for i in range(9)]
    for i, case in enumerate(cases):
        q = xr.DataArray(case["request"], dims=["Supplier"])
        pp = xr.DataArray(np.array([np.ones(9), case["priority"], np.full(9, case["width"]), np.zeros(9)]).T,
                          dims=["Supplier", "Profile"])
        expected = ns["allocate_available"](q, pp, case["supply"]).values
        np.testing.assert_array_equal(expected, case["expected"])
        np.testing.assert_array_equal(calculated[i], expected)
    dump(directory / "python-check.json", {"pass": True, "cases": len(cases), "native_executed": False,
                                           "v4_source_sha256": digest(v4_source)})


def export_native(directory, published, dll, destination):
    import numpy as np
    from pv_batteries.vensim_runner import VensimModel
    destination.mkdir(parents=True, exist_ok=False)
    result = {"model_sha256": digest(published), "dll_sha256": digest(dll),
              "case_sha256": digest(directory / "cases.json"), "series": {}}
    model = VensimModel(published, dll_path=dll, work_dir=destination / "work")
    model.set_time(initial=0, final=1, step=1)
    model.run("allocation_probe", {})
    for case in read(directory / "cases.json"):
        for kind in ("Available allocation", "Priority allocation"):
            for i in range(9):
                name = f"{kind}[{case['id']},S{i}]"
                times, values = model.get_series("allocation_probe", name, maxn=10)
                if not times or times[0] != 0 or not np.isfinite(values).all() or len(set(values)) != 1:
                    raise ValueError(f"Invalid constant probe output: {name}")
                result["series"][name] = {"times": times, "values": values}
    dump(destination / "native.json", result)
    compare_native(directory, destination)


def compare_native(directory, destination):
    """Near-numerical comparison, with only the exported Float32 half-ULP added."""
    import numpy as np
    native = read(destination / "native.json")
    if native["case_sha256"] != digest(directory / "cases.json"):
        raise ValueError("Native fixture identity differs")
    report = {"cases": [], "native_sha256": digest(destination / "native.json")}
    expected_names = set()
    for c in read(directory / "cases.json"):
        expected = np.array(c["expected"])
        for kind in ("Available allocation", "Priority allocation"):
            names = [f"{kind}[{c['id']},S{i}]" for i in range(9)]
            expected_names.update(names)
            series = [native["series"][n] for n in names]
            if any(s["times"][0] != 0 or len(s["times"]) != len(s["values"])
                   or len(set(s["values"])) != 1 for s in series):
                raise ValueError("Invalid constant series")
            values = np.array([s["values"][0] for s in series])
            rounded = values.astype(np.float32)
            if not np.isfinite(values).all() or not np.array_equal(values, rounded.astype(float)):
                raise ValueError("Expected finite Float32 native exports")
            half_ulp = np.maximum(np.nextafter(rounded, np.float32(np.inf)).astype(float) - values,
                                  values - np.nextafter(rounded, np.float32(-np.inf)).astype(float)) / 2
            error = abs(values - expected)
            limit = 1e-10 * np.maximum(1, abs(expected)) + 1e-8 * abs(expected) + half_ulp
            report["cases"].append({"id": c["id"], "function": kind, "priority_shift": c.get("shift"),
                "pass": bool(np.all(error <= limit)), "max_abs": float(error.max()),
                "resource_balance_error": float(values.sum() - min(sum(c["request"]), c["supply"]))})
    if set(native["series"]) != expected_names:
        raise ValueError("Extra or missing native output coordinates")
    report["functions"] = {kind: {"pass": all(r["pass"] for r in report["cases"] if r["function"] == kind),
        "max_abs": max(r["max_abs"] for r in report["cases"] if r["function"] == kind)}
        for kind in ("Available allocation", "Priority allocation")}
    dump(destination / "comparison.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=["prepare", "check-python", "export-native", "compare-native"])
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--source", type=Path)
    p.add_argument("--published", type=Path)
    p.add_argument("--dll", type=Path)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    directory = a.directory.resolve()
    if a.phase == "prepare":
        prepare(directory, a.source.resolve())
    elif a.phase == "check-python":
        check_python(directory, a.source.resolve())
    elif a.phase == "export-native":
        export_native(directory, a.published.resolve(), a.dll.resolve(), a.out.resolve())
    else:
        compare_native(directory, a.out.resolve())


if __name__ == "__main__":
    main()
