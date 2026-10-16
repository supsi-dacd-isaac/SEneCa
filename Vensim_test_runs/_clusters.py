import numpy as np
a = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_import_residual.npy")
r, g = a[:, 3], a[:, 4]
m = np.abs(g - r) > 1e-4
# clusters
for lo, hi in ((0.12, 0.13), (0.039, 0.043), (0.02, 0.025)):
    sel = m & (r >= lo) & (r < hi)
    print(f"\ncluster {lo}-{hi} n={sel.sum()}")
    for row in a[sel]:
        year, hour, month, rr, gg, cc = row
        print(f"  {int(year)} M{int(month)} H{int(hour)} need={rr:.5f} imp={gg:.5f}")
