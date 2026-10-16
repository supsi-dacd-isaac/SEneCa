"""Secante e falsa posizione, con un numero fisso di iterazioni, in float32."""
import numpy as np

SUPPLIERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "Import", "PHS", "Coal", "Waste"]
COST = np.array([2.0, 1.0, 10.0, 11.0, 32.0, 0.0, 31.5, 55.0, 12.0])  # Import filled later
IMP = 5

raw = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_vectors.npy")
dem = raw[:, 6]
imported = raw[:, 4]
cost_imp = raw[:, 5]
Q = np.maximum(raw[:, 7:16], 0)
bad = np.abs(imported - raw[:, 3]) > 1e-4


def alloc_import(x, q, p, width, dtype):
    x = dtype(x)
    half = dtype(width) * dtype(0.5)
    imp = dtype(0)
    total = dtype(0)
    for qi, pi, i in zip(q, p, range(len(q))):
        qi = dtype(qi)
        if qi <= 0:
            continue
        left = dtype(pi - half)
        right = dtype(pi + half)
        if x <= left:
            got = qi
        elif x < right:
            got = dtype(qi * (dtype(1) - (x - left) / dtype(width)))
        else:
            got = dtype(0)
        total = dtype(total + got)
        if i == IMP:
            imp = got
    return total, imp


def score(method, niter, dtype, lo, hi):
    err_bad = []
    err_good = []
    match_b = match_g = 0
    for i in range(len(raw)):
        p = -np.array(COST, dtype=dtype)
        p[IMP] = dtype(-cost_imp[i])
        q = np.array(Q[i], dtype=dtype)
        target = dtype(dem[i])
        a, b = dtype(lo), dtype(hi)
        fa = dtype(alloc_import(a, q, p, 0.1, dtype)[0] - target)
        fb = dtype(alloc_import(b, q, p, 0.1, dtype)[0] - target)
        x = b
        for _ in range(niter):
            if method == "bisect":
                x = dtype((a + b) / dtype(2))
            elif method == "regula":
                den = dtype(fb - fa)
                x = b if den == 0 else dtype(b - fb * (b - a) / den)
            elif method == "illinois":
                den = dtype(fb - fa)
                x = b if den == 0 else dtype(b - fb * (b - a) / den)
            fx = dtype(alloc_import(x, q, p, 0.1, dtype)[0] - target)
            if method == "illinois" and fx * fb > 0:
                fa = dtype(fa / dtype(2))
            if fx > 0:
                # troppa offerta: la priorita' di mercato e' piu' alta
                a, fa = x, fx
            else:
                b, fb = x, fx
        imp = float(alloc_import(x, q, p, 0.1, dtype)[1])
        e = abs(imp - imported[i])
        if bad[i]:
            err_bad.append(e)
            match_b += e < 1e-4
        else:
            err_good.append(e)
            match_g += e < 1e-4
    eb = np.array(err_bad)
    eg = np.array(err_good)
    print(f"{method:8} {dtype.__name__:8} n={niter:2} [{lo},{hi}] "
          f"maxb={eb.max():.5f} medb={np.median(eb):.5f} mb={match_b:3} "
          f"maxg={eg.max():.5f} mg={match_g:2}")


for method in ("bisect", "regula", "illinois"):
    for dtype in (np.float64, np.float32):
        for niter in (12, 16, 20, 24, 32):
            score(method, niter, dtype, -200, 5)
