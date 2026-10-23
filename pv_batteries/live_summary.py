"""Indicatori live con le stesse definizioni dei risultati precalcolati."""
from __future__ import annotations

import streamlit as st
import pandas as pd
from pv_batteries.display_labels import LIVE_INDICATORS
from pv_batteries.i18n import tr

import pv_batteries_config as pv
import risanamento_config as ris
import veicoli_config as vei
from gmd import gmd_bounds_for_spec, gmd_from_frame, scale_gmd_equity
from pv_summary import KPI_EXPLANATION, render_summary_metrics
from section_store import load_gmd_store
from section_ui import render_configured_summary_metrics


@st.cache_data(show_spinner=False, max_entries=2)
def reference_bounds(section: str):
    cfg = {"PV e Batterie": pv, "Riscaldamento e Risanamento": ris}[section]
    return gmd_bounds_for_spec(load_gmd_store(cfg), cfg.GMD_SPEC)


def render_live_summary(section: str, df, df_base) -> None:
    cfg = {"PV e Batterie": pv, "Riscaldamento e Risanamento": ris, "Veicoli": vei}[section]
    st.subheader(tr('Indicatori principali ({v0})', v0=cfg.FINAL_YEAR))
    with st.expander(tr("Cosa misurano questi indicatori")):
        st.markdown(tr(KPI_EXPLANATION if cfg is pv else cfg.KPI_EXPLANATION))
    specs = getattr(cfg, "GMD_SPEC", {})
    bounds, rows = {}, {}
    if specs:
        bounds = reference_bounds(section)
        try:
            rows = {"scelta": gmd_from_frame(df, specs), "base": gmd_from_frame(df_base, specs)}
        except ValueError as error:
            st.warning(tr('Indici di equità non disponibili. Rilancia la simulazione. {v0}', v0=error))
    kwargs = dict(year=cfg.FINAL_YEAR, gmd_store=rows, key="scelta",
                  gmd_bounds=bounds, df_base=df_base, base_key="base")
    if cfg is pv:
        render_summary_metrics(df=df, **kwargs)
    else:
        render_configured_summary_metrics(cfg.SUMMARY_METRICS, df, **kwargs,
                                          radar_chart_key=f"live_radar_{section}")
    outside = [name for row in rows.values() for name, value in row.items()
               if (scaled := scale_gmd_equity(value, *bounds[name])) is not None
               and not 0 <= scaled <= 1]
    if outside:
        st.caption(tr("Questo scenario supera l’intervallo di equità dei precalcolati: "
                   "gli indici possono essere inferiori a 0 o superiori a 1. "
                   "La scala di riferimento resta la stessa; i valori non sono troncati."))


def build_comparison_table(base_df: pd.DataFrame, user_df: pd.DataFrame) -> pd.DataFrame:
    year = 2050.0
    rows = []
    for col in LIVE_INDICATORS:
        if col not in base_df.columns or col not in user_df.columns:
            continue
        b = float(base_df.loc[year, col]) if year in base_df.index else float("nan")
        u = float(user_df.loc[year, col]) if year in user_df.index else float("nan")
        d = u - b
        rel = d / b if abs(b) > 1e-12 else float("nan")
        label, unit = LIVE_INDICATORS[col]
        rows.append({
            "Indicatore": label,
            "Unità": unit,
            "Base 2050": b,
            "Scelta 2050": u,
            "Variazione": d,
            "Variazione [%]": rel * 100.0,
        })
    return pd.DataFrame(rows)
