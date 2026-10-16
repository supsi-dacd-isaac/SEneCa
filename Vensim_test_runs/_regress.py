"""Regressione dell'errore di import sulle ore non esatte."""
import numpy as np

raw = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_vectors.npy")
# solo bad
bad = np.abs(raw[:, 4] - raw[:, 3]) > 1e-4
d = raw[bad]
r = d[:, 3]
g = d[:, 4]
dem = d[:, 6]
Q = np.maximum(d[:, 7:16], 0)
# colonne: 1, r, r^2, r^3, dem, q's
cols = [np.ones_like(r), r, r**2, r**3, dem]
for i in range(Q.shape[1]):
    cols.append(Q[:, i])
    cols.append(Q[:, i] * r)
X = np.column_stack(cols)
# predice g
coef, *_ = np.linalg.lstsq(X, g, rcond=None)
pred = X @ coef
print("bad n", len(g), "max|d|", np.max(np.abs(pred - g)), "median", np.median(np.abs(pred - g)),
      "R2", 1 - np.sum((pred - g)**2) / np.sum((g - g.mean())**2))

# modello piu' semplice: g = a + b r dentro fasce
print("\nfits within bands")
for lo, hi in ((0, 0.002), (0.002, 0.0033), (0.0033, 0.006), (0.006, 0.009), (0.009, 0.02), (0.02, 0.05), (0.1, 0.2)):
    m = (r >= lo) & (r < hi)
    if m.sum() < 3:
        print(f"  [{lo},{hi}) n={m.sum()}")
        continue
    A = np.column_stack([np.ones(m.sum()), r[m]])
    c, *_ = np.linalg.lstsq(A, g[m], rcond=None)
    hat = A @ c
    print(f"  [{lo:.4f},{hi:.4f}) n={m.sum():3}  g={c[0]:+.5f}{c[1]:+.3f}*r  max|d|={np.max(np.abs(hat-g[m])):.5f}")
