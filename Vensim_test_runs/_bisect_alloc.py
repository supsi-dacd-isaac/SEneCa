"""Riproduce la ricerca di Vensim sul profilo rettangolare e confronta due ore note."""
import numpy as np

COSTS = {
    "Solar": 2.0, "Wind": 1.0, "Nuclear": 10.0, "RoR": 11.0,
    "Hydro": 32.0, "PHS": 31.5, "Coal": 55.0, "Waste": 12.0, "Import": 157.20,
}

def alloc_at(x, supply, priority, width):
    out = np.empty_like(supply)
    half = width * 0.5
    for i, (q, p) in enumerate(zip(supply, priority)):
        if q <= 0:
            out[i] = 0.0
        elif x <= p - half:
            out[i] = q
        elif x >= p + half:
            out[i] = 0.0
        else:
            out[i] = q * (1.0 - (x - (p - half)) / width)
    return out


def search(supply, costs, demand, width=0.1, tol=1e-4, bracket=1e-3, iters=60):
    names = list(costs)
    q = np.array([supply[n] for n in names], dtype=np.float64)
    p = -np.array([costs[n] for n in names], dtype=np.float64)
    lo, hi = -400.0, 20.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        got = alloc_at(mid, q, p, width)
        err = got.sum() - demand
        if abs(err) <= tol or (hi - lo) <= bracket:
            return dict(zip(names, got)), err, mid
        # piu' priorita' bassa (x grande) riduce l'allocazione
        if err > 0:
            lo = mid
        else:
            hi = mid
    got = alloc_at(0.5 * (lo + hi), q, p, width)
    return dict(zip(names, got)), got.sum() - demand, 0.5 * (lo + hi)


# Ora in cui Vensim lascia l'import a 0 (residuo 0.00297)
miss = {"Solar": 0.0, "Wind": 0.00320, "Nuclear": 0.04044, "RoR": 0.10850,
        "Hydro": 0.08323, "PHS": 0.00869, "Coal": 0.0, "Waste": 0.01796, "Import": 10.0}
# Ora in cui Vensim assegna un import piccolo
hit = {"Solar": 0.0, "Wind": 0.00408, "Nuclear": 0.04044, "RoR": 0.08905,
       "Hydro": 0.13265, "PHS": 0.05339, "Coal": 0.00592, "Waste": 0.01796, "Import": 10.0}

for label, sup, demand in (
    ("miss", miss, 0.26499146),
    ("hit", hit, 0.34391201),
):
    print(f"\n{label} domanda={demand:.5f} capacita senza import={sum(v for k, v in sup.items() if k != 'Import'):.5f}")
    for tol, bracket in ((1e-6, 1e-6), (1e-3, 1e-4), (5e-3, 0.05), (1e-2, 0.2)):
        out, err, x = search(sup, COSTS, demand, tol=tol, bracket=bracket)
        print(f"  tol={tol:.0e} bracket={bracket:.0e} import={out['Import']:.6f} err={err:.3e} x={x:.3f}")
