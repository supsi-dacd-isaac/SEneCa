"""Quali caratteristiche separano le ore esatte da quelle sbagliate."""
import numpy as np

SUPPLIERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "Import", "PHS", "Coal", "Waste"]
raw = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_vectors.npy")
Q = raw[:, 7:16]
bad = np.abs(raw[:, 4] - raw[:, 3]) > 1e-4
print("bad", bad.sum(), "good", (~bad).sum())

def show(mask, title):
    q = Q[mask]
    print(f"\n{title}")
    for i, name in enumerate(SUPPLIERS):
        col = q[:, i]
        print(f"  {name:8} min={col.min():.5f} p50={np.median(col):.5f} max={col.max():.5f} frac0={np.mean(col<=0):.2f}")
    print(f"  residual p50={np.median(raw[mask,3]):.5f} min={raw[mask,3].min():.5f} max={raw[mask,3].max():.5f}")
    print(f"  demand  p50={np.median(raw[mask,6]):.5f}")

show(bad, "BAD")
show(~bad, "GOOD sample")

# correlazione dell'errore con ogni offerta, solo bad
err = raw[bad, 4] - raw[bad, 3]
print("\ncorr(err, feature) bad")
for i, name in enumerate(SUPPLIERS):
    c = np.corrcoef(err, Q[bad, i])[0, 1]
    print(f"  {name:8} {c:+.3f}")
print("  residual", np.corrcoef(err, raw[bad, 3])[0, 1])
print("  demand  ", np.corrcoef(err, raw[bad, 6])[0, 1])
print("  year    ", np.corrcoef(err, raw[bad, 0])[0, 1])
print("  month   ", np.corrcoef(err, raw[bad, 2])[0, 1])
print("  hour    ", np.corrcoef(err, raw[bad, 1])[0, 1])
