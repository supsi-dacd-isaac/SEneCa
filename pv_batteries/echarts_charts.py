"""Helper ECharts per grafici interattivi nelle pagine Streamlit."""
from __future__ import annotations

import json
import math
import re

import pandas as pd
import streamlit as st

from section_ui import chart_title, clean_base, elem_label, match_cols
from ui_colors import (
    BASE_GRAY, CHART_TEXT, DATA_COLORS, SUPSI_BLUE, SUPSI_PURPLE,
    data_color, line_color,
)

_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"


def render_chart_header(title: str, unit: str, desc: str | None, suffix: str = "") -> None:
    """Titolo del grafico; la didascalia si stampa solo se aggiunge informazione."""
    st.markdown(f"**{title}** ({unit}){suffix}")
    if desc:
        st.caption(desc)


def _safe_dom_id(key: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", key)


def _chart_key(meta: dict) -> str:
    if meta.get("kind") in ("line_composite", "bar_grouped"):
        return meta["title"]
    return chart_title(meta)


def _to_float_list(values) -> list[float | None]:
    return [None if pd.isna(v) else float(v) for v in values]


_BASE_LINE_STYLE = {"type": "dashed", "opacity": 0.75, "width": 2}
_BASE_ITEM_STYLE = {"opacity": 0.75}

# Voci che stanno su una riga di legenda in un grafico a mezza pagina, con
# etichette lunghe quanto i nomi dei distretti.
_LEGEND_ITEMS_PER_ROW = 4


def build_line_options(
    years: list[int | str],
    series: dict[str, list[float | None]],
    *,
    unit: str,
    series_order: list[str] | None = None,
    compare: dict[str, list[float | None]] | None = None,
    data_zoom: bool = False,
    area: bool = False,
    legend_position: str = "auto",
) -> dict:
    """Opzioni ECharts multi-serie (smooth, legenda, toolbox)."""
    if series_order:
        legend = [label for label in series_order if label in series]
        legend.extend(label for label in series if label not in legend)
    else:
        legend = list(series.keys())

    echarts_series: list[dict] = []
    for index, label in enumerate(legend):
        color = line_color(index, label)
        item: dict = {
            "name": label,
            "type": "line",
            "smooth": True,
            "lineStyle": {"color": color, "width": 2.5},
            "itemStyle": {"color": color},
            "data": series[label],
        }
        if area:
            item["areaStyle"] = {"opacity": 0.35}
        echarts_series.append(item)
        if compare and label in compare:
            echarts_series.append({
                "name": f"{label} (Base)",
                "type": "line",
                "smooth": True,
                "lineStyle": {**_BASE_LINE_STYLE, "color": color},
                "itemStyle": {**_BASE_ITEM_STYLE, "color": color},
                "data": compare[label],
            })

    full_legend = [s["name"] for s in echarts_series]
    # Con molte serie (es. gli 8 distretti) la legenda in basso va a capo su piu'
    # righe e copre l'asse x: di norma la si sposta sopra il grafico, a meno che
    # il grafico non chieda esplicitamente di tenerla sotto la figura.
    crowded = len(full_legend) > 4
    legend_on_top = crowded and legend_position != "bottom"
    if data_zoom:
        grid_bottom = "23%"
        legend_bottom = "9%"
    elif compare:
        grid_bottom = "15%"
        legend_bottom = 0
    else:
        grid_bottom = "12%"
        legend_bottom = 0

    options: dict = {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
                "magicType": {"type": ["line", "bar"]},
            }
        },
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "data": [str(y) for y in years],
            "axisLabel": {"margin": 10},
        },
        "yAxis": {"type": "value", "name": unit},
        "grid": {"bottom": grid_bottom},
        "series": echarts_series,
    }
    if len(full_legend) == 1:
        # Una sola serie: la legenda ripeterebbe il titolo del grafico.
        options["legend"] = {"show": False}
    elif legend_on_top:
        options["legend"] = {
            "top": 0, "type": "scroll", "data": full_legend,
            "padding": [0, 40],
        }
        options["grid"] = {"top": "18%", "bottom": grid_bottom if data_zoom else "8%"}
    elif crowded:
        # Legenda sotto la figura: va riservato lo spazio delle righe su cui
        # andra' a capo, altrimenti finisce sopra l'asse x. Oltre le tre righe
        # il grafico resterebbe schiacciato, quindi si passa alla versione
        # sfogliabile, che occupa una riga sola.
        rows = math.ceil(len(full_legend) / _LEGEND_ITEMS_PER_ROW)
        options["legend"] = {"bottom": 0, "data": full_legend}
        if rows > 3:
            options["legend"]["type"] = "scroll"
            rows = 1
        options["grid"] = {"bottom": f"{12 + 7 * rows}%"}
    else:
        options["legend"] = {"bottom": legend_bottom, "data": full_legend}
    if data_zoom:
        options["dataZoom"] = [
            {"type": "inside", "xAxisIndex": 0},
            {
                "type": "slider",
                "xAxisIndex": 0,
                "bottom": "2%",
                "height": 22,
            },
        ]
    return options


def pivot_to_stacked_series(
    pivot: pd.DataFrame,
) -> tuple[list[str], dict[str, list[float]]]:
    """Pivot (indice categorie, colonne serie) -> assi ECharts stacked bar."""
    categories = [str(i) for i in pivot.index.tolist()]
    series = {
        str(col): [float(v) for v in pivot[col].tolist()]
        for col in pivot.columns
    }
    return categories, series


def build_stacked_bar_options(
    categories: list[str],
    series: dict[str, list[float | None]],
    *,
    unit: str,
    series_order: list[str] | None = None,
) -> dict:
    """Barre impilate per supplier (profili mensili/orari)."""
    if series_order:
        legend = [label for label in series_order if label in series]
        legend.extend(label for label in series if label not in legend)
    else:
        legend = list(series.keys())

    echarts_series = [
        {
            "name": label,
            "type": "bar",
            "stack": "total",
            "emphasis": {"focus": "series"},
            "itemStyle": {"color": data_color(index, label)},
            "data": series[label],
        }
        for index, label in enumerate(legend)
    ]

    legend_opts: dict = {"bottom": "2%", "data": legend}
    if len(legend) > 5:
        legend_opts["type"] = "scroll"

    return {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
            }
        },
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": legend_opts,
        "xAxis": {"type": "category", "data": categories},
        "yAxis": {"type": "value", "name": unit},
        "grid": {"bottom": "22%", "left": "12%", "right": "4%"},
        "series": echarts_series,
    }


def build_pie_options(
    categories: list[str],
    values: list[float | None],
    *,
    unit: str = "",
) -> dict:
    """Grafico a torta per ripartizione per categoria."""
    data = [
        {"name": cat, "value": val}
        for cat, val in zip(categories, values, strict=True)
        if val is not None and not pd.isna(val)
    ]
    y_name = unit or "Valore"
    return {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
            }
        },
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "legend": {"bottom": 0, "type": "scroll" if len(data) > 6 else "plain"},
        "series": [{
            "name": y_name,
            "type": "pie",
            "radius": "65%",
            "center": ["50%", "45%"],
            "data": data,
            "emphasis": {
                "itemStyle": {"shadowBlur": 10, "shadowOffsetX": 0},
            },
        }],
    }


def build_radar_options(
    labels: list[str],
    values: list[float | None],
    base_values: list[float | None],
    *,
    series_label: str = "Scenario selezionato",
    base_label: str = "Scenario Base (100%)",
) -> dict:
    """Radar con assi in % rispetto al Base (Base = poligono regolare a 100)."""
    pcts: list[float | None] = []
    for val, base in zip(values, base_values, strict=True):
        if val is None or base in (None, 0) or pd.isna(val) or pd.isna(base):
            pcts.append(None)
        else:
            pcts.append(round(val / base * 100.0, 1))

    finite = [p for p in pcts if p is not None]
    upper = max(120.0, max(finite) * 1.1) if finite else 120.0
    axis_max = float(int(upper / 10) * 10 + 10)

    return {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
            }
        },
        "tooltip": {"trigger": "item"},
        "legend": {"bottom": 0, "data": [series_label, base_label]},
        "radar": {
            "indicator": [
                {"name": label, "min": 0, "max": axis_max} for label in labels
            ],
            "radius": "62%",
            "center": ["50%", "48%"],
            "axisName": {"fontSize": 11},
            "splitArea": {"areaStyle": {"opacity": 0.05}},
        },
        "series": [{
            "type": "radar",
            "data": [
                {
                    "value": pcts,
                    "name": series_label,
                    "lineStyle": {"color": SUPSI_BLUE, "width": 2.5},
                    "itemStyle": {"color": SUPSI_BLUE},
                    "areaStyle": {"opacity": 0.25},
                },
                {
                    "value": [100.0] * len(labels),
                    "name": base_label,
                    "lineStyle": {**_BASE_LINE_STYLE, "color": BASE_GRAY},
                    "itemStyle": {**_BASE_ITEM_STYLE, "color": BASE_GRAY},
                },
            ],
        }],
    }


def build_boxplot_options(
    categories: list[str],
    boxes: list[list[float]],
    *,
    unit: str = "",
    y_min: float | None = 0.0,
    y_max: float | None = 1.0,
    outliers: list[list[float]] | None = None,
) -> dict:
    """Boxplot per categoria: ogni box è [min, Q1, mediana, Q3, max]."""
    series: list[dict] = [{
        "id": "policy-mix-boxplot",
        "name": "Distribuzione",
        "type": "boxplot",
        "itemStyle": {"color": "#DDE5FF", "borderColor": SUPSI_BLUE},
        "data": [
            {"name": category, "value": box}
            for category, box in zip(categories, boxes, strict=True)
        ],
    }, {
        "id": "policy-mix-outliers",
        "name": "Outlier",
        "type": "scatter",
        "itemStyle": {"color": SUPSI_PURPLE},
        "data": outliers or [],
        "symbolSize": 6,
        "animationDurationUpdate": 0,
    }]
    y_axis: dict = {"type": "value", "name": unit, "scale": False}
    if y_min is not None:
        y_axis["min"] = y_min
    if y_max is not None:
        y_axis["max"] = y_max
    return {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
            }
        },
        "tooltip": {"trigger": "item"},
        "legend": {"show": bool(outliers), "bottom": 0},
        "xAxis": {
            "type": "category",
            "data": categories,
            "axisLabel": {"interval": 0, "rotate": 28},
        },
        "yAxis": y_axis,
        "grid": {"bottom": "26%", "left": "10%", "right": "4%", "top": "8%"},
        "series": series,
    }


def build_multi_radar_options(
    labels: list[str],
    series: dict[str, list[float | None]],
    *,
    axis_max: float = 1.0,
    series_order: list[str] | None = None,
) -> dict:
    """Radar multi-serie con assi su una scala comune (es. KPI 0–1)."""
    if series_order:
        names = [name for name in series_order if name in series]
        names.extend(name for name in series if name not in names)
    else:
        names = list(series.keys())

    return {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
            }
        },
        "tooltip": {"trigger": "item"},
        "legend": {
            "bottom": 0,
            "type": "scroll" if len(names) > 5 else "plain",
            "data": names,
        },
        "radar": {
            "indicator": [
                {"name": label, "min": 0, "max": axis_max} for label in labels
            ],
            "radius": "58%",
            "center": ["50%", "46%"],
            "axisName": {"fontSize": 11},
            "splitArea": {"areaStyle": {"opacity": 0.05}},
        },
        "series": [{
            "type": "radar",
            "data": [
                {
                    "value": [
                        None if v is None or pd.isna(v) else round(float(v), 3)
                        for v in series[name]
                    ],
                    "name": name,
                    "lineStyle": {"color": line_color(index, name), "width": 2},
                    "itemStyle": {"color": line_color(index, name)},
                    "areaStyle": {"opacity": 0.12},
                }
                for index, name in enumerate(names)
            ],
        }],
    }


def render_echarts(
    options: dict, *, chart_key: str, height: int = 400, tooltip_decimals: int = 2,
    previous_options: dict | None = None, animate_initial: bool = True,
) -> None:
    """Renderizza ECharts in iframe (affidabile con Streamlit)."""
    options.setdefault("color", list(DATA_COLORS))
    options.setdefault("backgroundColor", "#FFFFFF")
    options.setdefault("textStyle", {"color": CHART_TEXT})
    dom_id = _safe_dom_id(chart_key)
    options_json = json.dumps(options)
    previous_options_json = json.dumps(previous_options)
    animate_initial_json = json.dumps(animate_initial)
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script src="{_ECHARTS_CDN}"></script>
  <style>
    html, body {{ margin: 0; padding: 0; overflow: hidden; background: #FFFFFF; }}
    #{dom_id} {{ width: 100%; height: {height}px; }}
  </style>
</head>
<body>
  <div id="{dom_id}"></div>
  <script>
    const el = document.getElementById({json.dumps(dom_id)});
    const chart = echarts.init(el);
    const options = {options_json};
    const previousOptions = {previous_options_json};
    const animateInitial = {animate_initial_json};
    const tooltipDecimals = {tooltip_decimals};
    options.tooltip = Object.assign({{ trigger: "axis" }}, options.tooltip || {{}}, {{
      valueFormatter: function(value) {{
        if (value == null || value === "" || (typeof value === "number" && isNaN(value))) {{
          return "-";
        }}
        const n = Number(value);
        return Number.isFinite(n) ? n.toFixed(tooltipDecimals) : String(value);
      }},
    }});
    if (previousOptions) {{
      // This iframe is new after a Streamlit rerun: restore the last visible
      // mix first, then let ECharts animate the update instead of the entrance.
      previousOptions.animation = false;
      chart.setOption(previousOptions);
      requestAnimationFrame(() => requestAnimationFrame(() => {{
        options.animation = true;
        chart.setOption(options);
      }}));
    }} else {{
      if (!animateInitial) options.animation = false;
      chart.setOption(options);
    }}
    window.addEventListener("resize", function() {{ chart.resize(); }});
  </script>
</body>
</html>"""
    st.iframe(html, height=height)


def _series_from_line(df: pd.DataFrame, meta: dict) -> dict[str, list[float | None]]:
    base = meta["base"]
    type_order = meta.get("type_order") or meta.get("district_order")
    scale = meta.get("scale", 1.0)
    cols = match_cols(df, base)
    if not cols:
        return {}
    if type_order:
        rank = {label: i for i, label in enumerate(type_order)}
        cols = sorted(cols, key=lambda c: rank.get(elem_label(c, base), len(type_order)))
    return {
        elem_label(c, base): _to_float_list((df[c] * scale).tolist())
        for c in cols
    }


def _series_from_composite(df: pd.DataFrame, meta: dict) -> dict[str, list[float | None]]:
    series: dict[str, list[float | None]] = {}
    for spec in meta["series"]:
        cols = []
        for base in spec["bases"]:
            cols.extend(match_cols(df, base))
        if cols:
            series[spec["label"]] = _to_float_list(df[cols].sum(axis=1).tolist())
    return series


def _render_echarts_series(
    df: pd.DataFrame,
    meta: dict,
    series: dict[str, list[float | None]],
    *,
    title: str,
    chart_key: str | None = None,
    df_base: pd.DataFrame | None = None,
    compare_fn=None,
) -> None:
    if not series:
        st.info(f"Nessun dato per '{title}'.")
        return
    years = [int(y) for y in df.index.tolist()]
    series_order = meta.get("type_order")
    if meta.get("kind") == "line_composite":
        series_order = [spec["label"] for spec in meta["series"]]
    compare_raw = compare_fn(df_base, meta) if df_base is not None and compare_fn else None
    compare = (
        {k: v for k, v in compare_raw.items() if k in series}
        if compare_raw else None
    )
    if compare == {}:
        compare = None
    if start_year := meta.get("start_year"):
        cut = next((i for i, y in enumerate(years) if y >= start_year), len(years))
        years = years[cut:]
        series = {k: v[cut:] for k, v in series.items()}
        if compare:
            compare = {k: v[cut:] for k, v in compare.items()}
    options = build_line_options(
        years,
        series,
        unit=meta["unit"],
        series_order=series_order,
        compare=compare,
        legend_position=meta.get("legend", "auto"),
    )
    render_chart_header(title, meta["unit"], meta.get("desc"))
    render_echarts(
        options,
        chart_key=chart_key or _chart_key(meta),
        height=meta.get("height", 400),
        tooltip_decimals=meta.get("tooltip_decimals", 2),
    )


def render_echarts_line(
    df: pd.DataFrame,
    meta: dict,
    *,
    chart_key: str | None = None,
    df_base: pd.DataFrame | None = None,
) -> None:
    """Line plot ECharts da variabile Vensim (colonne wide)."""
    title = chart_title(meta)
    _render_echarts_series(
        df,
        meta,
        _series_from_line(df, meta),
        title=title,
        chart_key=chart_key,
        df_base=df_base,
        compare_fn=_series_from_line,
    )


def render_echarts_line_composite(
    df: pd.DataFrame,
    meta: dict,
    *,
    chart_key: str | None = None,
    df_base: pd.DataFrame | None = None,
) -> None:
    """Line plot ECharts da piu' serie aggregate (line_composite)."""
    title = meta.get("title", meta.get("desc", "Composite"))
    _render_echarts_series(
        df,
        meta,
        _series_from_composite(df, meta),
        title=title,
        chart_key=chart_key,
        df_base=df_base,
        compare_fn=_series_from_composite,
    )


_SHARE_SC_LABEL = "Autoconsumo / domanda (%)"
_SHARE_PROD_LABEL = "Produzione / domanda (%)"
_DEMAND_LABEL = "Domanda"
_SC_LABEL = "Autoconsumo (SC)"
_PROD_LABEL = "Produzione PV"


def _demand_share_series(
    series: dict[str, list[float | None]],
) -> dict[str, list[float | None]]:
    """Quote percentuali SC/domanda e Produzione/domanda per distretto."""
    demand = series.get(_DEMAND_LABEL)
    if not demand:
        return {}
    shares: dict[str, list[float | None]] = {}
    pairs = (
        (_SHARE_SC_LABEL, _SC_LABEL),
        (_SHARE_PROD_LABEL, _PROD_LABEL),
    )
    for share_label, num_label in pairs:
        numer = series.get(num_label)
        if not numer:
            continue
        shares[share_label] = [
            None if d in (None, 0) or n is None else 100.0 * n / d
            for n, d in zip(numer, demand, strict=True)
        ]
    return shares


def build_district_combo_options(
    districts: list[str],
    bar_series: dict[str, list[float | None]],
    share_series: dict[str, list[float | None]],
    *,
    unit: str,
    bar_order: list[str],
    compare_bar: dict[str, list[float | None]] | None = None,
    compare_share: dict[str, list[float | None]] | None = None,
) -> dict:
    """Combo barre GWh + linee % su asse Y destro."""
    bar_legend = [label for label in bar_order if label in bar_series]
    share_legend = [_SHARE_SC_LABEL, _SHARE_PROD_LABEL]
    share_legend = [label for label in share_legend if label in share_series]

    share_values = [
        v for vals in share_series.values() for v in vals if v is not None
    ]
    if compare_share:
        share_values.extend(
            v for vals in compare_share.values() for v in vals if v is not None
        )
    right_yaxis: dict = {
        "type": "value",
        "name": "%",
        "min": 0,
        "axisLabel": {"formatter": "{value}%"},
    }
    if share_values and max(share_values) <= 100:
        right_yaxis["max"] = 100

    echarts_series: list[dict] = []
    for index, label in enumerate(bar_legend):
        echarts_series.append({
            "name": label,
            "type": "bar",
            "yAxisIndex": 0,
            "itemStyle": {"color": data_color(index, label)},
            "data": bar_series[label],
        })
    for index, label in enumerate(bar_legend):
        if compare_bar and label in compare_bar:
            color = line_color(index, label)
            echarts_series.append({
                "name": f"{label} (Base)",
                "type": "line",
                "yAxisIndex": 0,
                "smooth": True,
                "lineStyle": {**_BASE_LINE_STYLE, "color": color},
                "itemStyle": {**_BASE_ITEM_STYLE, "color": color},
                "data": compare_bar[label],
            })
    for index, label in enumerate(share_legend):
        color = line_color(index + len(bar_legend), label)
        echarts_series.append({
            "name": label,
            "type": "line",
            "yAxisIndex": 1,
            "smooth": True,
            "lineStyle": {"color": color, "width": 2.5},
            "itemStyle": {"color": color},
            "data": share_series[label],
        })
    for index, label in enumerate(share_legend):
        if compare_share and label in compare_share:
            color = line_color(index + len(bar_legend), label)
            echarts_series.append({
                "name": f"{label} (Base)",
                "type": "line",
                "yAxisIndex": 1,
                "smooth": True,
                "lineStyle": {**_BASE_LINE_STYLE, "color": color},
                "itemStyle": {**_BASE_ITEM_STYLE, "color": color},
                "data": compare_share[label],
            })

    legend = [s["name"] for s in echarts_series]
    grid_bottom = "18%" if (compare_bar or compare_share) else "15%"

    return {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
            }
        },
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0, "data": legend},
        "xAxis": {"type": "category", "data": districts},
        "yAxis": [
            {"type": "value", "name": unit},
            right_yaxis,
        ],
        "grid": {"bottom": grid_bottom},
        "series": echarts_series,
    }


def build_category_bar_options(
    categories: list[str],
    values: list[float | None],
    *,
    unit: str,
    series_label: str,
    y_min: float | None = 0,
    y_max: float | None = None,
    compare_values: list[float | None] | None = None,
) -> dict:
    """Barre verticali a singola serie per categorie (distretti, tipi, ...)."""
    yaxis: dict = {"type": "value", "name": unit}
    if y_min is not None:
        yaxis["min"] = y_min
    if y_max is not None:
        yaxis["max"] = y_max
    if unit == "%":
        yaxis["axisLabel"] = {"formatter": "{value}%"}

    echarts_series: list[dict] = [
        {"name": series_label, "type": "bar", "itemStyle": {"color": SUPSI_BLUE},
         "data": values},
    ]
    if compare_values is not None:
        echarts_series.append({
            "name": "Base", "type": "bar", "itemStyle": {"color": BASE_GRAY},
            "data": compare_values,
        })

    return {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
            }
        },
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0, "data": [s["name"] for s in echarts_series]} if compare_values else {},
        "xAxis": {"type": "category", "data": categories},
        "yAxis": yaxis,
        "grid": {"bottom": "12%" if compare_values else "8%"},
        "series": echarts_series,
    }


def _sort_cols_by_order(
    cols: list[str], base: str, order: list[str] | None
) -> list[str]:
    if not order:
        return cols
    rank = {label: i for i, label in enumerate(order)}
    return sorted(cols, key=lambda c: rank.get(elem_label(c, base), len(order)))


def _category_values_from_bar(
    df: pd.DataFrame, meta: dict
) -> tuple[list[str], list[float | None]]:
    base = meta["base"]
    year = meta.get("year", 2050)
    scale = meta.get("scale", 1.0)
    cols = match_cols(df, base)
    if not cols or year not in df.index:
        return [], []
    order = meta.get("district_order") or meta.get("type_order")
    cols = _sort_cols_by_order(cols, base, order)
    categories = [elem_label(c, base) for c in cols]
    values = [
        None if pd.isna(df.loc[year, c]) else float(df.loc[year, c] * scale)
        for c in cols
    ]
    return categories, values


def render_echarts_bar_category(
    df: pd.DataFrame,
    meta: dict,
    *,
    chart_key: str | None = None,
    df_base: pd.DataFrame | None = None,
) -> None:
    """Barre ECharts per variabile wide a categorie (2050)."""
    title = chart_title(meta)
    year = meta.get("year", 2050)
    categories, values = _category_values_from_bar(df, meta)
    if not categories:
        st.info(f"Nessun dato {year} per '{title}'.")
        return
    compare_values = None
    if df_base is not None:
        _, compare_values = _category_values_from_bar(df_base, meta)
    options = build_category_bar_options(
        categories,
        values,
        unit=meta["unit"],
        series_label=title,
        y_max=meta.get("y_max"),
        compare_values=compare_values,
    )
    render_chart_header(title, meta["unit"], meta.get("desc"), f" - {year}")
    render_echarts(
        options,
        chart_key=chart_key or _chart_key(meta),
        height=meta.get("height", 400),
        tooltip_decimals=meta.get("tooltip_decimals", 2),
    )


def build_grouped_bar_options(
    districts: list[str],
    series: dict[str, list[float | None]],
    *,
    unit: str,
    series_order: list[str],
) -> dict:
    """Barre raggruppate per distretto (ECharts)."""
    legend = [label for label in series_order if label in series]
    legend.extend(label for label in series if label not in legend)
    echarts_series = [
        {"name": label, "type": "bar", "itemStyle": {"color": data_color(index, label)},
         "data": series[label]}
        for index, label in enumerate(legend)
    ]
    return {
        "toolbox": {
            "feature": {
                "saveAsImage": {},
                "dataView": {"readOnly": True},
                "restore": {},
            }
        },
        "tooltip": {"trigger": "axis"},
        "legend": {"bottom": 0, "data": legend},
        "xAxis": {"type": "category", "data": districts},
        "yAxis": {"type": "value", "name": unit},
        "grid": {"bottom": "12%"},
        "series": echarts_series,
    }


def _values_by_district(
    df: pd.DataFrame,
    base: str,
    year: int,
    district_order: list[str],
    scale: float = 1.0,
) -> dict[str, float | None]:
    cols = match_cols(df, base)
    if not cols or year not in df.index:
        return {}
    by_label = {
        elem_label(c, base): df.loc[year, c] * scale for c in cols
    }
    rank = {d: i for i, d in enumerate(district_order)}
    ordered = sorted(by_label.keys(), key=lambda d: rank.get(d, len(district_order)))
    return {
        d: (None if pd.isna(by_label[d]) else float(by_label[d]))
        for d in ordered
    }


def _series_from_bar_grouped(
    df: pd.DataFrame, meta: dict
) -> tuple[list[str], dict[str, list[float | None]]]:
    year = meta.get("year", 2050)
    district_order = meta.get("district_order", [])
    districts: list[str] = []
    series: dict[str, list[float | None]] = {}
    for spec in meta["series"]:
        values = _values_by_district(
            df,
            spec["base"],
            year,
            district_order,
            spec.get("scale", 1.0),
        )
        if not values:
            continue
        if not districts:
            districts = list(values.keys())
        series[spec["label"]] = list(values.values())
    return districts, series


def render_echarts_bar_grouped(
    df: pd.DataFrame,
    meta: dict,
    *,
    chart_key: str | None = None,
    df_base: pd.DataFrame | None = None,
) -> None:
    """Combo ECharts: barre GWh + linee % domanda per distretto."""
    title = chart_title(meta)
    districts, series = _series_from_bar_grouped(df, meta)
    if not districts or not series:
        st.info(f"Nessun dato per '{title}'.")
        return
    bar_order = [spec["label"] for spec in meta["series"]]
    share_series = _demand_share_series(series)
    compare_bar = None
    compare_share = None
    if df_base is not None:
        _, base_series = _series_from_bar_grouped(df_base, meta)
        if base_series:
            compare_bar = base_series
            compare_share = _demand_share_series(base_series)
    options = build_district_combo_options(
        districts,
        series,
        share_series,
        unit=meta["unit"],
        bar_order=bar_order,
        compare_bar=compare_bar,
        compare_share=compare_share,
    )
    render_chart_header(
        title, meta["unit"], meta.get("desc"), f" - {meta.get('year', 2050)}")
    render_echarts(
        options,
        chart_key=chart_key or _chart_key(meta),
        height=meta.get("height", 450),
        tooltip_decimals=meta.get("tooltip_decimals", 2),
    )
