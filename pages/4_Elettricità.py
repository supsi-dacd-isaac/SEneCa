"""Pagina Streamlit - Sezione Elettricità (output orari stacked)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import streamlit as st
from pv_batteries.i18n import tr

ROOT = Path(__file__).resolve().parent.parent
PVBAT = ROOT / "pv_batteries"
for p in (str(ROOT), str(PVBAT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import elettricita_config as cfg  # noqa: E402

# Streamlit non ricarica i moduli helper al rerun: forza reload dopo edit.
import section_store_hourly  # noqa: E402
import section_store  # noqa: E402
import section_ui as _section_ui  # noqa: E402
import section_ui_hourly  # noqa: E402
import echarts_charts as _echarts_charts  # noqa: E402
from pv_batteries.policy_labels import control_label, format_value
importlib.reload(cfg)
importlib.reload(section_store)
importlib.reload(section_store_hourly)
importlib.reload(_section_ui)
importlib.reload(_echarts_charts)
importlib.reload(section_ui_hourly)
from section_store_hourly import load_combo_hourly_df, load_combo_keys  # noqa: E402
from section_store import base_combo_key, combo_key  # noqa: E402
from section_ui_hourly import (  # noqa: E402
    render_electricity_section,
    render_hourly_summary_metrics,
)


@st.cache_data(show_spinner=False)
def _combo_df(section: str, combo: tuple[float, ...]):
    return load_combo_hourly_df(cfg, list(combo))


@st.cache_resource(show_spinner=False)
def _combo_keys(section: str):
    return load_combo_keys(cfg)


st.title(tr("Elettricità"))

keys = _combo_keys(cfg.SECTION)
if not keys and not cfg.CONSOLIDATED_HOURLY.exists():
    st.warning(
        tr("Scenari pre-calcolati non disponibili. "
        "Contatta l’amministratore per ripristinare i dati della release.")
    )
    st.stop()

with st.expander(tr("Offerta, dispacciamento, consumo ed esportazione: cosa significano")):
    st.markdown(tr(cfg.CONCEPTS_EXPLANATION))

BINARY_INPUTS = getattr(cfg, "BINARY_INPUTS", frozenset())


def _render_binary_input(
    label: str, *, key: str, default: float = 0.0, help: str | None = None,
) -> float:
    default_label = "Sì" if default == 1.0 else "No"
    selected = st.segmented_control(
        tr(label), options=list(cfg.BINARY_LABELS), default=default_label,
        help=tr(help), key=key,
        format_func={value: tr(value) for value in cfg.BINARY_LABELS}.get,
    )
    return 1.0 if selected == "Sì" else 0.0


with st.sidebar:
    st.header(tr("Scenario selezionato"))
    values = []
    for name in cfg.INPUT_ORDER:
        meta = cfg.INPUT_META[name]
        opts = cfg.INPUT_GRID[name]
        label = control_label(meta)
        if name in BINARY_INPUTS:
            val = _render_binary_input(
                label, key=f"electricity_input_{name}", default=cfg.BASE_SCENARIO[name], help=tr(meta.get("help") or None),
            )
        else:
            scale = float(meta.get("scale", 1) or 1)
            val = st.select_slider(
                tr(label), options=opts, value=cfg.BASE_SCENARIO[name], key=f"electricity_input_{name}",
                format_func=lambda x, scale=scale: f"{x * scale:g}",
                help=tr(meta.get("help") or None),
            )
        values.append(val)

    compare_base = st.checkbox(tr("Confronta con scenario Base"), value=False, key="electricity_compare_base")
    with st.expander(tr("Scenario Base")):
        for name in cfg.INPUT_ORDER:
            imeta = cfg.INPUT_META[name]
            base_val = cfg.BASE_SCENARIO[name]
            if name in BINARY_INPUTS:
                st.markdown(
                    tr('- {v0}: **{v1}**', v0=imeta['label'], v1='Sì' if base_val == 1.0 else 'No'))
            else:
                st.markdown(
                    tr('- {v0}: **{v1}**', v0=imeta['label'], v1=format_value(imeta, base_val))
                )

key = combo_key(values)
base_key = base_combo_key(cfg)
base_values = [cfg.BASE_SCENARIO[n] for n in cfg.INPUT_ORDER]

if key not in keys:
    st.warning(tr("Combinazione non ancora disponibile nello store."))
    st.stop()

df = _combo_df(cfg.SECTION, tuple(values))
if df.empty:
    st.warning(tr("Nessun dato orario per questa combinazione."))
    st.stop()

df_base = None
if compare_base:
    if key == base_key:
        st.info(tr("Scenario identico al Base."))
    elif base_key not in keys:
        st.warning(tr("Scenario Base non disponibile nello store."))
    else:
        df_base = _combo_df(cfg.SECTION, tuple(base_values))

st.subheader(tr('Indicatori principali ({v0})', v0=cfg.FINAL_YEAR))
with st.expander(tr("Cosa misurano questi indicatori")):
    st.markdown(tr(cfg.KPI_EXPLANATION))
metrics_df_base = df_base
if metrics_df_base is None and key != base_key and base_key in keys:
    metrics_df_base = _combo_df(cfg.SECTION, tuple(base_values))
render_hourly_summary_metrics(
    cfg.SUMMARY_METRICS,
    df,
    year=cfg.FINAL_YEAR,
    df_base=metrics_df_base,
)

st.divider()

st.caption(
    tr('Profili mensili e orari negli anni {v0}; giorno tipo per {v1}.', v0=', '.join((str(y) for y in cfg.DISPLAY_YEARS)), v1=', '.join(tr(m) for m in cfg.DISPLAY_MONTHS))
)

render_electricity_section(
    df, cfg, values, df_base=df_base, section_selector=True,
)
