"""Helper di rendering condivisi per le pagine Streamlit delle sezioni."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from gmd import gmd_bounds_for_spec, scale_gmd_equity

GMD_DISPLAY_CAPTION = (
    "Indice di equità normalizzato sullo store pre-calcolato "
    "(0 = maggiore disuguaglianza, 1 = minore disuguaglianza)."
)


def clean_base(base: str) -> str:
    return base.strip('"')


def match_cols(df: pd.DataFrame, base: str) -> list[str]:
    return [c for c in df.columns if c == base or c.startswith(base + "[")]


def elem_label(col: str, base: str) -> str:
    if col == base:
        return clean_base(base)
    return col[len(base) + 1:-1]


def fmt(x, spec: str) -> str:
    return format(x, spec) if x is not None and pd.notna(x) else "n/d"


def sim_incomplete(df: pd.DataFrame, final_year: int) -> bool:
    return final_year in df.index and bool(df.loc[final_year].isna().all())


def fmt_scaled_gmd(value: float | None) -> str:
    return fmt(value, ".3f")


def fmt_metric_value(
    value: float | None, unit: str | None = None, *, decimals: int = 0,
) -> str:
    if value is None:
        return "n/d"
    if unit is None:
        return fmt_scaled_gmd(value)
    return f"{value:.{decimals}f} {unit}"


def metric_delta_vs_base(
    cur: float | None, base: float | None, delta_color: str = "normal",
) -> tuple[str | None, str]:
    """Formatta il delta e lascia neutre le variazioni mostrate come zero."""
    if cur is None or base is None:
        return None, delta_color
    if base == 0:
        if cur == 0:
            return "0% vs Base", "off"
        return None, delta_color
    pct = (cur - base) / base * 100.0
    pct_display = f"{pct:.1f}"
    if float(pct_display) == 0:
        return "0.0% vs Base", "off"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct_display}% vs Base", delta_color


def pct_delta_vs_base(cur: float | None, base: float | None) -> str | None:
    return metric_delta_vs_base(cur, base)[0]


def _series_from_base(
    df: pd.DataFrame, base: str, elem: str | None = None,
) -> pd.Series:
    cols = match_cols(df, base)
    if elem is not None:
        cols = [c for c in cols if elem_label(c, base) == elem]
    if not cols:
        return pd.Series(dtype=float)
    if len(cols) == 1:
        return df[cols[0]]
    return df[cols].sum(axis=1)


def _metric_numeric_value(
    spec: dict,
    df: pd.DataFrame,
    *,
    year: int,
    gmd_row: dict | None = None,
    gmd_bounds: dict[str, tuple[float, float]] | None = None,
) -> float | None:
    if measure := spec.get("gmd"):
        if not gmd_row or not gmd_bounds:
            return None
        vmin, vmax = gmd_bounds[measure]
        return scale_gmd_equity(gmd_row.get(measure), vmin, vmax)

    series = _series_from_base(df, spec["base"], spec.get("elem"))
    if series.empty:
        return None
    if over := spec.get("over"):
        total = _series_from_base(df, over)
        if total.empty:
            return None
        series = series.divide(total.where(total != 0)) * 100.0
    if spec.get("value") == "sum":
        return None if series.isna().all() else float(series.sum())
    if year not in series.index:
        return None
    val = series.loc[year]
    return None if pd.isna(val) else float(val)


def render_kpi_radar(
    entries: list[tuple[str, float | None, float | None]],
    *,
    chart_key: str,
    height: int = 360,
) -> None:
    """Radar KPI in % rispetto al Base; servono almeno 3 assi confrontabili."""
    from echarts_charts import build_radar_options, render_echarts

    usable = [
        (label, value, base)
        for label, value, base in entries
        if value is not None and base is not None and base != 0
    ]
    if len(usable) < 3:
        return

    st.markdown("**Confronto con lo scenario Base**")
    st.caption(
        "Ogni asse è normalizzato sul valore dello scenario Base (100%): il "
        "poligono tratteggiato è il Base, quello pieno lo scenario selezionato. "
        "Attenzione al verso: per emissioni, costi e importazioni un valore "
        "più alto è peggiore."
    )
    options = build_radar_options(
        [label for label, _, _ in usable],
        [value for _, value, _ in usable],
        [base for _, _, base in usable],
    )
    _, center, _ = st.columns([1, 2, 1])
    with center:
        render_echarts(options, chart_key=chart_key, height=height)


def render_configured_summary_metrics(
    metrics: list[dict],
    df: pd.DataFrame,
    *,
    year: int,
    gmd_store: dict[str, dict],
    key: str,
    gmd_bounds: dict[str, tuple[float, float]],
    df_base: pd.DataFrame | None = None,
    base_key: str | None = None,
    radar: bool = True,
    radar_chart_key: str = "kpi_radar",
) -> None:
    """Metriche KPI da config con delta vs scenario Base."""
    gmd_row = gmd_store.get(key, {})
    gmd_base_row = gmd_store.get(base_key, {}) if base_key else {}

    entries: list[tuple[str, float | None, float | None]] = []
    last_gmd = max(
        (i for i, spec in enumerate(metrics) if spec.get("gmd")),
        default=None,
    )
    cols = st.columns(len(metrics))
    for i, (col, spec) in enumerate(zip(cols, metrics, strict=True)):
        value_num = _metric_numeric_value(
            spec, df, year=year, gmd_row=gmd_row, gmd_bounds=gmd_bounds,
        )
        value_base = _metric_numeric_value(
            spec, df_base, year=year, gmd_row=gmd_base_row, gmd_bounds=gmd_bounds,
        ) if df_base is not None else None

        if spec.get("gmd"):
            display = fmt_scaled_gmd(value_num)
        else:
            display = fmt_metric_value(
                value_num, spec.get("unit"), decimals=spec.get("decimals", 0),
            )

        if spec.get("radar", True):
            entries.append((spec["label"], value_num, value_base))
        delta, delta_color = metric_delta_vs_base(
            value_num, value_base, spec.get("delta_color", "normal"),
        )
        with col:
            with st.container(border=True):
                st.metric(
                    spec["label"],
                    display,
                    delta=delta,
                    delta_color=delta_color,
                    help=GMD_DISPLAY_CAPTION if i == last_gmd else None,
                )

    if radar:
        render_kpi_radar(entries, chart_key=radar_chart_key)


def render_section_picker(labels: list[str], *, key: str) -> str:
    """Selettore di sottosezione: mostra un blocco di risultati alla volta."""
    st.session_state.setdefault(key, labels[0])
    choice = st.segmented_control(
        "Sezione dei risultati",
        labels,
        key=key,
        label_visibility="collapsed",
    )
    # Il widget permette di deselezionare e restituire None: senza fallback la
    # pagina resterebbe senza grafici.
    return choice or labels[0]


def _go_to_section(key: str, labels: list[str], offset: int) -> None:
    current = labels.index(st.session_state.get(key) or labels[0])
    st.session_state[key] = labels[min(max(current + offset, 0), len(labels) - 1)]


def render_section_nav(labels: list[str], active: str, *, key: str) -> None:
    """Tasti avanti/indietro abbinati a `render_section_picker`."""
    index = labels.index(active)
    col_prev, col_next = st.columns(2)
    col_prev.button(
        "Indietro",
        icon=":material/arrow_back:",
        disabled=index == 0,
        on_click=_go_to_section,
        args=(key, labels, -1),
        width="stretch",
        key=f"{key}_prev",
    )
    col_next.button(
        "Avanti",
        icon=":material/arrow_forward:",
        disabled=index == len(labels) - 1,
        on_click=_go_to_section,
        args=(key, labels, 1),
        width="stretch",
        key=f"{key}_next",
    )


def chart_title(meta: dict) -> str:
    if title := meta.get("title"):
        return title
    if base := meta.get("base"):
        return clean_base(base)
    return meta.get("desc", "Grafico")


def render_gmd_metrics(
    gmd_store: dict[str, dict],
    key: str,
    labels: dict[str, str],
    bounds: dict[str, tuple[float, float]] | None = None,
    *,
    base_key: str | None = None,
) -> None:
    """Mostra metriche GMD normalizzate 0-1 per la combo corrente."""
    if bounds is None:
        bounds = gmd_bounds_for_spec(gmd_store, {m: {} for m in labels})
    row = gmd_store.get(key, {})
    base_row = gmd_store.get(base_key, {}) if base_key and base_key != key else {}
    items = list(labels.items())
    cols = st.columns(len(items))
    for col, (measure, label) in zip(cols, items):
        vmin, vmax = bounds[measure]
        scaled = scale_gmd_equity(row.get(measure), vmin, vmax)
        delta = None
        delta_color = "normal"
        if base_row:
            scaled_base = scale_gmd_equity(base_row.get(measure), vmin, vmax)
            if scaled is not None and scaled_base is not None:
                change = scaled - scaled_base
                if float(f"{change:.3f}") == 0:
                    delta, delta_color = "0.000 vs Base", "off"
                else:
                    delta = f"{change:+.3f} vs Base"
        col.metric(
            label, fmt_scaled_gmd(scaled), delta=delta, delta_color=delta_color,
        )


def render_line(df: pd.DataFrame, meta: dict, *, df_base: pd.DataFrame | None = None):
    from echarts_charts import render_echarts_line
    render_echarts_line(df, meta, df_base=df_base)


def render_line_composite(df: pd.DataFrame, meta: dict, *, df_base: pd.DataFrame | None = None):
    from echarts_charts import render_echarts_line_composite
    render_echarts_line_composite(df, meta, df_base=df_base)


def render_bar(df: pd.DataFrame, meta: dict, final_year: int, *, df_base: pd.DataFrame | None = None):
    from echarts_charts import render_echarts_bar_category
    del final_year  # anno definito in meta
    render_echarts_bar_category(df, meta, df_base=df_base)


def render_explanation(meta: dict, explanations: dict[str, tuple[str, str]]) -> None:
    """Expander esplicativo associato al grafico tramite la chiave `explain`."""
    if note := explanations.get(meta.get("explain")):
        label, body = note
        with st.expander(label):
            st.markdown(body)


def render_section(df, outputs, final_year, *, df_base=None, explanations=None):
    """Disegna lineplot (kind=line, line_composite) e barplot (kind=bar) in griglia."""
    explanations = explanations or {}
    line_outs = [o for o in outputs if o["kind"] in ("line", "line_composite")]
    bar_outs = [o for o in outputs if o["kind"] == "bar"]
    # I due titoli servono solo a separare i blocchi: con un blocco solo sono rumore.
    show_titles = bool(line_outs and bar_outs)
    if line_outs:
        if show_titles:
            st.subheader(
                f"Andamenti temporali ({int(df.index.min())}-{int(df.index.max())})")
        for i in range(0, len(line_outs), 2):
            cols = st.columns(2)
            for j, meta in enumerate(line_outs[i:i + 2]):
                with cols[j]:
                    render_explanation(meta, explanations)
                    if meta["kind"] == "line_composite":
                        render_line_composite(df, meta, df_base=df_base)
                    else:
                        render_line(df, meta, df_base=df_base)
    if bar_outs:
        if show_titles:
            st.subheader(f"Valori al {final_year}")
        for i in range(0, len(bar_outs), 2):
            cols = st.columns(2)
            for j, meta in enumerate(bar_outs[i:i + 2]):
                with cols[j]:
                    render_explanation(meta, explanations)
                    render_bar(df, meta, final_year, df_base=df_base)


def _render_output_chart(
    df: pd.DataFrame, meta: dict, final_year: int, *, df_base=None,
) -> None:
    if meta["kind"] == "line_composite":
        render_line_composite(df, meta, df_base=df_base)
    elif meta["kind"] == "line":
        render_line(df, meta, df_base=df_base)
    elif meta["kind"] == "bar":
        render_bar(df, meta, final_year, df_base=df_base)


def render_section_layout(
    df, outputs, layout: list[list[str]], final_year, *, df_base=None,
) -> None:
    """Griglia custom: ogni riga elenca le base Vensim da affiancare."""
    by_base = {o["base"]: o for o in outputs if "base" in o}
    for row in layout:
        cols = st.columns(len(row))
        for col, base in zip(cols, row, strict=True):
            meta = by_base.get(base)
            with col:
                if meta is None:
                    st.info(f"Grafico non configurato: {base}")
                else:
                    _render_output_chart(
                        df, meta, final_year, df_base=df_base,
                    )
