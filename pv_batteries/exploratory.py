"""Scoring e normalizzazione KPI per l'analisi esplorativa."""
from __future__ import annotations

import numpy as np
import pandas as pd

from exploratory_config import KPI_ORDER, KPI_SPEC, POLICY_ORDER


def scale_kpis(df: pd.DataFrame) -> pd.DataFrame:
    """Scala ogni KPI su [0, 1] rispetto a min/max di tutte le simulazioni.

    0 = peggiore, 1 = migliore. La direzione dipende da higher_is_better.
    """
    out = df.copy()
    for name in KPI_ORDER:
        raw = pd.to_numeric(df[name], errors="coerce")
        vmin = float(raw.min())
        vmax = float(raw.max())
        col = f"{name}_s"
        if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax == vmin:
            out[col] = np.where(raw.notna(), 1.0, np.nan)
            continue
        if KPI_SPEC[name]["higher_is_better"]:
            out[col] = (raw - vmin) / (vmax - vmin)
        else:
            out[col] = (vmax - raw) / (vmax - vmin)
    return out


def score_policy_mixes(
    scaled: pd.DataFrame, weights: dict[str, float],
) -> pd.DataFrame:
    """Score di ogni policy mix: media pesata dei KPI, media sugli scenari.

    Gli scenari di incertezza hanno tutti lo stesso peso. Righe con KPI
    mancanti vengono escluse dalla media del mix.
    """
    w = np.array([float(weights[k]) for k in KPI_ORDER], dtype=float)
    w_sum = w.sum()
    if w_sum <= 0:
        raise ValueError("I pesi dei KPI devono sommare a un valore positivo.")
    w = w / w_sum

    cols = [f"{k}_s" for k in KPI_ORDER]
    work = scaled.dropna(subset=cols, how="any").copy()
    work["sim_score"] = work[cols].to_numpy(dtype=float) @ w

    rows = []
    for pid, grp in work.groupby("policy_id", sort=True):
        first = grp.iloc[0]
        kpi_means = {k: float(grp[k].mean()) for k in KPI_ORDER}
        kpi_scaled_means = {
            f"{k}_s": float(grp[f"{k}_s"].mean()) for k in KPI_ORDER
        }
        rows.append({
            "policy_id": int(pid),
            "score": float(grp["sim_score"].mean()),
            "score_std": float(grp["sim_score"].std(ddof=0)),
            "n_samples": int(len(grp)),
            **{name: float(first[name]) for name in POLICY_ORDER},
            **kpi_means,
            **kpi_scaled_means,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values("score", ascending=False).reset_index(drop=True)


def top_n_mixes(ranked: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return ranked.head(n).copy()


def policy_value_shares(top: pd.DataFrame) -> dict[str, dict[float, float]]:
    """Frazione dei mix top-N che assumono ciascun valore di ogni leva."""
    if top.empty:
        return {}
    n = len(top)
    shares: dict[str, dict[float, float]] = {}
    for name in POLICY_ORDER:
        counts = top[name].value_counts(dropna=False)
        shares[name] = {float(val): float(cnt) / n for val, cnt in counts.items()}
    return shares
