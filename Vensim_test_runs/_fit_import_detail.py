"""Dettaglio delle ore in cui l'importazione Vensim non coincide col residuo."""
import numpy as np

a = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_import_residual.npy")
r, g, c = a[:, 3], a[:, 4], a[:, 5]
err = g - r
mask = np.abs(err) > 1e-5
print("non-exact", mask.sum())
# bins of residual
edges = [0, 0.001, 0.002, 0.0025, 0.003, 0.0035, 0.004, 0.005, 0.006, 0.008, 0.01, 0.02, 1, 100]
print("\nresidual bin | n | n_zero | n_under | n_over | median err | max|err|")
for lo, hi in zip(edges[:-1], edges[1:]):
    m = mask & (r >= lo) & (r < hi)
    if m.sum() == 0:
        continue
    e = err[m]
    print(f"  [{lo:.4f},{hi:.4f}) n={m.sum():4} zero={np.sum(g[m]==0):3} "
          f"under={np.sum(e<0):3} over={np.sum(e>0):3} med={np.median(e): .5f} max={np.max(np.abs(e)):.5f}")

print("\n-- under, residual<0.02, worst 30 --")
m = (err < -1e-5) & (r < 0.02)
idx = np.argsort(err[m])[:30]
sub = a[m][idx]
for row in sub:
    year, hour, month, rr, gg, cc = row
    print(f"  {int(year)} M{int(month)} H{int(hour)} need={rr:.5f} imp={gg:.5f} err={gg-rr:.5f} cost={cc:.3f}")

print("\n-- over, residual<0.02 --")
m = (err > 1e-5) & (r < 0.02)
sub = a[m][np.argsort(-err[m])]
print("n", len(sub))
for row in sub[:30]:
    year, hour, month, rr, gg, cc = row
    print(f"  {int(year)} M{int(month)} H{int(hour)} need={rr:.5f} imp={gg:.5f} err={gg-rr:.5f} cost={cc:.3f}")

print("\n-- import exactly 0 --")
m = (g == 0) & (r > 0)
for row in a[m][np.argsort(a[m, 3])]:
    year, hour, month, rr, gg, cc = row
    print(f"  {int(year)} M{int(month)} H{int(hour)} need={rr:.5f} cost={cc:.3f}")
