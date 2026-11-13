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
    comparison = {'pass': 'pending'}
    if baseline is not None:
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
        'validated_python_outputs_exact': len(outputs()) if baseline is not None else 'pending',
        'validated_julia_comparison_pass': comparison['pass'],
        'baseline_sha256': None if baseline is None else {n: hashlib.sha256((baseline/n).read_bytes()).hexdigest()
                                                          for n in ('python.npz', 'julia.npz')},
        'csv_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
    print(f'Exported {len(frame)} years; Julia comparison: {comparison["pass"]}')


def mdl_defaults(mdl, names):
    """Constant values written in SURE.mdl: the configuration of the Vensim calibration run."""
    import re
    text = mdl.read_text(encoding='latin-1')
    values = {}
    for name in names:
        match = re.search(r'^"?' + re.escape(name) + r'"?\s*=\s*\n?\s*([-0-9.eE+]+)\s*\n?\s*~', text, re.M)
        if not match:
            raise ValueError(f'No constant definition for {name} in {mdl.name}')
        values[name] = float(match.group(1))
    return values


def vensim_tab(path):
    rows = {}
    for line in path.read_text(encoding='latin-1').splitlines():
        parts = line.split('\t')
        rows[parts[0]] = parts[1:]
    times = [float(t) for t in rows['Time']]
    # constants have a single value; empty cells (trailing tabs) are not values
    return {name: {t: float(v) for t, v in zip(times, values) if v.strip()}
            for name, values in rows.items() if name != 'Time'}


def export_native(destination, vensim_reference):
    """Calibration curves from the native build, run as Vensim's own base run.

    The native export does not include the four adoption summaries, so the build is
    copied to a temporary directory with an extended export.json (same model,
    inputs and calibration). The run uses the constants written in SURE.mdl, as
    the Vensim base run READCIN calibration.out; the result must agree with that
    Vensim run (VDF2TAB, 6 significant digits) before it is written.
    """
    import json
    import shutil
    import subprocess
    import tempfile
    from sure_julia.catalog import defaults
    from sure_julia.common import NATIVE_REVISION, digest, model_directory, read
    from sure_julia.runtime import JuliaBackend
    build = model_directory()
    source = ROOT / 'sure_native/model/SURE.mdl'
    if digest(source) != read(build / 'build.json')['sources']['SURE.mdl']:
        raise ValueError('sure_native/model/SURE.mdl is not the source of the native build')
    with tempfile.TemporaryDirectory(prefix='sure-calibration-') as temporary:
        copy = Path(temporary) / 'build'
        shutil.copytree(build, copy)
        export = read(copy / 'export.json')
        names = [v['name'] for v in export] + [n for n in NAMES if n not in {v['name'] for v in export}]
        (copy / 'names.txt').write_text('\n'.join(names) + '\n', encoding='utf-8')
        subprocess.run(['julia', '--startup-file=no', f'--project={ROOT / "sure_native"}',
                        str(ROOT / 'sure_native/scripts/webapp_export.jl'), str(source),
                        str(copy / 'names.txt'), str(copy / 'export.json')], check=True)
        (copy / 'names.txt').unlink()
        metadata = read(copy / 'build.json')
        metadata['artifacts']['export.json'] = digest(copy / 'export.json')
        (copy / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        params = mdl_defaults(source, defaults())
        engine = JuliaBackend(copy, timeout=900)
        try:
            arrays = engine.run_arrays(params, NAMES)
            specs = [v for v in engine.export if v['name'] in NAMES]
        finally:
            engine.close()
    frame = frame_from_arrays({n: arrays[n] for n in NAMES}, specs, flatten=True)
    reference = vensim_tab(vensim_reference)
    worst = 0.
    for column in frame.columns:
        if column not in reference:
            raise ValueError(f'{column} missing from the Vensim base run')
        series = reference[column]
        for year, value in frame[column].items():
            # Vensim saves one value for constants and none at FINAL TIME for flow-based summaries
            if float(year) not in series and len(series) > 1:
                continue
            expected = series.get(float(year), next(iter(series.values())))
            error = abs(value - expected) / max(1e-6, abs(expected))
            if abs(value - expected) > 1e-9 and error > worst:
                worst, where = error, (column, year, value, expected)
    if worst > 5e-5:
        raise ValueError(f'Native calibration run differs from Vensim: max relative error {worst:.2e} at {where}')
    observation_years = {tech: [int(y) for y in calibration_observations(tech).dropna().index]
                         for tech in CALIBRATION_INPUTS}
    years = sorted({y for available in observation_years.values() for y in available})
    frame = frame.reindex(years)
    if not years or not np.isfinite(frame.to_numpy()).all():
        raise ValueError('Invalid calibration plot data')
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(destination, index_label='Time')
    dump(destination.with_suffix('.json'), {
        'model_revision': NATIVE_REVISION, 'model_sources': read(build / 'build.json')['sources'],
        'years': years, 'observation_years': observation_years, 'outputs': NAMES,
        'engine': 'Native Julia translation of SURE.mdl (sure_native); constants as written in SURE.mdl; calibration.out',
        'parameters': params,
        'validated_vensim_comparison': {'reference': vensim_reference.name, 'max_relative_error': worst,
                                        'tolerance': 5e-5, 'pass': True},
        'csv_sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
    print(f'Exported {len(frame)} years from the native build; max relative error vs Vensim {worst:.1e}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--baseline', type=Path,
                        help='Validated python.npz/julia.npz; without it the Julia comparison stays pending')
    parser.add_argument('--native', type=Path, metavar='VENSIM_BASE_TAB',
                        help='Export from the native build and check it against this Vensim base run (.tab)')
    args = parser.parse_args()
    if args.native:
        export_native(args.destination, args.native)
    else:
        export(args.baseline, args.destination)
