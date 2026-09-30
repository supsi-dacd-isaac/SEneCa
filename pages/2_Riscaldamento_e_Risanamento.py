"""Pagina Streamlit - Sezione "Riscaldamento e Risanamento".

Serve all'istante le 1215 combinazioni pre-calcolate (precompute_risanamento.py):
6 slider discreti -> traiettorie/valori 2050 degli output + equity CO2 tax (GMD).
"""
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

import risanamento_config as cfg  # noqa: E402
importlib.reload(cfg)
import gmd as _gmd  # noqa: E402
import section_store as _section_store  # noqa: E402
import echarts_charts as _echarts_charts  # noqa: E402
import section_ui as _section_ui  # noqa: E402
importlib.reload(_gmd)
importlib.reload(_section_store)
importlib.reload(_echarts_charts)
importlib.reload(_section_ui)
from gmd import gmd_bounds_for_spec  # noqa: E402
from section_store import base_combo_key, combo_key, load_gmd_store, load_traj_store  # noqa: E402
from section_ui import (  # noqa: E402
    GMD_DISPLAY_CAPTION,
    render_configured_summary_metrics,
    render_section,
    sim_incomplete,
)


def _format_base_value(name: str, value: float) -> str:
    if name == "MuKEn scenario":
        return cfg.MUKEN_LABELS.get(value, f"{value:g}")
    imeta = cfg.INPUT_META[name]
    unit = f" {imeta['unit']}" if imeta["unit"] != "-" else ""
    return f"`{value:g}`{unit}"


def _render_muken_input(label: str, *, default: float = 0.0) -> float:
    options = [cfg.MUKEN_LABELS[v] for v in cfg.INPUT_GRID["MuKEn scenario"]]
    default_label = cfg.MUKEN_LABELS[default]
    selected = st.radio(
        label,
        options=options,
        index=options.index(default_label),
    )
    return cfg.MUKEN_LABEL_TO_VALUE[selected]


@st.cache_resource(show_spinner="Caricamento scenari pre-calcolati...")
def _traj(section: str):
    return load_traj_store(cfg)


@st.cache_resource(show_spinner=False)
def _gmd(section: str):
    return load_gmd_store(cfg)


st.title("Riscaldamento e Risanamento")

store = _traj(cfg.SECTION)
gmd_store = _gmd(cfg.SECTION)

if not store:
    st.warning(
        "Nessuno scenario pre-calcolato trovato. Esegui "
        "`pv_batteries/precompute_risanamento.py` per popolare lo store."
    )
    st.stop()

n_combos = 1
for v in cfg.INPUT_GRID.values():
    n_combos *= len(v)
st.caption(f"{len(store)}/{n_combos} combinazioni disponibili nello store.")

with st.sidebar:
    st.header("Scenario selezionato")
    values = []
    for name in cfg.INPUT_ORDER:
        meta = cfg.INPUT_META[name]
        opts = cfg.INPUT_GRID[name]
        label = meta["label"] + (f" ({meta['unit']})" if meta["unit"] != "-" else "")
        if name == "MuKEn scenario":
            val = _render_muken_input(label, default=opts[0])
        else:
            val = st.select_slider(
                label, options=opts, value=opts[0],
                format_func=lambda x: f"{x:g}",
            )
        values.append(val)

    compare_base = st.checkbox("Confronta con scenario Base", value=False)
    with st.expander("Scenario Base"):
        for name in cfg.INPUT_ORDER:
            imeta = cfg.INPUT_META[name]
            base_val = cfg.BASE_SCENARIO[name]
            if name == "MuKEn scenario":
                st.markdown(f"- {imeta['label']}: **{_format_base_value(name, base_val)}**")
            else:
                st.markdown(f"- {imeta['label']}: {_format_base_value(name, base_val)}")

key = combo_key(values)
base_key = base_combo_key(cfg)

if key not in store:
    st.warning(
        "Questa combinazione non e' ancora disponibile nello store "
        "(il pre-calcolo potrebbe essere ancora in corso). Riprova piu' tardi."
    )
    st.stop()

df = store[key]

df_base = None
if compare_base:
    if key == base_key:
        st.info("Scenario identico al Base.")
    elif base_key not in store:
        st.warning("Scenario Base non disponibile nello store.")
    else:
        df_base = store[base_key]

if sim_incomplete(df, cfg.FINAL_YEAR):
    last_ok = int(df.dropna(how="all").index.max())
    st.warning(
        f"Per questa combinazione il modello Vensim non converge fino al "
        f"{cfg.FINAL_YEAR}: la simulazione si ferma al {last_ok}. I valori al "
        f"{cfg.FINAL_YEAR} e la misura di equity non sono disponibili."
    )

st.subheader(f"Indicatori principali ({cfg.FINAL_YEAR})")
st.caption(GMD_DISPLAY_CAPTION)
with st.expander("Cosa misurano questi indicatori"):
    st.markdown(cfg.KPI_EXPLANATION)
gmd_bounds = gmd_bounds_for_spec(gmd_store, cfg.GMD_SPEC)
metrics_base_key = base_key if key != base_key else None
metrics_df_base = store.get(base_key) if metrics_base_key else None
render_configured_summary_metrics(
    cfg.SUMMARY_METRICS,
    df,
    year=cfg.FINAL_YEAR,
    gmd_store=gmd_store,
    key=key,
    gmd_bounds=gmd_bounds,
    df_base=metrics_df_base,
    base_key=metrics_base_key,
)

st.divider()

render_section(
    df, cfg.OUTPUTS, cfg.FINAL_YEAR,
    df_base=df_base, explanations=cfg.EXPLANATIONS,
)

with st.expander("Dati grezzi (traiettorie)"):
    st.dataframe(df, width="stretch")
    st.download_button(
        "Scarica CSV", df.to_csv().encode("utf-8"),
        file_name=f"risanamento_{key}.csv", mime="text/csv")
