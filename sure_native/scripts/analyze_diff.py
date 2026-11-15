"""Prima divergenza per variabile tra un'uscita Julia e il riferimento Vensim."""
import sys, collections
import numpy as np
ref, jl = sys.argv[1], sys.argv[2]
thr = float(sys.argv[3]) if len(sys.argv) > 3 else 1e-6
names = open(f"{ref}/names.txt", encoding="utf-8").read().split("\n")[:-1]
T = len(np.fromfile(f"{ref}/times.f64"))
R = np.fromfile(f"{ref}/values.f64").reshape(len(names), T)
J = np.fromfile(f"{jl}/values.f64").reshape(len(names), T)
st = np.fromfile(f"{ref}/status.u8", dtype=np.uint8)
scale = np.nanmax(np.abs(R), axis=1, initial=0.0)
floor = np.maximum(1e-12, 1e-10 * scale)
na = (R <= -1e33) & (J <= -1e33)
err = np.abs(J - R) / np.maximum(np.abs(R), floor[:, None])
err[np.isnan(R) | na] = 0.0
tol = np.where(st == 0, thr, max(thr, 1e-5))
atol = np.where(st == 0, 1e-10, 1e-6) * scale + 1e-12   # 1e-12: rumore di arrotondamento attorno a zero
diff = np.abs(J - R); diff[np.isnan(R) | na] = 0.0
bad = diff > tol[:, None] * np.abs(np.nan_to_num(R)) + atol[:, None]
first = np.where(bad.any(axis=1), bad.argmax(axis=1), T)
byvar = collections.defaultdict(lambda: [T, 0.0, 0, ""])
for i, nm in enumerate(names):
    if first[i] == T: continue
    v = nm.split("[")[0]
    e = byvar[v]
    if first[i] < e[0]: e[0] = first[i]; e[3] = nm
    e[1] = max(e[1], err[i].max()); e[2] += 1
print("serie fuori soglia:", int((first < T).sum()), "variabili:", len(byvar))
for v, (f, m, n, ex) in sorted(byvar.items(), key=lambda kv: (kv[1][0], -kv[1][1]))[:int(sys.argv[4]) if len(sys.argv) > 4 else 40]:
    i = names.index(ex)
    print(f"{2011+f}\t{m:.3g}\t{n}\t{v}\t| {ex}: jl={J[i,f]:.10g} vensim={R[i,f]:.10g}")
