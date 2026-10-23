"""Riepilogo PV condiviso tra simulazioni precalcolate e live."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from pv_batteries.i18n import tr
from pv_batteries.responsive import wrapping_columns

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
        cols = wrapping_columns(len(row), key=f"pv_metrics_{row[0][0]}", metrics=True)
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

    st.caption(tr("Costo per famiglia: elettricità, riscaldamento e risanamento. Equità: scala 0–1 dei precalcolati, più alto = più equo."))
    render_kpi_radar(
        [(BILL_SURCHARGE_EQUITY_RADAR_LABEL if label == BILL_SURCHARGE_EQUITY_LABEL else label,
          value, value_base) for label, _, value, value_base, _ in items],
        chart_key="kpi_radar_pv",
    )


KPI_EXPLANATION = """Valori **al 2050**; variazioni rispetto allo scenario Base.

- **Potenza PV**: totale installato residenziale e non residenziale [MW].
- **Produzione PV**: energia prodotta al 2050 [GWh].
- **Capacità batterie**: energia accumulabile [MWh].
- **Costo annuo per famiglia**: elettricità, riscaldamento e investimenti annualizzati per impianti e risanamento [CHF].
- **Equità**: confronta gli oneri tra famiglie, non il loro livello medio. Per il supplemento considera pagamenti meno incentivi PV; per i costi considera energia e risanamento.

Gli indici di equità derivano dalla disuguaglianza monetaria (GMD), riscalata sui precalcolati: **0 = meno equo, 1 = più equo**. La scala è relativa agli scenari, non una percentuale."""
