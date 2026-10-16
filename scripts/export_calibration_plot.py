"""Export the explanatory calibration curves from the validated canonical model.

The three additional adoption summaries do not change equations or calibration.
Require exact agreement with every existing Python baseline output and the
unchanged strict tolerance against the retained Julia baseline before exporting.
"""
import argparse
import hashlib
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sure_julia.common import MODEL_REVISION, model_sources, dump
from sure_julia.catalog import inventory, outputs
from sure_julia.python_backend import PythonBackend
from sure_julia.runtime import frame_from_arrays
from sure_julia.validation import compare
from pv_batteries.history_data import CALIBRATION_INPUTS, calibration_observations

NAMES = ['Adoption Battery Type', 'Adoption HP Type', 'Adoption PV Type', 'Adoption Vehicles']


def export(baseline, destination):
    requested = list(dict.fromkeys(outputs() + NAMES))
    engine = PythonBackend(outputs=requested)
    try:
        arrays = engine.run_arrays()
    finally:
        engine.close()
    variables, dimensions = inventory()
    with np.load(baseline / 'python.npz') as original, np.load(baseline / 'julia.npz') as julia:
        if set(original.files) != set(outputs()) or set(julia.files) != set(original.files):
            raise ValueError('Incomplete validated baseline')
        if any(not np.array_equal(arrays[n], original[n]) for n in original.files):
            raise ValueError('Additional outputs changed the validated Python baseline')
        specs = [{'name': n, 'dims': variables[n].get('subscripts', []),
                  'coords': {d: dimensions[d] for d in variables[n].get('subscripts', [])}}
                 for n in original.files]
        comparison = compare({n: arrays[n] for n in original.files},
                             {n: julia[n] for n in julia.files}, specs)
        if not comparison['pass']:
            raise ValueError('Calibration extraction disagrees with the Julia baseline')
    specs = [{'name': n, 'dims': variables[n].get('subscripts', []),
              'coords': {d: dimensions[d] for d in variables[n].get('subscripts', [])}} for n in NAMES]
    frame = frame_from_arrays({n: arrays[n] for n in NAMES}, specs, flatten=True)
    observation_years = {tech: [int(y) for y in calibration_observations(tech).dropna().index]
                         for tech in CALIBRATION_INPUTS}
    years = sorted({y for available in observation_years.values() for y in available})
    frame = frame.reindex(years)
    if not years or not np.isfinite(frame.to_numpy()).all():
        raise ValueError('Invalid calibration plot data')
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index_label='Time')
    dump(destination.with_suffix('.json'), {
        'model_revision': MODEL_REVISION, 'model_sources': model_sources(),
        'years': years, 'observation_years': observation_years, 'outputs': NAMES,
        'engine': 'PySD 3.14.3; canonical calibration; synchronous DELAY FIXED; baseline policy',
        'validated_python_outputs_exact': len(outputs()), 'validated_julia_comparison_pass': comparison['pass'],
        'baseline_sha256': {n: hashlib.sha256((baseline/n).read_bytes()).hexdigest()
                            for n in ('python.npz', 'julia.npz')},
        'csv_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
    print(f'Exported {len(frame)} years; {len(outputs())} validated outputs unchanged')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    export(args.baseline, args.destination)
