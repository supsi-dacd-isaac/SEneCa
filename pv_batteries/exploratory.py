"""Scoring e normalizzazione KPI per l'analisi esplorativa."""
from __future__ import annotations

import numpy as np
import pandas as pd

from pv_batteries.exploratory_config import KPI_ORDER, KPI_SPEC, POLICY_ORDER, N_SAMPLES, all_policy_combos


def validate_kpi_store(df: pd.DataFrame) -> None:
    """Require the entire policy × sample grid before comparing policy mixes."""
    required = {"policy_id", "sample_id", "completed", *KPI_ORDER, *POLICY_ORDER,
                "pv_self_consumed_gwh", "electricity_demand_gwh"}
    if missing := required - set(df.columns):
        raise ValueError(f"Indicatori mancanti: {', '.join(sorted(missing))}")
    combos = all_policy_combos()
    expected = pd.MultiIndex.from_product([range(len(combos)), range(N_SAMPLES)])
    actual = pd.MultiIndex.from_frame(df[["policy_id", "sample_id"]])
    if len(df) != len(expected) or actual.has_duplicates or len(expected.difference(actual)):
        raise ValueError(f"Sono richieste {len(expected)} combinazioni distinte di policy e incertezza")
    if not np.isfinite(df[list(required)].to_numpy(dtype=float)).all() or not (df["completed"] == 1).all():
        raise ValueError("Il dataset contiene risultati mancanti, non finiti o incompleti")
    for pid, group in df.groupby("policy_id"):
        if not (group[POLICY_ORDER].to_numpy() == np.array([combos[int(pid)][n] for n in POLICY_ORDER])).all():
            raise ValueError(f"Parametri del policy mix {pid} non coerenti")
    demand = df["electricity_demand_gwh"].to_numpy()
    numerator = df["pv_self_consumed_gwh"].to_numpy()
    if np.any(demand <= 0) or np.any(numerator < 0):
        raise ValueError("Domanda o autoconsumo non validi")
    ratio = df["pv_self_coverage"].to_numpy()
    if not np.array_equal(ratio, numerator / demand) or np.any((ratio < 0) | (ratio > 1 + 1e-10)):
        raise ValueError("La copertura PV non coincide con il rapporto tra autoconsumo e domanda")


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

    Gli scenari di incertezza hanno tutti lo stesso peso. Valori mancanti
    interrompono il confronto, senza selezionare solo i casi favorevoli.
    """
    w = np.array([float(weights[k]) for k in KPI_ORDER], dtype=float)
    w_sum = w.sum()
    if not np.isfinite(w).all() or np.any(w < 0) or w_sum <= 0:
        raise ValueError("I pesi dei KPI devono sommare a un valore positivo.")
    w = w / w_sum

    cols = [f"{k}_s" for k in KPI_ORDER]
    if not np.isfinite(scaled[cols].to_numpy(dtype=float)).all():
        raise ValueError("Missing or nonfinite normalized indicators")
    work = scaled.copy()
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
