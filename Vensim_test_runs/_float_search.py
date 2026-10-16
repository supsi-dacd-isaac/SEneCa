"""La ricerca in float32 cade dal lato opposto del bordo del rettangolo?"""
import numpy as np
from scipy.optimize import least_squares

def f_factory(supply, priority, width, demand, dtype):
    q = np.asarray(supply, dtype=dtype)
    p = np.asarray(priority, dtype=dtype)
    half = dtype(width) * dtype(0.5)
    demand = dtype(demand)
    def f(x):
        x = dtype(x[0])
        total = dtype(0)
        for qi, pi in zip(q, p):
            if qi <= 0:
                continue
            left = pi - half
            right = pi + half
            if x <= left:
                total += qi
            elif x < right:
                total += qi * (dtype(1) - (x - left) / dtype(width))
        return np.array([total - demand], dtype=np.float64)
    return f

# priorita = -costo
priority = -np.array([2, 1, 10, 11, 32, 31.5, 55, 12, 157.2])
# miss
q_miss = np.array([0, 0.00320, 0.04044, 0.10850, 0.08323, 0.00869, 0, 0.01796, 10.0])
# hit
q_hit = np.array([0, 0.00408, 0.04044, 0.08905, 0.13265, 0.05339, 0.00592, 0.01796, 10.0])

for name, q, demand in (("miss", q_miss, 0.26499146), ("hit", q_hit, 0.34391201)):
    print("\n", name)
    for dtype in (np.float64, np.float32):
        fun = f_factory(q, priority, 0.1, demand, dtype)
        sol = least_squares(fun, x0=np.array([-80.0]), bounds=(-200, 5), ftol=1e-8, xtol=1e-8)
        x = float(sol.x[0])
        # import e' l'ultimo
        imp_p = -157.2
        half = 0.05
        if x <= imp_p - half:
            imp = 10.0
        elif x >= imp_p + half:
            imp = 0.0
        else:
            imp = 10.0 * (1 - (x - (imp_p - half)) / 0.1)
        print(f"  {dtype.__name__:8} x={x:.6f} import={imp:.6f} cost={sol.cost:.3e} nfev={sol.nfev}")
