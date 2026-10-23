"""Riepilogo PV condiviso tra simulazioni precalcolate e live."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from pv_batteries.i18n import tr

from pv_batteries.policy_labels import (
    BILL_SURCHARGE_EQUITY_HELP, BILL_SURCHARGE_EQUITY_LABEL,
    BILL_SURCHARGE_EQUITY_RADAR_LABEL,
)
from pv_batteries_config import FINAL_YEAR
from explore_results_charts import _LEGACY_PV_CAPACITY_BASES
from gmd import scale_gmd_equity
from section_ui import (
    GMD_DISPLAY_CAPTION, fmt_scaled_gmd, match_cols,
    metric_delta_vs_base, render_kpi_radar,
)

def total_pv_power_mw(df: pd.DataFrame, year: int) -> float | None:
    if year not in df.index:
        return None
    res_cols = match_cols(df, "PV residential power by Type")
    if not res_cols:
        return None
    res = df.loc[year, res_cols]
    if res.isna().all():
        return None
    nr_kw = sum(
        float(df.loc[year, base])
        for base in _LEGACY_PV_CAPACITY_BASES
        if base in df.columns and pd.notna(df.loc[year, base])
    )
    return float(res.sum()) + nr_kw / 1000.0


def total_pv_production_gwh(df: pd.DataFrame, year: int) -> float | None:
    cols = match_cols(df, "Total PV electricity production")
    if not cols or year not in df.index:
        return None
    val = df.loc[year, cols[0]]
    return None if pd.isna(val) else float(val)


def total_battery_mwh(df: pd.DataFrame, year: int) -> float | None:
    cols = match_cols(df, "Total Battery capacity District")
    if not cols or year not in df.index:
        return None
    row = df.loc[year, cols]
    if row.isna().all():
        return None
    return float(row.sum())


def avg_annual_cost_chf(df: pd.DataFrame, year: int) -> float | None:
    cols = match_cols(df, "Average electricity and heating and retrofit cost")
    if not cols or year not in df.index:
        return None
    val = df.loc[year, cols[0]]
    return None if pd.isna(val) else float(val)


def _fmt_metric(value: float | None, unit: str, *, decimals: int = 0) -> str:
    if value is None:
        return tr("n/d")
    return f"{value:.{decimals}f} {unit}"


def render_summary_metrics(
    df: pd.DataFrame,
    gmd_store: dict[str, dict],
    key: str,
    *,
    year: int,
    gmd_bounds: dict[str, tuple[float, float]],
    df_base: pd.DataFrame | None = None,
    base_key: str | None = None,
) -> None:
    """Indicatori principali al 2050: PV, batterie, costo, GMD levy/cost."""
    gmd_row = gmd_store.get(key, {})
    gmd_base_row = gmd_store.get(base_key, {}) if base_key else {}

    pv = total_pv_power_mw(df, year)
    prod = total_pv_production_gwh(df, year)
    bat = total_battery_mwh(df, year)
    cost = avg_annual_cost_chf(df, year)
    gmd_levy = scale_gmd_equity(
        gmd_row.get("gmd_levy"), *gmd_bounds["gmd_levy"]
    )
    gmd_cost = scale_gmd_equity(
        gmd_row.get("gmd_cost"), *gmd_bounds["gmd_cost"]
    )

    pv_base = total_pv_power_mw(df_base, year) if df_base is not None else None
    prod_base = (
        total_pv_production_gwh(df_base, year) if df_base is not None else None
    )
    bat_base = total_battery_mwh(df_base, year) if df_base is not None else None
    cost_base = avg_annual_cost_chf(df_base, year) if df_base is not None else None
    gmd_levy_base = (
        scale_gmd_equity(gmd_base_row.get("gmd_levy"), *gmd_bounds["gmd_levy"])
        if gmd_base_row else None
    )
    gmd_cost_base = (
        scale_gmd_equity(gmd_base_row.get("gmd_cost"), *gmd_bounds["gmd_cost"])
        if gmd_base_row else None
    )

    items = (
        ("Potenza PV totale", _fmt_metric(pv, "MW"), pv, pv_base, "normal"),
        (
            "Produzione PV totale (GWh)",
            _fmt_metric(prod, "GWh", decimals=0),
            prod,
            prod_base,
            "normal",
        ),
        ("Capacità batterie totale", _fmt_metric(bat, "MWh"), bat,
         bat_base, "normal"),
        ("Costo medio annuale", _fmt_metric(cost, "CHF"), cost,
         cost_base, "inverse"),
        (BILL_SURCHARGE_EQUITY_LABEL, fmt_scaled_gmd(gmd_levy), gmd_levy,
         gmd_levy_base, "normal"),
        ("Equità costo (GMD)", fmt_scaled_gmd(gmd_cost), gmd_cost,
         gmd_cost_base, "normal"),
    )
    for row in (items[:3], items[3:]):
        cols = st.columns(len(row))
        for col, (label, display, value, value_base, color) in zip(
            cols, row, strict=True,
        ):
            delta, delta_color = metric_delta_vs_base(value, value_base, color)
            if label == BILL_SURCHARGE_EQUITY_LABEL:
                help_text = BILL_SURCHARGE_EQUITY_HELP + " " + GMD_DISPLAY_CAPTION
            elif "Equità" in label:
                help_text = GMD_DISPLAY_CAPTION
            elif label == "Costo medio annuale":
                help_text = (
                    "Costo medio per economia domestica: comprende elettricità, "
                    "riscaldamento e i costi annualizzati di investimento per "
                    "tecnologie e risanamento."
                )
            else:
                help_text = None
            with col:
                with st.container(border=True, height="stretch"):
                    # Native Markdown wraps longer indicator names without truncation.
                    st.markdown(tr(label), help=tr(help_text))
                    st.metric(
                        tr(label), display, delta=delta, delta_color=delta_color,
                        label_visibility="collapsed",
                    )

    render_kpi_radar(
        [(BILL_SURCHARGE_EQUITY_RADAR_LABEL if label == BILL_SURCHARGE_EQUITY_LABEL else label,
          value, value_base) for label, _, value, value_base, _ in items],
        chart_key="kpi_radar_pv",
    )


KPI_EXPLANATION = f"""
Tutti gli indicatori sono riferiti al **{FINAL_YEAR}**; la variazione percentuale sotto
ogni valore è il confronto con lo scenario Base.

- **Potenza PV totale** — potenza fotovoltaica installata sul territorio, somma degli
  impianti residenziali e di quelli non residenziali di ogni taglia.
- **Produzione PV totale** — energia elettrica prodotta dagli impianti fotovoltaici
  nell'anno, in GWh.
- **Capacità batterie totale** — capacità di accumulo installata, sommata sugli otto
  distretti.
- **Costo medio annuale** — spesa media di una famiglia per elettricità, riscaldamento
  e risanamento dell'edificio.

### Gli indici di equità

I due indici di equità misurano **quanto diversamente il costo della transizione ricade
sulle famiglie**, non quanto è alto. Partono dalla *Gini Mean Difference* pesata,
cioè la differenza media in valore assoluto fra tutte le coppie di archetipi di
famiglia, pesata per quante famiglie rappresenta ciascun archetipo:

$$\\mathrm{{GMD}} = \\frac{{\\sum_i \\sum_j w_i w_j\\, |x_i - x_j|}}{{2\\,W^2}}$$

Vale zero quando tutti gli archetipi sopportano esattamente lo stesso onere, e cresce
via via che le situazioni divergono.

- **{BILL_SURCHARGE_EQUITY_LABEL}** — il supplemento sulla bolletta elettrica finanzia
  gli incentivi e gli altri oneri rappresentati nel modello. La grandezza $x$ è il
  saldo cumulato fra supplementi pagati e incentivi PV ricevuti da ciascun archetipo.
  Risponde alla domanda: chi finanzia gli incentivi e
  chi invece li incassa?
- **Equità costo** — la grandezza $x$ è il costo annuo totale per energia e risanamento
  di ciascun archetipo.

**Come leggere il numero.** Il GMD grezzo è in CHF e poco interpretabile da solo, quindi
viene riscalato su una scala da 0 a 1 usando il valore minimo e massimo osservati
**sull'intero store degli scenari precalcolati**: 1 identifica lo scenario più equo
fra quelli disponibili, 0 il meno equo. È quindi un indice **relativo** al ventaglio di
scenari, non una misura assoluta di equità: un valore di 0.5 significa "a metà strada
fra lo scenario migliore e quello peggiore", e i valori cambierebbero se si cambiasse
la griglia degli scenari.
"""
