import numpy as np
SUPPLIERS = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "Import", "PHS", "Coal", "Waste"]
raw = np.load(r"c:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim_test_runs\gap_base_vectors.npy")
m = (raw[:, 3] > 0.12) & (raw[:, 3] < 0.13)
print("n", m.sum())
sub = raw[m]
order = np.argsort(sub[:, 3])
for row in sub[order]:
    year, hour, month, r, g, c, dem = row[:7]
    q = row[7:]
    print(f"\n{int(year)} M{int(month)} H{int(hour)} dem={dem:.6f} need={r:.6f} imp={g:.6f}")
    for name, qi in zip(SUPPLIERS, q):
        print(f"  {name:8} {qi:.6f}")
