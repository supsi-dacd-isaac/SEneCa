#!/usr/bin/env python3
"""Audit the 6D/3D representation on certified SURE snapshots; no simulation.

Run from the repository root:
  .venv/bin/python -B scripts/validate_sure_packing.py --run-dir dist/julia-repro/RUN

This independent postprocessing audit is outside the frozen engine harness.
It writes only debug/packing-operations and never changes reference artifacts.
All reductions explicitly preserve the same label traversal in both layouts.
"""
from __future__ import annotations

import argparse
import itertools
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from scripts.julia_repro.common import YEARS, check_sources, digest, dump, read
from scripts.julia_repro.inventory import columns_for
from scripts.julia_repro.packing import DIMENSIONS, mapping, pack, unpack
from scripts.julia_repro.reference import reference_ready
from scripts.julia_repro.results import load_snapshot


def indices(cells):
    return tuple(np.asarray(axis, dtype=np.intp) for axis in zip(*cells))


def select(values, positions):
    return values[(slice(None), *positions)]


def assert_bits(left, right, context):
    if left.shape != right.shape or left.dtype != np.float64 or right.dtype != np.float64:
        raise ValueError(f"Unexpected comparison shape/type: {context}")
    equal = left.view(np.uint64) == right.view(np.uint64)
    if not bool(equal.all()):
        first = tuple(np.argwhere(~equal)[0])
        raise ValueError(f"Non-identical representation: {context}, index={first}, "
                         f"6D={left[first]!r}, 3D={right[first]!r}")
    return int(left.size)


class LabelPlan:
    def __init__(self, coords):
        self.coords = coords
        self.shape = tuple(len(coords[d]) for d in DIMENSIONS)
        self.archetypes = list(itertools.product(*(coords[d] for d in ("District","Performance","Type"))))
        self.configurations = list(itertools.product(coords["PVpanel"],coords["Battery"]))
        self.archetype_positions = {labels:i for i,labels in enumerate(self.archetypes)}
        self.configuration_positions = {labels:i for i,labels in enumerate(self.configurations)}
        self.positions = {d:{label:i for i,label in enumerate(coords[d])} for d in DIMENSIONS}
        self.packed_shape = (len(self.archetypes),len(coords["HS"]),len(self.configurations))
        pairs = list(mapping(coords))
        self.original_indices = indices([a for a,b in pairs])
        self.packed_indices = indices([b for a,b in pairs])
        self.cells = list(itertools.product(*(coords[d] for d in DIMENSIONS)))
        self.selections = []
        # Non-contiguous labels, a single element, and an intersection of both
        # composite indices exercise independent selections in each layout.
        for name, criteria in (
            ("district_performance", {"District":coords["District"][::2], "Performance":coords["Performance"][1::2]}),
            ("heating_configuration", {"HS":coords["HS"][1::3], "PVpanel":[coords["PVpanel"][0]], "Battery":[coords["Battery"][-1]]}),
            ("single_cell", {d:[coords[d][-1]] for d in DIMENSIONS}),
        ):
            chosen = [cell for cell in self.cells if all(cell[DIMENSIONS.index(d)] in labels for d,labels in criteria.items())]
            self.selections.append((name,criteria,*self.paired(chosen)))
        excluded = [cell for cell in self.cells if
            (cell[2] in coords["Performance"][::2] and cell[4] == coords["PVpanel"][0]) or
            (cell[0] == coords["District"][-1] and cell[5] == coords["Battery"][-1])]
        self.exclusions = self.paired(excluded)
        self.reductions = []
        for reduced in (("HS",),("PVpanel","Battery"),("District","Performance")):
            remaining = [d for d in DIMENSIONS if d not in reduced]
            groups = list(itertools.product(*(coords[d] for d in remaining)))
            slices = []
            for chosen in itertools.product(*(coords[d] for d in reduced)):
                cells = []
                for group in groups:
                    labels = dict(zip(remaining,group)) | dict(zip(reduced,chosen))
                    cells.append(tuple(labels[d] for d in DIMENSIONS))
                slices.append(self.paired(cells))
            self.reductions.append((reduced,remaining,len(groups),slices))
        self.transitions = []
        for dim,source,destination in (("HS",coords["HS"][0],coords["HS"][1]),
            ("PVpanel",coords["PVpanel"][-1],coords["PVpanel"][0])):
            axis = DIMENSIONS.index(dim)
            sources = [cell for cell in self.cells if cell[axis] == source]
            destinations = [tuple(destination if j == axis else label for j,label in enumerate(cell)) for cell in sources]
            self.transitions.append((dim,source,destination,self.paired(sources),self.paired(destinations)))

    def paired(self,cells):
        original = [tuple(self.positions[d][label] for d,label in zip(DIMENSIONS,cell)) for cell in cells]
        packed = [(self.archetype_positions[(cell[0],cell[2],cell[3])],self.positions["HS"][cell[1]],
                   self.configuration_positions[(cell[4],cell[5])]) for cell in cells]
        return indices(original),indices(packed)

    def convert(self,original):
        result = np.empty((original.shape[0],*self.packed_shape),dtype=np.float64)
        result[(slice(None),*self.packed_indices)] = select(original,self.original_indices)
        return result

    def audit(self,original,name):
        packed = self.convert(original)
        restored = np.empty_like(original)
        restored[(slice(None),*self.original_indices)] = select(packed,self.packed_indices)
        results = {"roundtrip":assert_bits(original,restored,name+"/roundtrip")}
        # Bind the vectorized all-year copy to the existing scalar label mapper.
        assert_bits(pack(original[0],self.coords),packed[0],name+"/core_pack")
        assert_bits(unpack(packed[0],self.coords),original[0],name+"/core_unpack")
        for label,criteria,left,right in self.selections:
            results["selection/"+label] = assert_bits(select(original,left),select(packed,right),name+"/"+label)
        excluded_original,excluded_packed = original.copy(),packed.copy()
        left,right = self.exclusions
        excluded_original[(slice(None),*left)] = 0.
        excluded_packed[(slice(None),*right)] = 0.
        results["exclusion_union"] = assert_bits(self.convert(excluded_original),excluded_packed,name+"/exclusion")
        for reduced,remaining,count,slices in self.reductions:
            left_sum = np.zeros((len(YEARS),count),dtype=np.float64)
            right_sum = np.zeros_like(left_sum)
            for left,right in slices:
                # Same explicit axis-label order; do not use np.sum, whose
                # physical-stride-dependent accumulation could round differently.
                left_sum += select(original,left)
                right_sum += select(packed,right)
            label = "sum/"+"+".join(reduced)
            results[label] = assert_bits(left_sum,right_sum,name+"/"+label)
        for dim,source,destination,(source6,source3),(destination6,destination3) in self.transitions:
            changed_original,changed_packed = original.copy(),packed.copy()
            transfer6 = select(changed_original,source6)*.125
            transfer3 = select(changed_packed,source3)*.125
            changed_original[(slice(None),*source6)] -= transfer6
            changed_original[(slice(None),*destination6)] += transfer6
            changed_packed[(slice(None),*source3)] -= transfer3
            changed_packed[(slice(None),*destination3)] += transfer3
            label = f"transition/{dim}/{source}->{destination}"
            results[label] = assert_bits(self.convert(changed_original),changed_packed,name+"/"+label)
        return {"pass":True,"years":len(YEARS),"source_cells":int(original.size),
                "comparisons":sum(results.values()),"operations":results}


def run(directory,requested=None):
    directory = Path(directory).resolve()
    manifest = read(directory/"manifest.json")
    check_sources(manifest)
    cases = requested or list(manifest["scenarios"])
    cases = list(dict.fromkeys(manifest["aliases"].get(case,case) for case in cases))
    if set(cases)-set(manifest["scenarios"]):
        raise ValueError("Unknown scenario")
    target = directory/"debug/packing-operations"
    dependencies = {"script":Path(__file__).resolve(),"packing":Path(__file__).resolve().parent/"julia_repro/packing.py",
                    "manifest":directory/"manifest.json"}
    hashes = {name:digest(path) for name,path in dependencies.items()}
    report = {"pass":False,"status":"running","cases":{},"implementation":hashes,
              "scope":"independent snapshot postprocessing; no model simulation or equation rewrite",
              "arithmetic":"bitwise comparisons; explicit identical label order for every partial sum",
              "runtime":{"python":platform.python_version(),"numpy":np.__version__,"platform":platform.platform()},
              "selected_cases":cases,"full_suite":set(cases)==set(manifest["scenarios"])}
    dump(target/"report.json",report)
    plan = LabelPlan({d:manifest["dimensions"][d] for d in DIMENSIONS})
    assert [list(x) for x in plan.archetypes] == manifest["packed_coordinates"]["Archetipo"]
    assert [list(x) for x in plan.configurations] == manifest["packed_coordinates"]["Configurazione"]
    dump(target/"mapping.json",{"original_dimensions":DIMENSIONS,"coordinates":plan.coords,
        "archetypes":plan.archetypes,"configurations":plan.configurations,
        "pairs":[{"original":a,"packed":b} for a,b in mapping(plan.coords)]})
    started = time.perf_counter()
    for case in cases:
        if not reference_ready(directory,manifest,[case],mode="diagnostic"):
            raise RuntimeError(f"Uncertified reference: {case}")
        prefix = directory/"reference/diagnostic"/case
        source_hashes = {suffix:digest(prefix.with_suffix(suffix)) for suffix in
                         (".json",".npz",".params.json",".provenance.json")}
        meta,arrays = load_snapshot(prefix)
        if meta["years"] != YEARS:
            raise ValueError("Truncated reference")
        rows = {}
        for name in manifest["six_dimensional"]:
            item = meta["variables"][name]
            if (item["dims"] != list(DIMENSIONS) or item["coords"] != plan.coords or
                    item["columns"] != columns_for(name,manifest)):
                raise ValueError(f"Unexpected real-state coordinates: {case}/{name}")
            values = arrays[name]
            if values.shape != (len(YEARS),int(np.prod(plan.shape))) or not np.isfinite(values).all():
                raise ValueError(f"Invalid real state: {case}/{name}")
            # Snapshot columns explicitly enumerate this product order. This
            # reshaping decodes the labelled snapshot; packing uses label maps.
            rows[name] = plan.audit(values.reshape((len(YEARS),*plan.shape)),case+"/"+name)
        if any(digest(prefix.with_suffix(suffix)) != sha for suffix,sha in source_hashes.items()):
            raise RuntimeError(f"Reference changed during audit: {case}")
        result = {"pass":True,"variables":rows,"snapshot":source_hashes,
                  "source_cells":sum(row["source_cells"] for row in rows.values()),
                  "comparisons":sum(row["comparisons"] for row in rows.values())}
        dump(target/f"{case}.json",result)
        report["cases"][case] = {"pass":True,"variables":len(rows),"comparisons":result["comparisons"],
                                "sha256":digest(target/f"{case}.json")}
        dump(target/"report.json",report)
        print(f"Packing operations {case}: PASS ({len(report['cases'])}/{len(cases)})",flush=True)
    check_sources(manifest)
    if hashes != {name:digest(path) for name,path in dependencies.items()}:
        raise RuntimeError("Audit implementation or manifest changed")
    report.update({"pass":True,"status":"complete","seconds":time.perf_counter()-started,
                   "mapping_sha256":digest(target/"mapping.json"),
                   "comparisons":sum(row["comparisons"] for row in report["cases"].values())})
    dump(target/"report.json",report)
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir",type=Path,required=True)
    parser.add_argument("--scenarios",nargs="+")
    args=parser.parse_args()
    run(args.run_dir,args.scenarios)
