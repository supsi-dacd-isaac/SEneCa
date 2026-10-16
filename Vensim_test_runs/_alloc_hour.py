"""Confronta i due allocatori di PySD con l'ora in cui Vensim lascia l'import a zero."""
import numpy as np
import xarray as xr
from pysd.py_backend.allocation import allocate_available, allocate_by_priority

suppliers = ["Solar", "Wind", "Nuclear", "RoR", "Hydro", "Import", "PHS", "Coal", "Waste"]
# 2043 M3 H18, valori Vensim
supply = np.array([0.00460, 0.00603, 0.01213, 0.07367, 0.27368, 10.0, 0.03477, 0.0, 0.01796])
demand = 0.425938
costs = np.array([2.0, 1.0, 10.0, 11.0, 32.0, 157.20, 31.5, 55.0, 12.0])
priority = -costs

req = xr.DataArray(supply, {"Supplier": suppliers}, ["Supplier"])
pri = xr.DataArray(priority, {"Supplier": suppliers}, ["Supplier"])
pp = xr.DataArray(
    np.column_stack([np.ones(len(suppliers)), priority, np.full(len(suppliers), 0.1), np.zeros(len(suppliers))]),
    {"Supplier": suppliers, "pprofile": ["ptype", "ppriority", "pwidth", "pextra"]},
    ["Supplier", "pprofile"],
)
by_pri = allocate_by_priority(req, pri, 0.1, demand)
avail_alg = allocate_available(req, pp, demand)
print("domanda", demand, "somma offerta nazionale", supply.sum() - 10)
print("by_priority", {s: round(float(by_pri.sel(Supplier=s)), 6) for s in suppliers})
print("allocate_available", {s: round(float(avail_alg.sel(Supplier=s)), 6) for s in suppliers})
print("non coperto by_priority", demand - float(by_pri.sum()))
print("non coperto allocate_available", demand - float(avail_alg.sum()))
