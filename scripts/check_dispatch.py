"""Focused dispatch handoff: fixture, Python base/high, then native comparison.

python scripts/check_dispatch.py --prepare
python scripts/check_dispatch.py --python
python scripts/check_dispatch.py --native-fixture PATH.vpmx --native-model PATH.vpmx
Native packages must be freshly published from this branch's sources.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_checks.dispatch_validation import (
    cases, write_fixture, physical, SUPPLIERS, DISPATCH, CAPACITY, DEMAND, BALANCE, UNSERVED,
)
import sure_paths as paths

OUTPUTS = [DISPATCH, CAPACITY, DEMAND, BALANCE, UNSERVED,
           'Hourly imported electricity', 'Seasonal PHS hourly production',
           'Electricity market price', 'Energy price', 'Electricity price',
           'Power by Type', 'Annual CO2 emissions']
YEARS = np.arange(2011, 2051)
DEST = ROOT / 'dist/dispatch-check'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def native_frame(ven, run_name, columns, times):
    values = {}
    for label in columns:
        values[label] = ven.series(run_name, label, times)
        if values[label] is None:
            raise AssertionError(f'Native series missing: {label}')
    df = pd.DataFrame(values, index=times)
    assert np.isfinite(df.to_numpy()).all(), 'Missing timestamps or non-finite native output'
    return df


def columns_for(df, variable):
    return [c for c in df if c == variable or c.startswith(variable + '[')]


def check_physical(df):
    # Build supplier order explicitly; never depend on flattening or set order.
    demand_cols = columns_for(df, DEMAND)
    demand = df[demand_cols].to_numpy()
    def tensor(variable):
        return np.stack([df[[f'{variable}{col[len(DEMAND):-1]},{supplier}]'
                           for col in demand_cols]].to_numpy() for supplier in SUPPLIERS], axis=-1)
    report = physical(tensor(DISPATCH), tensor(CAPACITY), demand)
    # Unlike the synthetic capacity-shortfall case, both full SURE scenarios
    # have enough import capacity and must serve all demand.
    report['pass'] &= report['max_unserved'] <= 2e-6
    return report


def compare(left, right):
    assert left.index.equals(right.index) and left.columns.equals(right.columns)
    assert np.isfinite(left.to_numpy()).all() and np.isfinite(right.to_numpy()).all()
    rows = []
    for variable in OUTPUTS:
        cols = columns_for(left, variable)
        a, b = left[cols].to_numpy(), right[cols].to_numpy()
        assert a.size, f'Missing output: {variable}'
        err = np.abs(a - b)
        # Pointwise 0.1%, with a small scale floor for near-zero cells. No
        # annual aggregation may waive an hourly failure or a missing value.
        atol = max(1e-6, float(np.max(np.abs(b))) * 1e-6)
        passed = err <= atol + .001 * np.abs(b)
        i, j = np.unravel_index(np.argmax(err), err.shape)
        rows.append({'variable': variable, 'pass': bool(passed.all()),
                     'fail_cells': int((~passed).sum()), 'max_abs': float(err[i, j]),
                     'worst': f'{cols[j]} @ {left.index[i]}', 'atol': atol, 'rtol': .001})
    return rows


def fixture(native_path=None):
    import pysd
    path = DEST / 'dispatch_fixture.mdl'
    expected = write_fixture(path)
    fixture_columns = [f'{DISPATCH}[{month},H1,{supplier}]'
                       for month in ('M1', 'M2') for supplier in SUPPLIERS]
    ref = pd.DataFrame(np.tile(expected, (1, 2)), columns=fixture_columns)
    labels = [name for name, *_ in cases()]
    ref.insert(0, 'case', labels)
    ref.to_csv(DEST / 'fixture_expected.csv', index_label='Time')
    ref = ref.drop(columns='case')
    if native_path:
        from Vensim_test_runs._validate_coherence import Vensim
        ven = Vensim(native_path)
        run = str(DEST / 'native_fixture')
        ven._cmd(f'SIMULATE>RUNNAME|{run}')
        ven._cmd('MENU>RUN|O')
        actual = native_frame(ven, run, fixture_columns, ref.index.to_numpy())
        tolerance = 2e-6  # includes float32 DLL export; far below the old gaps
        name = 'native_fixture'
    else:
        import fix_allocate_sure
        pysd.read_vensim(path)
        py = path.with_suffix('.py')
        py.write_text(py.read_text().replace(fix_allocate_sure.PRIORITY_IMPORT,
                                             fix_allocate_sure.PRIORITY_WRAPPER))
        model = pysd.load(py)
        actual = model.run(return_columns=[DISPATCH])[fixture_columns]
        tolerance = 1e-7  # PySD embeds lookup coordinates rounded to 8 decimals
        name = 'python_fixture'
    error = np.abs(actual.to_numpy() - ref.to_numpy())
    report = {'cases': len(labels), 'supplier_cells': int(error.size),
              'max_abs': float(error.max()), 'atol': tolerance,
              'pass': bool(np.isfinite(error).all() and (error <= tolerance).all())}
    actual.to_csv(DEST / f'{name}.csv', index_label='Time')
    dump(DEST / f'{name}.json', report)
    print(name, report, flush=True)
    return report['pass']


def full_runs(native_path=None):
    import sure_pysd as sp
    from pysd_explore_config import ALL_INPUTS
    from sure_julia.synchronous_delays import install
    paths.set_variant('v6')
    model = sp.load_model(prune=True, outputs=OUTPUTS)
    install(model)
    const = sp.build_constant_params(model)
    assert const, 'Missing calibrated constants'
    scenarios = {'base': {i.name: float(i.default) for i in ALL_INPUTS},
                 'high': {i.name: float(max(i.values)) for i in ALL_INPUTS}}
    assert scenarios['base']['Provvedimento 1.3'] == 0
    assert scenarios['high']['Provvedimento 1.3'] == 1
    report = {}
    for name, inputs in scenarios.items():
        print(f'Running {name} 2011-2050 (synchronous delays)...', flush=True)
        assert all(sp.namespace_key(model, k) for k in inputs), 'Missing scenario lever'
        df = sp.run_scenario(model, const_params=const, scenario_inputs=inputs,
                             timestamps=YEARS, return_columns=OUTPUTS)
        assert np.array_equal(df.index, YEARS) and np.isfinite(df.to_numpy()).all()
        df.to_csv(DEST / f'{name}.python.csv.gz', index_label='Time')
        item = {'python_physical': check_physical(df)}
        item['pass'] = item['python_physical']['pass']
        if native_path:
            from Vensim_test_runs._validate_coherence import Vensim
            # Reload the package for each scenario; no SETVAL leaks.
            ven = Vensim(native_path)
            run = str(DEST / f'{name}.native')
            skipped, horizon = ven.run(run, inputs)
            assert not skipped, f'Rejected SETVAL: {skipped}'
            assert horizon == 2050, f'Incomplete native horizon: {horizon}'
            native = native_frame(ven, run, df.columns, YEARS)
            native.to_csv(DEST / f'{name}.native.csv.gz', index_label='Time')
            item['native_physical'] = check_physical(native)
            item['comparison'] = compare(df, native)
            item['pass'] &= item['native_physical']['pass'] and all(r['pass'] for r in item['comparison'])
        report[name] = item
        dump(DEST / ('comparison.json' if native_path else 'python_full.json'), report)
        print(name, json.dumps(item), flush=True)
    dump(DEST / 'scenarios.json', scenarios)
    return all(r['pass'] for r in report.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--python', action='store_true')
    parser.add_argument('--native-fixture', type=Path)
    parser.add_argument('--native-model', type=Path)
    args = parser.parse_args()
    assert args.prepare or args.python or args.native_fixture or args.native_model
    DEST.mkdir(parents=True, exist_ok=True)
    # Resolve before the DLL changes the process's working directory.
    native_fixture = args.native_fixture.resolve() if args.native_fixture else None
    native_model = args.native_model.resolve() if args.native_model else None
    passed = True
    if args.prepare or args.python or native_fixture:
        passed &= fixture(native_fixture)
    if args.python or native_model:
        passed &= full_runs(native_model)
    import pysd
    sources = [ROOT / p for p in ('Vensim/SURE.mdl', 'Vensim/SURE_pysd_v6.py',
                                  'constants_ref_v6.pkl')]
    sources += sorted((ROOT / 'Vensim').glob('*_pysd_v6.csv'))
    sources += [DEST / 'dispatch_fixture.mdl'] if (DEST / 'dispatch_fixture.mdl').exists() else []
    sources += [p for p in (native_fixture, native_model) if p]
    dump(DEST / 'manifest.json', {
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'working_tree_dirty': bool(subprocess.check_output(
            ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True).strip()),
        'pysd': pysd.__version__, 'pass': passed,
        'python_full_tested': bool(args.python or native_model),
        'native_fixture_tested': bool(native_fixture), 'native_full_tested': bool(native_model),
        'sha256': {str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p): digest(p) for p in sources},
    })
    print(f'Results: {DEST}', flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
