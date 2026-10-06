"""Pagina Streamlit - Sezione Elettricità (output orari stacked)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import streamlit as st

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


@st.cache_data(show_spinner="Caricamento dati combinazione...")
def _combo_df(section: str, combo: tuple[float, ...]):
    return load_combo_hourly_df(cfg, list(combo))


@st.cache_resource(show_spinner=False)
def _combo_keys(section: str):
    return load_combo_keys(cfg)


st.title("Elettricità")

keys = _combo_keys(cfg.SECTION)
if not keys and not cfg.CONSOLIDATED_HOURLY.exists():
    st.warning(
        "Nessuno scenario pre-calcolato. Esegui "
        "`pv_batteries/precompute_elettricita.py` per popolare lo store."
    )
    st.stop()

with st.expander("Offerta, dispacciamento, consumo ed esportazione: cosa significano"):
    st.markdown(cfg.CONCEPTS_EXPLANATION)

BINARY_INPUTS = getattr(cfg, "BINARY_INPUTS", frozenset())


def _render_binary_input(label: str, *, default: float = 0.0) -> float:
    default_label = "Sì" if default == 1.0 else "No"
    selected = st.segmented_control(
        label, options=list(cfg.BINARY_LABELS), default=default_label,
    )
    return 1.0 if selected == "Sì" else 0.0


with st.sidebar:
    st.header("Scenario selezionato")
    values = []
    for name in cfg.INPUT_ORDER:
        meta = cfg.INPUT_META[name]
        opts = cfg.INPUT_GRID[name]
        label = meta["label"] + (f" ({meta['unit']})" if meta["unit"] != "-" else "")
        if name in BINARY_INPUTS:
            val = _render_binary_input(label, default=opts[0])
        else:
            val = st.select_slider(label, options=opts, value=opts[0],
                                   format_func=lambda x: f"{x:g}")
        values.append(val)

    compare_base = st.checkbox("Confronta con scenario Base", value=False)
    with st.expander("Scenario Base"):
        for name in cfg.INPUT_ORDER:
            imeta = cfg.INPUT_META[name]
            base_val = cfg.BASE_SCENARIO[name]
            if name in BINARY_INPUTS:
                st.markdown(
                    f"- {imeta['label']}: **{'Sì' if base_val == 1.0 else 'No'}**")
            else:
                unit = f" {imeta['unit']}" if imeta["unit"] != "-" else ""
                st.markdown(f"- {imeta['label']}: `{base_val:g}`{unit}")

key = combo_key(values)
base_key = base_combo_key(cfg)
base_values = [cfg.BASE_SCENARIO[n] for n in cfg.INPUT_ORDER]

if key not in keys:
    st.warning("Combinazione non ancora disponibile nello store.")
    st.stop()

df = _combo_df(cfg.SECTION, tuple(values))
if df.empty:
    st.warning("Nessun dato orario per questa combinazione.")
    st.stop()

df_base = None
if compare_base:
    if key == base_key:
        st.info("Scenario identico al Base.")
    elif base_key not in keys:
        st.warning("Scenario Base non disponibile nello store.")
    else:
        df_base = _combo_df(cfg.SECTION, tuple(base_values))

st.subheader(f"Indicatori principali ({cfg.FINAL_YEAR})")
with st.expander("Cosa misurano questi indicatori"):
    st.markdown(cfg.KPI_EXPLANATION)
metrics_df_base = df_base
if metrics_df_base is None and key != base_key and base_key in keys:
    metrics_df_base = _combo_df(cfg.SECTION, tuple(base_values))
render_hourly_summary_metrics(
    cfg.SUMMARY_METRICS,
    df,
    year=cfg.FINAL_YEAR,
    key=key,
    df_base=metrics_df_base,
)

st.divider()

st.caption(
    f"Profili mensili e orari negli anni {', '.join(str(y) for y in cfg.DISPLAY_YEARS)}; "
    f"giorno tipo per {', '.join(cfg.DISPLAY_MONTHS)}."
)

render_electricity_section(
    df, cfg, values, df_base=df_base, section_selector=True,
)
