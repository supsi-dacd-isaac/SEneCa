"""Rendering stacked bar orari per la sezione Elettricità."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from echarts_charts import (
    _to_float_list,
    build_line_options,
    build_stacked_bar_options,
    pivot_to_stacked_series,
    render_echarts,
)
from section_store_hourly import (
    aggregate_annual_supplier,
    aggregate_monthly_supplier,
    hourly_snapshot,
)
from section_ui import (
    fmt_metric_value,
    pct_delta_vs_base,
    render_kpi_radar,
    render_section_nav,
    render_section_picker,
)

ELEC_SECTION_KEY = "elec_section"


def _label_supplier_frame(df: pd.DataFrame, cfg) -> pd.DataFrame:
    """Rinomina le colonne-supplier con le etichette italiane della config."""
    labels = getattr(cfg, "SUPPLIER_LABELS", None)
    if df.empty or not labels:
        return df
    return df.rename(columns=lambda c: labels.get(str(c), str(c)))

VIEW_ANNUAL = "Totale annuo"
VIEW_MONTHLY = "Profilo mensile"
VIEW_HOURLY = "Profilo orario"


def hourly_metric_value(
    spec: dict, df: pd.DataFrame | None, *, year: int,
) -> float | None:
    """Totale annuo della variabile oraria (opzionalmente per un supplier)."""
    if df is None or df.empty:
        return None
    annual = aggregate_annual_supplier(
        df, spec["variable"], spec.get("exclude_suppliers"),
    )
    if annual.empty or year not in annual.index:
        return None
    row = annual.loc[year]
    supplier = spec.get("supplier")
    if supplier is not None:
        if supplier not in annual.columns:
            return None
        value = row[supplier]
    else:
        value = row.sum()
    return None if pd.isna(value) else float(value)


def render_hourly_summary_metrics(
    metrics: list[dict],
    df: pd.DataFrame,
    *,
    year: int,
    key: str,
    df_base: pd.DataFrame | None = None,
    radar: bool = True,
) -> None:
    """KPI annuali della sezione oraria, con delta e radar vs scenario Base."""
    entries: list[tuple[str, float | None, float | None]] = []
    cols = st.columns(len(metrics))
    for col, spec in zip(cols, metrics, strict=True):
        value = hourly_metric_value(spec, df, year=year)
        value_base = hourly_metric_value(spec, df_base, year=year)
        if spec.get("radar", True):
            entries.append((spec["label"], value, value_base))
        with col:
            with st.container(border=True):
                st.metric(
                    spec["label"],
                    fmt_metric_value(
                        value, spec.get("unit"), decimals=spec.get("decimals", 0),
                    ),
                    delta=pct_delta_vs_base(value, value_base),
                )

    if radar:
        render_kpi_radar(entries, chart_key=f"kpi_radar_hourly_{key}")


def _chart_label_prefix(meta: dict) -> str:
    title = meta.get("title")
    if title:
        return title.split("|", 1)[0].strip()
    return meta.get("base", "Grafico")


def _compare_from_pivot(
    base_pivot: pd.DataFrame, labels: list[str],
) -> dict[str, list[float | None]] | None:
    if base_pivot.empty:
        return None
    compare = {
        str(col): _to_float_list(base_pivot[col].tolist())
        for col in base_pivot.columns
        if str(col) in labels
    }
    return compare or None


def render_area_line(
    pivot: pd.DataFrame,
    title: str,
    unit: str,
    *,
    chart_key: str,
    series_label: str = "Domanda",
) -> None:
    if pivot.empty:
        st.info(f"Nessun dato per {title}")
        return

    st.markdown(f"**{title}** ({unit})")
    categories, series = pivot_to_stacked_series(pivot)
    if len(series) == 1:
        series = {series_label: next(iter(series.values()))}
    options = build_line_options(categories, series, unit=unit, area=True)
    render_echarts(options, chart_key=chart_key, height=380)


def render_stacked_bar(
    pivot: pd.DataFrame,
    title: str,
    unit: str,
    *,
    chart_key: str,
    use_echarts: bool = False,
) -> None:
    if pivot.empty:
        st.info(f"Nessun dato per {title}")
        return

    st.markdown(f"**{title}** ({unit})")

    if use_echarts:
        categories, series = pivot_to_stacked_series(pivot)
        options = build_stacked_bar_options(categories, series, unit=unit)
        render_echarts(options, chart_key=chart_key, height=380)
        return

    st.bar_chart(pivot, sort=False)


def render_annual_supplier_line(
    df: pd.DataFrame, meta: dict, cfg,
    *, df_base: pd.DataFrame | None = None,
) -> None:
    annual = _label_supplier_frame(
        aggregate_annual_supplier(
            df, meta["base"], meta.get("exclude_suppliers"),
        ),
        cfg,
    )
    title = meta.get("title", f"{meta['base']} | totale annuo per supplier")
    if annual.empty:
        st.info(f"Nessun dato annuale per {meta['desc']}")
        return

    st.markdown(
        f"**{title}** ({meta['unit']}) — "
        f"{int(cfg.YEARS.start)}-{cfg.FINAL_YEAR}"
    )
    st.caption("Somma di tutte le ore e mesi dell'anno.")

    if meta.get("annual_echarts"):
        years = [int(y) for y in annual.index.tolist()]
        series = {
            str(col): [float(v) for v in annual[col].tolist()]
            for col in annual.columns
        }
        compare = None
        if df_base is not None:
            annual_base = _label_supplier_frame(
                aggregate_annual_supplier(
                    df_base, meta["base"], meta.get("exclude_suppliers"),
                ),
                cfg,
            )
            compare = _compare_from_pivot(annual_base, list(series.keys()))
        options = build_line_options(
            years,
            series,
            unit=meta["unit"],
            data_zoom=meta.get("annual_data_zoom", False),
            compare=compare,
        )
        render_echarts(
            options,
            chart_key=f"{meta['base']}_annual_supplier",
            height=460,
        )
        return

    st.line_chart(annual)


def render_monthly_supplier_bars(
    df: pd.DataFrame, meta: dict, cfg,
) -> None:
    st.markdown("**Profilo mensile per supplier**")
    prefix = _chart_label_prefix(meta)
    use_echarts = meta.get("stacked_echarts", False)
    cols = st.columns(len(cfg.DISPLAY_YEARS))

    for col, year in zip(cols, cfg.DISPLAY_YEARS, strict=True):
        with col:
            monthly = _label_supplier_frame(
                aggregate_monthly_supplier(
                    df, meta["base"], year, meta.get("exclude_suppliers"),
                    months=cfg.ALL_MONTHS,
                ),
                cfg,
            )
            title = f"{prefix} | {year}"
            render_stacked_bar(
                monthly,
                title,
                meta["unit"],
                chart_key=f"{meta['base']}_monthly_{year}",
                use_echarts=use_echarts,
            )


def render_hourly_section(
    df: pd.DataFrame, meta: dict, cfg,
) -> None:
    st.markdown("**Profilo orario**")
    prefix = _chart_label_prefix(meta)
    use_stacked = meta.get("stacked_echarts", False)
    use_area = meta.get("hourly_area_echarts", False)

    for month in cfg.DISPLAY_MONTHS:
        cols = st.columns(len(cfg.DISPLAY_YEARS))
        for col, year in zip(cols, cfg.DISPLAY_YEARS, strict=True):
            with col:
                snap = _label_supplier_frame(
                    hourly_snapshot(
                        df, meta["base"], month, year, meta["has_supplier"],
                        meta.get("exclude_suppliers"),
                    ),
                    cfg,
                )
                title = f"{prefix} | {month} | {year}"
                chart_key = f"{meta['base']}_hourly_{month}_{year}"
                if use_area:
                    render_area_line(
                        snap, title, meta["unit"], chart_key=chart_key,
                    )
                else:
                    render_stacked_bar(
                        snap,
                        title,
                        meta["unit"],
                        chart_key=chart_key,
                        use_echarts=use_stacked,
                    )


def _available_views(meta: dict) -> list[str]:
    """PHS e' salvato senza supplier: ha senso solo il profilo orario."""
    if meta.get("extended_layout"):
        return [VIEW_ANNUAL, VIEW_MONTHLY, VIEW_HOURLY]
    return [VIEW_HOURLY]


def _render_output(
    df: pd.DataFrame, meta: dict, cfg, *, df_base: pd.DataFrame | None,
) -> None:
    views = _available_views(meta)
    view = views[0]
    if len(views) > 1:
        view = st.selectbox("Grafico", views, key=f"elec_view_{meta['base']}")

    if view == VIEW_ANNUAL:
        render_annual_supplier_line(df, meta, cfg, df_base=df_base)
    elif view == VIEW_MONTHLY:
        render_monthly_supplier_bars(df, meta, cfg)
    else:
        render_hourly_section(df, meta, cfg)


def render_electricity_section(
    df: pd.DataFrame, cfg, values, *, df_base: pd.DataFrame | None = None,
    section_selector: bool = False,
) -> None:
    """Per output supplier: annuale / mensile / orario; PHS solo orario.

    Con `section_selector` si mostra una variabile alla volta, scelta da un
    selettore con i tasti avanti/indietro.
    """
    del values  # df gia' filtrato per combo

    outputs = cfg.OUTPUTS
    labels = active = None
    if section_selector:
        labels = [o["desc"] for o in cfg.OUTPUTS]
        active = render_section_picker(labels, key=ELEC_SECTION_KEY)
        outputs = [cfg.OUTPUTS[labels.index(active)]]

    for meta in outputs:
        st.subheader(meta["desc"])
        _render_output(df, meta, cfg, df_base=df_base)

    if labels:
        st.divider()
        render_section_nav(labels, active, key=ELEC_SECTION_KEY)
