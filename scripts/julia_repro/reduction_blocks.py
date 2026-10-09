"""Exact reduction-kernel tests, independent of the model layout audit."""
from pathlib import Path
import itertools

from .common import CONFIG, RUNTIME, dump, read, run_logged


def oracle(target):
    import numpy as np
    target = Path(target)
    rng = np.random.default_rng(20261009)
    rows = []
    for shape in [(257,), (7, 24), (3, 8, 9), (2, 3, 8, 9),
                  (2, 2, 3, 8, 9), (2, 2, 2, 3, 8, 9)]:
        values = rng.choice([-1e16, -1., -.1, -1e-16, 0., 1e-16, .1, 1., 1e16], size=shape)
        for transpose in (False, True):
            array = values.T if transpose else values
            rank = array.ndim
            physical = sorted(range(rank), key=lambda axis: -array.strides[axis])
            for mask in range(1, 2**rank):
                reduced = [axis for axis in range(rank) if mask & (1 << axis)]
                kept = [axis for axis in range(rank) if axis not in reduced]
                blocksize = 1
                for axis in reversed(physical):
                    if axis not in reduced:
                        break
                    blocksize *= array.shape[axis]
                expected = np.asarray(np.sum(array, axis=tuple(reduced)))
                vectors, results = [], []
                for index in itertools.product(*(range(array.shape[axis]) for axis in kept)):
                    selection = [slice(None)]*rank
                    for axis, position in zip(kept, index):
                        selection[axis] = position
                    cell = array[tuple(selection)]
                    permutation = [reduced.index(axis) for axis in physical if axis in reduced]
                    vectors.append(np.transpose(cell, permutation).ravel(order="C").tolist())
                    results.append(float(expected[index]))
                rows.append({"shape": list(array.shape), "transposed": transpose,
                             "reduced": reduced, "blocksize": blocksize,
                             "vectors": vectors, "expected": results})
    dump(target / "oracles.json", rows)


def run(directory):
    from .execution import julia_command
    target = Path(directory).resolve() / "reduction-blocks"
    command = f"from scripts.julia_repro.reduction_blocks import oracle; oracle({str(target)!r})"
    run_logged([RUNTIME / "python-reference/bin/python", "-B", "-c", command], target / "oracle.log")
    run_logged([*julia_command(), CONFIG / "test_reduction_blocks.jl", target], target / "julia.log")
    return read(target / "results.json")
