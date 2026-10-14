"""Unit-aware derived indicators shared by Julia and native Vensim extraction."""
import numpy as np


def pv_self_coverage(self_consumed_gwh, district_demand_kwh):
    """Demand-weighted PV self-coverage, stored as a dimensionless fraction.

    Vensim's Total PV electricity SC is a sum of district PV production in
    GWh. Total annual demand Districts is in kWh. Sum all district demands
    before dividing; averaging district percentages gives a different KPI.
    """
    numerator = np.asarray(self_consumed_gwh, dtype=float)
    demand = np.asarray(district_demand_kwh, dtype=float)
    if numerator.ndim != 0 or demand.ndim != 1 or not demand.size:
        raise ValueError("Self-coverage requires one total and the district demand vector")
    if not np.isfinite(numerator).all() or not np.isfinite(demand).all():
        raise ValueError("Nonfinite self-coverage input")
    if numerator < 0 or np.any(demand < 0) or demand.sum() <= 0:
        raise ValueError("Self-coverage requires nonnegative energy and positive demand")
    denominator_gwh = float(demand.sum() / 1e6)
    ratio = float(numerator) / denominator_gwh
    if not np.isfinite(ratio) or ratio > 1 + 1e-10:
        raise ValueError("Self-consumed PV exceeds total electricity demand")
    return ratio, float(numerator), denominator_gwh
