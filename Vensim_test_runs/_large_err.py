import numpy as np
raw = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_vectors.npy")
# also the full residual table
a = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_import_residual.npy")
r, g = a[:, 3], a[:, 4]
err = g - r
m = (np.abs(err) > 1e-4) & (r > 0.02)
print("bad and residual>0.02:", m.sum())
order = np.argsort(-np.abs(err[m]))
print("need      import    err       rel")
for rr, gg in zip(r[m][order], g[m][order]):
    print(f"{rr:.6f}  {gg:.6f}  {gg-rr:+.6f}  {(gg-rr)/rr:+.4f}")

print("\nerror quantiles by residual size, ALL hours with residual>0")
for lo, hi in [(0, 0.01), (0.01, 0.02), (0.02, 0.05), (0.05, 0.1), (0.1, 1), (1, 20)]:
    sel = (r >= lo) & (r < hi)
    e = np.abs(err[sel])
    if sel.sum() == 0:
        continue
    print(f"  [{lo:.2f},{hi:.2f}) n={sel.sum():5}  n|e|>1e-4 {np.sum(e>1e-4):4}  "
          f"p95 {np.quantile(e,0.95):.5f}  max {e.max():.5f}")
