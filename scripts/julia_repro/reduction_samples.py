"""Check the NumPy reduction kernel against captured, real SURE SUM inputs."""
from __future__ import annotations

import itertools
from pathlib import Path

from .common import CONFIG, RUNTIME, digest, dump, read, run_logged
from .reduction_policy import ensure_policy, layout_plan


def oracle(directory, target, case="base"):
    """Reorder recorded cells only; expected results come from frozen Python."""
    import numpy as np

    directory, target = Path(directory).resolve(), Path(target).resolve()
    audit = directory / "debug/reduction-audit" / case
    report = read(audit / "result.json")
    if not report["pass"] or not report["uint64_bitwise"]:
        raise ValueError("Real SUM samples require a passing frozen-reference audit")
    for name in ("layouts.json", "samples.npz"):
        if digest(audit / name) != report["artifacts"][name]:
            raise ValueError(f"Changed reduction audit artifact: {name}")
    rows = []
    with np.load(audit / "samples.npz", allow_pickle=False) as samples:
        for record in read(audit / "layouts.json"):
            plan = layout_plan(record)
            array = samples[record["sample"]]
            expected = samples[record["sample"] + "_result"]
            reduced = record["reduce_axes"]
            kept = [axis for axis in range(array.ndim) if axis not in reduced]
            physical = record["physical_axes_slow_to_fast"]
            if list(array.shape) != record["shape"] or list(expected.shape) != record["result_shape"]:
                raise ValueError("Recorded SUM sample shape changed")
            if record["result_dims"] != [record["dims"][axis] for axis in kept]:
                raise ValueError("Recorded SUM result axes need an explicit coordinate permutation")
            vectors, results = [], []
            reduced_source_order = sorted(reduced)
            permutation = [reduced_source_order.index(axis) for axis in physical if axis in reduced]
            for index in itertools.product(*(range(array.shape[axis]) for axis in kept)):
                selection = [slice(None)] * array.ndim
                for axis, position in zip(kept, index):
                    selection[axis] = position
                cell = array[tuple(selection)]
                vectors.append(np.transpose(cell, permutation).ravel(order="C").tolist())
                results.append(float(expected[index]))
            rows.append({"shape": record["shape"], "reduced": reduced,
                         "transposed": bool(record["f_contiguous"] and not record["c_contiguous"]),
                         "blocksize": plan["blocksize"], "vectors": vectors, "expected": results,
                         "binding": record["binding"], "sample": record["sample"],
                         "component": record["component"]})
    dump(target / "oracles.json", rows)


def run(directory, case="base"):
    from .execution import julia_command

    directory = Path(directory).resolve()
    policy = ensure_policy(directory, case=case)
    target = directory / "reduction-samples" / case
    command = ("from scripts.julia_repro.reduction_samples import oracle; "
               f"oracle({str(directory)!r}, {str(target)!r}, case={case!r})")
    run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c", command], target / "oracle.log")
    run_logged([*julia_command(), CONFIG / "test_reduction_blocks.jl", target], target / "julia.log")
    result = read(target / "results.json")
    result.update({"scenario": case, "uint64_bitwise": result["pass"],
                   "evidence": policy["evidence"], "oracles_sha256": digest(target / "oracles.json"),
                   "implementation_sha256": digest(Path(__file__)),
                   "kernel_sha256": digest(CONFIG / "allocation.jl"),
                   "harness_sha256": digest(CONFIG / "test_reduction_blocks.jl")})
    dump(target / "results.json", result)
    return result
