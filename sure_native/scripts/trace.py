"""Confronta al primo istante tutte le celle delle variabili indicate (Julia vs Vensim)."""
import sys, numpy as np
ref, jl, k = sys.argv[1], sys.argv[2], int(sys.argv[3])
pats = [p.lower() for p in sys.argv[4:]]
names = open(f"{ref}/names.txt", encoding="utf-8").read().split("\n")[:-1]
T = len(np.fromfile(f"{ref}/times.f64"))
R = np.fromfile(f"{ref}/values.f64").reshape(len(names), T)
J = np.fromfile(f"{jl}/values.f64").reshape(len(names), T)
st = np.fromfile(f"{ref}/status.u8", dtype=np.uint8)
for i, nm in enumerate(names):
    base = nm.split("[")[0].lower()
    if base in pats:
        r, j = R[i, k], J[i, k]
        rel = abs(j - r) / max(abs(r), 1e-300)
        flag = "  <<" if rel > 1e-7 and not (np.isnan(r)) else ""
        print(f"{nm}\tst={st[i]}\tjl={j:.12g}\tvensim={r:.12g}\trel={rel:.2e}{flag}")
