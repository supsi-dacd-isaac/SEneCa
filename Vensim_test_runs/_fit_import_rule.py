"""Cerca la regola con cui Vensim assegna l'importazione dato il residuo."""
import numpy as np

ROOT = r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs"


def load(name):
    a = np.load(ROOT + "\\" + name)
    # year, hour, month, residual, import, cost
    return a


def summarize(name):
    a = load(name)
    r = a[:, 3]
    g = a[:, 4]
    c = a[:, 5]
    pos = r > 0
    err = g[pos] - r[pos]
    print(f"\n== {name}  n={len(a)} residual>0: {pos.sum()}")
    print(f"cost unique rounded: {np.unique(np.round(c, 3))[:12]}")
    exact = np.abs(err) < 1e-5
    zero = g[pos] == 0
    over = err > 1e-5
    under = err < -1e-5
    print(f"exact {exact.sum()}  import=0 {zero.sum()}  over {over.sum()}  under {under.sum()}")
    print(f"err p50 {np.median(err):.6f} p05 {np.quantile(err,0.05):.6f} p95 {np.quantile(err,0.95):.6f}")
    # band of residual where import is exactly 0
    rz = r[pos][zero]
    if len(rz):
        print(f"import=0 residual range {rz.min():.5f} .. {rz.max():.5f} n={len(rz)}")
    # for each cost, error vs residual correlation on the partial region
    for cost in np.unique(np.round(c[pos], 2)):
        m = pos & (np.abs(c - cost) < 0.02) & (r > 0) & (r < 0.02)
        if m.sum() < 5:
            continue
        e = g[m] - r[m]
        print(f"  cost {cost:.2f} n={m.sum()} exact {np.sum(np.abs(e)<1e-5)} "
              f"zero {np.sum(g[m]==0)} median err {np.median(e):.5f}")


for name in ("gap_base_import_residual.npy", "gap_high_import_residual.npy"):
    summarize(name)


def try_float32():
    """Root finder in float32 sulla sola curva di import, gli altri sono saturi."""
    a = load("gap_base_import_residual.npy")
    # solo ore in cui il residuo e' piccolo rispetto alla capacita 10: gli altri sono pieni
    m = (a[:, 3] > 0) & (a[:, 3] < 0.02)
    r = a[m, 3]
    g = a[m, 4]
    c = a[m, 5]
    width = np.float32(0.1)
    q0 = np.float32(10.0)

    def alloc_at(x, p):
        x = np.float32(x)
        left = np.float32(p - width * np.float32(0.5))
        right = np.float32(p + width * np.float32(0.5))
        if x <= left:
            return q0
        if x < right:
            return np.float32(q0 * (np.float32(1) - (x - left) / width))
        return np.float32(0)

    def solve(residual, cost, niter, x_lo, x_hi):
        p = np.float32(-np.float32(cost))
        target = np.float32(residual)
        lo = np.float32(x_lo)
        hi = np.float32(x_hi)
        for _ in range(niter):
            mid = np.float32((lo + hi) * np.float32(0.5))
            # quantita' totale = residuo pieno degli altri (gia' nel target) + import(x)
            # gli altri sono saturi per x a sinistra del loro bordo, cioe' per x < -55
            got = alloc_at(mid, p)
            if got > target:
                lo = mid  # troppo import, alza la priorita'
            else:
                hi = mid
        return float(alloc_at(np.float32((lo + hi) * np.float32(0.5)), p))

    print("\n== bisection float32, bracket [-200, 0]")
    for niter in (16, 20, 24, 30, 40):
        pred = np.array([solve(rr, cc, niter, -200, 0) for rr, cc in zip(r, c)])
        print(f"  niter {niter:2} max|d| {np.max(np.abs(pred-g)):.6e} "
              f"median {np.median(np.abs(pred-g)):.6e} nmatch {np.sum(np.abs(pred-g)<1e-4)}")


try_float32()
