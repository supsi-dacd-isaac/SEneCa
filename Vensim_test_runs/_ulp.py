"""L'import di Vensim e' la curva valutata alla radice arrotondata in float32?"""
import numpy as np

SUPPLIERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "Import", "PHS", "Coal", "Waste"]
COST = {"Solar": 2.0, "Wind": 1.0, "Nuclear": 10.0, "RoR": 11.0, "Hydro": 32.0,
        "PHS": 31.5, "Coal": 55.0, "Waste": 12.0}
raw = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_vectors.npy")
Q = np.maximum(raw[:, 7:16], 0.0)
dem = raw[:, 6]
imported = raw[:, 4]
cost = raw[:, 5]
width = np.float32(0.1)


def rect_sum(x, q, p):
    x = np.float32(x)
    total = np.float32(0)
    imp = np.float32(0)
    half = width * np.float32(0.5)
    for qi, pi, name in zip(q, p, SUPPLIERS):
        qi = np.float32(qi)
        if qi <= 0:
            continue
        left = np.float32(pi - half)
        right = np.float32(pi + half)
        if x <= left:
            got = qi
        elif x < right:
            got = np.float32(qi * (np.float32(1) - np.float32(x - left) / width))
        else:
            got = np.float32(0)
        total = np.float32(total + got)
        if name == "Import":
            imp = got
    return float(total), float(imp)


def priorities(cimp):
    p = []
    for name in SUPPLIERS:
        c = cimp if name == "Import" else COST[name]
        p.append(np.float32(-np.float32(c)))
    return p


# Per ogni ora, radice analitica e valutazione float32 li' e sugli ulp vicini
hits = {k: 0 for k in ("exact_f64", "f32_at_root", "f32_round_x", "nearest_ulp")}
worst = []
for i in range(len(raw)):
    p = priorities(cost[i])
    q = Q[i]
    domestic = float(q.sum() - q[5])
    residual = float(dem[i] - domestic)
    # radice: import = residual, x = right - residual/100
    right = float(p[5]) + 0.05
    x_star = right - residual / 100.0
    # import dalla formula float64
    imp64 = min(10.0, max(0.0, residual))
    # float32 x
    x32 = np.float32(x_star)
    _, imp32 = rect_sum(x32, q, p)
    # prova anche gli ulp intorno a x32
    x_bits = np.float32(x32).view(np.int32)
    best = None
    for delta in range(-8, 9):
        xx = np.array([x_bits + delta], dtype=np.int32).view(np.float32)[0]
        _, imp = rect_sum(xx, q, p)
        e = abs(imp - imported[i])
        if best is None or e < best[0]:
            best = (e, delta, imp)
    if abs(imp64 - imported[i]) < 1e-4:
        hits["exact_f64"] += 1
    if abs(imp32 - imported[i]) < 1e-4:
        hits["f32_at_root"] += 1
    if best[0] < 1e-4:
        hits["nearest_ulp"] += 1
    else:
        worst.append((best[0], residual, imported[i], best[2], best[1]))

print("hits", hits, "of", len(raw))
worst.sort(reverse=True)
print("worst remaining", len(worst))
for row in worst[:8]:
    print("  err", row)
