"""Misure di equity (Gini Mean Difference pesato) al 2050.

Ispirato a Notebook.ipynb (weighted_gmd_fast + allineamento valore/peso per
subscript). Qui si calcolano solo gmd_cost e gmd_levy, come richiesto.
"""
from __future__ import annotations

import numpy as np

from pv_batteries_config import GMD_SPEC


def weighted_gmd_fast(values, weights):
    """Weighted Gini Mean Difference.

        sum_i sum_j w_i w_j |x_i - x_j| / (2 * W^2)

    Formulazione con cumulative-sum su valori ordinati (identica al Notebook).
    """
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)

    mask = np.isfinite(values) & np.isfinite(weights) & (weights >= 0)
    values = values[mask]
    weights = weights[mask]

    W = weights.sum()
    if W == 0 or len(values) == 0:
        return np.nan

    order = np.argsort(values)
    x = values[order]
    w = weights[order]

    cum_w = np.cumsum(w)
    cum_wx = np.cumsum(w * x)
    cum_w_prev = cum_w - w
    cum_wx_prev = cum_wx - w * x

    pair_sum = np.sum(w * (x * cum_w_prev - cum_wx_prev))
    return pair_sum / W ** 2


def compute_gmd_from_spec(values_2050: dict[str, dict[str, float]],
                          spec_map: dict[str, dict]) -> dict[str, float]:
    """Calcola le misure GMD indicate in 'spec_map' dai valori 2050 per subscript.

    values_2050: {base_var: {combo_subscript: valore_2050}}
    spec_map: {nome_misura: {"value": var, "weight": var}}
    L'allineamento valore/peso avviene per stringa di subscript comune.
    """
    out: dict[str, float] = {}
    for name, spec in spec_map.items():
        vmap = values_2050.get(spec["value"], {})
        wmap = values_2050.get(spec["weight"], {})
        common = sorted(set(vmap) & set(wmap))
        if not common:
            out[name] = np.nan
            continue
        v = np.array([vmap[k] for k in common], dtype=float)
        w = np.array([wmap[k] for k in common], dtype=float)
        out[name] = weighted_gmd_fast(v, w)
    return out


def compute_gmd_measures(values_2050: dict[str, dict[str, float]]) -> dict[str, float]:
    """Come compute_gmd_from_spec ma con lo spec di default (sezione PV)."""
    return compute_gmd_from_spec(values_2050, GMD_SPEC)


def gmd_bounds(gmd_store: dict[str, dict], measure: str) -> tuple[float, float]:
    """Min/max GMD grezzo per una misura, su tutte le combo dello store."""
    vals = [
        float(row[measure])
        for row in gmd_store.values()
        if measure in row and np.isfinite(row[measure])
    ]
    if not vals:
        return (np.nan, np.nan)
    return (min(vals), max(vals))


def gmd_bounds_for_spec(
    gmd_store: dict[str, dict], gmd_spec: dict[str, dict],
) -> dict[str, tuple[float, float]]:
    return {name: gmd_bounds(gmd_store, name) for name in gmd_spec}


def scale_gmd_equity(
    raw: float | None, vmin: float, vmax: float,
) -> float | None:
    """Normalizza GMD su [0, 1]: 1 = minore disuguaglianza, 0 = maggiore."""
    if raw is None or not np.isfinite(raw):
        return None
    if not np.isfinite(vmin) or not np.isfinite(vmax):
        return None
    if vmax == vmin:
        return 1.0
    return float((vmax - raw) / (vmax - vmin))
