"""Prova risolutori sulla curva rettangolare e confrontali con Vensim."""
import numpy as np

SUPPLIERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "Import", "PHS", "Coal", "Waste"]
# costi costanti tranne Import, che sta nella colonna
COST = {"Solar": 2.0, "Wind": 1.0, "Nuclear": 10.0, "RoR": 11.0, "Hydro": 32.0,
        "PHS": 31.5, "Coal": 55.0, "Waste": 12.0}

raw = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_vectors.npy")
# year hour month residual import cost demand + 9 supplies
dem = raw[:, 6]
imported = raw[:, 4]
cost_imp = raw[:, 5]
Q = raw[:, 7:16]
bad = np.abs(imported - raw[:, 3]) > 1e-4


def run_solver(fn):
    pred = np.empty(len(raw))
    for i in range(len(raw)):
        pred[i] = fn(Q[i], cost_imp[i], dem[i])
    err = np.abs(pred - imported)
    return (float(np.max(err[bad])), float(np.median(err[bad])), int(np.sum(err[bad] < 1e-4)),
            float(np.max(err[~bad])), int(np.sum(err[~bad] < 1e-4)))


def make(dtype, niter, hmode, x0mode):
    width = dtype(0.1)

    def total_and_import(x, q, p):
        x = dtype(x)
        acc = dtype(0)
        imp = dtype(0)
        half = width * dtype(0.5)
        for qi, pi, name in zip(q, p, SUPPLIERS):
            qi = dtype(qi)
            if qi <= 0:
                continue
            left = pi - half
            right = pi + half
            if x <= left:
                got = qi
            elif x < right:
                got = qi * (dtype(1) - (x - left) / width)
            else:
                got = dtype(0)
            acc = dtype(acc + got)
            if name == "Import":
                imp = got
        return acc, imp

    def fn(q, cimp, demand):
        p = []
        for name in SUPPLIERS:
            c = cimp if name == "Import" else COST[name]
            p.append(dtype(-dtype(c)))
        p = np.array(p, dtype=dtype)
        q = np.array(q, dtype=dtype)
        demand = dtype(demand)
        if x0mode == "mid":
            x = dtype(-80)
        elif x0mode == "right":
            x = dtype(5)
        else:
            x = dtype(-200)
        eps = np.finfo(dtype).eps
        for _ in range(niter):
            f, _ = total_and_import(x, q, p)
            f = dtype(f - demand)
            if hmode == "rel":
                h = dtype(max(abs(float(x)) * np.sqrt(float(eps)), float(eps) * 10))
            elif hmode == "abs1e3":
                h = dtype(1e-3)
            elif hmode == "abs1e2":
                h = dtype(1e-2)
            elif hmode == "halfw":
                h = dtype(0.05)
            else:
                h = width
            fp_x, _ = total_and_import(dtype(x + h), q, p)
            fp = dtype((fp_x - (f + demand)) / h)
            if fp == 0 or not np.isfinite(float(fp)):
                x = dtype(x - width)
                continue
            step = dtype(f / fp)
            x = dtype(x - step)
        _, imp = total_and_import(x, q, p)
        return float(imp)

    return fn


print(f"{'solver':28} max_bad  med_bad  match_bad  max_good match_good")
for dtype, niter, hmode, x0 in [
    (np.float64, 8, "rel", "mid"),
    (np.float32, 8, "rel", "mid"),
    (np.float32, 20, "rel", "mid"),
    (np.float32, 20, "rel", "right"),
    (np.float32, 20, "rel", "left"),
    (np.float32, 12, "abs1e3", "right"),
    (np.float32, 12, "abs1e2", "right"),
    (np.float32, 12, "halfw", "right"),
    (np.float64, 12, "halfw", "right"),
    (np.float32, 30, "abs1e3", "left"),
]:
    label = f"{dtype.__name__} n={niter} {hmode} {x0}"
    mb, med, nb, mg, ng = run_solver(make(dtype, niter, hmode, x0))
    print(f"{label:28} {mb:8.5f} {med:8.5f} {nb:4} {mg:8.5f} {ng:4}")
