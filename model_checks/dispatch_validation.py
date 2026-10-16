"""Dispatch fixtures and an independent piecewise-linear rectangular oracle."""
from pathlib import Path
import re

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SUPPLIERS = ['Solar', 'Wind', 'Nuclear', 'RoR', 'Hydro', 'Import', 'PHS', 'Coal', 'Waste']
DISPATCH = 'Electricity dispatched'
CAPACITY = 'Dispatchable supply by supplier'
DEMAND = 'Hourly demand and PHS'
BALANCE = 'Electricity dispatch balance error'
UNSERVED = 'Unserved hourly electricity'


def rectangular(request, costs, demand, width=.1):
    """Invert the linear segments exactly; no iteration or PySD allocator."""
    q = np.maximum(request, 0.)
    if demand >= q.sum():
        return q
    if demand <= 0:
        return np.zeros_like(q)
    p = -np.asarray(costs)
    levels = np.unique(np.r_[p - width / 2, p + width / 2])[::-1]
    def at(level):
        return q * np.clip((p + width / 2 - level) / width, 0, 1)
    for upper, lower in zip(levels[:-1], levels[1:]):
        a, b = at(upper), at(lower)
        if a.sum() <= demand <= b.sum():
            # Interpolate allocations, avoiding cancellation at tiny residuals.
            return a + (b - a) * ((demand - a.sum()) / (b.sum() - a.sum()))
    raise AssertionError('Demand not bracketed')


def cases():
    rows = np.load(ROOT / 'Vensim_test_runs/gap_base_vectors.npy', allow_pickle=False)
    result = []
    costs = np.array([2, 1, 10, 11, 32, 157.2, 31.5, 55, 12.])
    for year, hour, month, residual, old_import, import_cost, demand, *q in rows:
        c = costs.copy()
        c[5] = import_cost
        result.append((f'{int(year)}-M{int(month)}-H{int(hour)}', np.array(q), c, demand))
    q = np.array([.2, .1, .3, .2, .5, 10, .1, .2, .1])
    for label, demand in [('zero', 0), ('tiny_import', 1.70004),
                          ('surplus', .05), ('exact_capacity', q.sum()),
                          ('shortfall', 20)]:
        result.append((label, q.copy(), costs.copy(), demand))
    for label, index, cost in [('tie', 0, 1), ('overlap', 0, 1.05),
                               ('cheap_import', 5, .5)]:
        c = costs.copy()
        c[index] = cost
        result.append((label, q.copy(), c, .15))
    negative = q.copy()
    negative[4] = -1
    result.append(('negative_hydro', negative, costs.copy(), 1.1))
    result.append(('no_capacity', np.zeros(9), costs.copy(), 1.))
    return result


def equation(source, name):
    return re.search(r'(?m)^' + re.escape(name) + r'(?:\[[^\]]+\])?\s*=.*?\|', source, re.S).group(0)


def write_fixture(path):
    """One native run replays all cases; Time is a case index, not a year."""
    fixtures = cases()
    n = len(fixtures)
    source = (ROOT / 'Vensim/SURE.mdl').read_text(encoding='latin-1')
    blocks = ['Month : M1,M2 ~~|', 'Hour : H1 ~~|', 'Supplier : ' + ','.join(SUPPLIERS) + ' ~~|']
    blocks += [equation(source, name) for name in
               (DISPATCH, CAPACITY, BALANCE, UNSERVED, 'Ppriority by supplier', 'Supplier priority width')]
    def lookup(name, values):
        pairs = ',\n'.join(f'({i},{v:.17g})' for i, v in enumerate(values))
        return f'{name} = WITH LOOKUP(Time, (\n{pairs}\n)) ~~|'
    expected = np.array([rectangular(q, c, d) for _, q, c, d in fixtures])
    # Explicit slices avoid PySD 3.14.3's scalar np.interp -> DataArray broadcast
    # issue, while exercising dispatch across more than one Month cell.
    blocks += [lookup(DEMAND + f'[{month},Hour]', [d for _, q, c, d in fixtures])
               for month in ('M1', 'M2')]
    for j, supplier in enumerate(SUPPLIERS):
        blocks += [lookup(f'Hourly available supply by Supplier[Month,Hour,{supplier}]',
                          [q[j] for _, q, c, d in fixtures]),
                   lookup(f'Marginal cost by supplier[{supplier}]', [c[j] for _, q, c, d in fixtures]),
                   lookup(f'Expected dispatch[Month,Hour,{supplier}]', expected[:, j])]
    blocks += ['Dispatch reference error[Month,Hour,Supplier] = '
               'Electricity dispatched[Month,Hour,Supplier] - Expected dispatch[Month,Hour,Supplier] ~~|']
    blocks += [f'{name} = {value} ~ case ~|' for name, value in
               [('INITIAL TIME', 0), ('FINAL TIME', n - 1), ('TIME STEP', 1), ('SAVEPER', 'TIME STEP')]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{UTF-8}\n' + '\n\n'.join(blocks), encoding='utf-8')
    return expected


def physical(dispatched, capacity, demand, atol=2e-6):
    """All cells, no masks or aggregation hiding missing/invalid values."""
    assert all(np.isfinite(a).all() for a in (dispatched, capacity, demand)), 'Non-finite data'
    assert (capacity >= 0).all(), 'Negative dispatchable capacity'
    balance = dispatched.sum(axis=-1) - np.minimum(demand, capacity.sum(axis=-1))
    report = {
        'max_balance_error': float(np.max(np.abs(balance))),
        'min_dispatch': float(dispatched.min()),
        'max_capacity_excess': float(np.max(dispatched - capacity)),
        'max_unserved': float(np.maximum(0, demand - dispatched.sum(axis=-1)).max()),
    }
    report['pass'] = (report['max_balance_error'] <= atol
                      and report['min_dispatch'] >= -atol
                      and report['max_capacity_excess'] <= atol)
    return report
