"""Build/check the canonical calibration from the five supplied Vensim OUT files."""
from pathlib import Path
import argparse
import hashlib
import json
import pickle
import re
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FILES = ('Energy cost.out', 'PV power.out', 'Renovation.out',
         'PV and Battery and HS and HP.out', 'Vehicle.out')


def parse(directory):
    values, sources = {}, {}
    for name in FILES:
        path = directory / name
        assigned = 0
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip() or line.startswith(':'):
                continue
            match = re.fullmatch(r'\s*[-+\d.eE]+\s*<=\s*(.*?)\s*=\s*([-+\d.eE]+)\s*<=\s*[-+\d.eE]+\s*', line)
            if not match:
                raise ValueError(f'Invalid calibration line in {name}: {line}')
            key, value = match[1], float(match[2])
            if not np.isfinite(value) or key in values:
                raise ValueError(f'Nonfinite or duplicate calibration: {key}')
            values[key] = value
            assigned += 1
        if not assigned:
            raise ValueError(f'Empty calibration file: {name}')
        sources[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'assignments': assigned}
    if len(values) != 56:
        raise ValueError('Expected all 56 calibration assignments')
    return values, sources


def prepare(check=False):
    import sure_paths as paths
    import sure_pysd as sp
    paths.set_variant('v7')
    values, sources = parse(ROOT / 'Vensim/calibration')
    model = sp.load_model(prune=False)
    params = {}
    for label, value in values.items():
        name, sub = re.fullmatch(r'(.*?)(?:\[([^]]+)\])?', label).groups()
        real = sp.namespace_key(model, name)
        if real is None:
            raise ValueError(f'Unknown calibration parameter: {name}')
        if sub is None:
            params[real] = value
        else:
            if real not in params:
                params[real] = getattr(model.components, model._namespace[real])().copy(deep=True)
            array = params[real]
            coords = sub.split(',')
            if len(coords) != len(array.dims):
                raise ValueError(f'Wrong calibration dimensions: {label}')
            array.loc[dict(zip(array.dims, coords))] = value
    for name in ('Coeff VeryLow', 'Coeff Low', 'Coeff Moderate', 'Coeff High'):
        params[name].loc[{'Type': 'DFH'}] = params[name].sel(Type='SFH').values
    exported = {}
    for name, value in sorted(params.items()):
        dims = list(getattr(value, 'dims', ()))
        exported[name] = {'dims': dims,
            'coords': {d: list(map(str, value.coords[d].values)) for d in dims},
            'values': value.values.tolist() if dims else float(value)}
    manifest = {'schema': 1, 'variant': 'v7', 'source': 'Model (1).zip supplied 2026-10-16',
        'archive_sha256': '482a6135aa31b76725b65d3423ffc239c051ab362a88387a63b66b5d297bcbdd',
        'files': sources, 'assignments': len(values), 'groups': len(exported),
        'precision': 'Decimal values from OUT loaded as Float64; no recalibration performed',
        'parameters': exported}
    target = ROOT / 'constants_ref_v7.pkl'
    audit = ROOT / 'Vensim/calibration/manifest.json'
    if check:
        if pickle.loads(target.read_bytes()) != exported or json.loads(audit.read_text()) != manifest:
            raise ValueError('Calibration artifacts do not match supplied OUT files')
    else:
        target.write_bytes(pickle.dumps(exported, protocol=4))
        audit.write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n')
    print(f'Verified {len(values)} assignments in {len(exported)} calibrated groups')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    prepare(parser.parse_args().check)
