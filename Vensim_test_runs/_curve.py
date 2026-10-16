"""La curva import(residuo) sulle ore non esatte, per costo."""
import numpy as np

a = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_import_residual.npy")
r, g, c = a[:, 3], a[:, 4], a[:, 5]
err = g - r
m = (np.abs(c - 157.195) < 0.02) & (r < 0.03) & (np.abs(err) > 1e-4)
order = np.argsort(r[m])
print("need      import    err")
for rr, gg in zip(r[m][order], g[m][order]):
    print(f"{rr:.6f}  {gg:.6f}  {gg-rr:+.6f}")
