"""Pagina Streamlit - Sezione "PV e Batterie decentralizzate".

Serve all'istante le 324 combinazioni pre-calcolate del modello corretto:
6 slider discreti -> traiettorie/valori 2050 degli output + misure di equity GMD.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from pv_batteries.i18n import tr

ROOT = Path(__file__).resolve().parent.parent
PVBAT = ROOT / "pv_batteries"
for p in (str(ROOT), str(PVBAT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pv_batteries_config as _cfg  # noqa: E402
from pv_batteries.policy_labels import control_label, format_value
importlib.reload(_cfg)
from pv_batteries_config import (  # noqa: E402
    BASE_SCENARIO, BINARY_INPUTS, FINAL_YEAR,
    GMD_SPEC, INPUT_GRID, INPUT_META, INPUT_ORDER,
)
import explore_results_charts as _erc  # noqa: E402
import gmd as _gmd  # noqa: E402
import section_ui as _section_ui  # noqa: E402
import echarts_charts as _echarts_charts  # noqa: E402
import section_store as _section_store  # noqa: E402
importlib.reload(_gmd)
importlib.reload(_section_ui)
importlib.reload(_echarts_charts)
importlib.reload(_section_store)
importlib.reload(_erc)
from explore_results_charts import render_pv_topic_sections as render_topic_sections  # noqa: E402
from gmd import gmd_bounds_for_spec  # noqa: E402
from pv_summary import KPI_EXPLANATION, render_summary_metrics  # noqa: E402
from section_store import (  # noqa: E402
    base_combo_key, combo_key, load_gmd_store, load_traj_store,
)

@st.cache_resource(show_spinner=False)
def _traj(section: str):
    return load_traj_store(_cfg)


@st.cache_resource(show_spinner=False)
def _gmd(section: str):
    return load_gmd_store(_cfg)


def _format_input_value(name: str, value: float) -> str:
    if name in BINARY_INPUTS:
        return tr("Sì") if value == 1.0 else tr("No")
    return f"{value:g}"


def _render_binary_input(label: str, *, key: str, default: float = 0.0,
                         help: str | None = None) -> float:
    selected = st.segmented_control(
        label, options=[0.0, 1.0], default=default, key=key,
        format_func={0.0: tr("No"), 1.0: tr("Sì")}.get,
        help=help,
    )
    return 0.0 if selected is None else selected


st.title(tr("PV e Batterie decentralizzate"))

store = _traj("pv_batteries")
gmd_store = _gmd("pv_batteries")

if not store:
    st.warning(
        tr("Scenari pre-calcolati non disponibili. "
        "Contatta l’amministratore per ripristinare i dati della release.")
    )
    st.stop()

with st.sidebar:
    st.header(tr("Scenario selezionato"))
    values = []
    for name in INPUT_ORDER:
        meta = INPUT_META[name]
        opts = INPUT_GRID[name]
        label = control_label(meta)
        if name in BINARY_INPUTS:
            val = _render_binary_input(
                label, key=f"pv_input_{name}", default=BASE_SCENARIO[name], help=tr(meta.get("help")) or None,
            )
        else:
            scale = float(meta.get("scale", 1) or 1)
            val = st.select_slider(
                label, options=opts, value=BASE_SCENARIO[name], key=f"pv_input_{name}",
                format_func=lambda x, scale=scale: f"{x * scale:g}",
                help=tr(meta.get("help")) or None,
            )
        values.append(val)

    compare_base = st.checkbox(tr("Confronta con scenario Base"), value=False, key="pv_compare_base")
    with st.expander(tr("Scenario Base")):
        for name in INPUT_ORDER:
            imeta = INPUT_META[name]
            base_val = BASE_SCENARIO[name]
            if name in BINARY_INPUTS:
                st.markdown(
                    f"- {tr(imeta['label'])}: **{_format_input_value(name, base_val)}**"
                )
            else:
                st.markdown(
                    f"- {tr(imeta['label'])}: **{format_value(imeta, base_val)}**"
                )

key = combo_key(values)
base_key = base_combo_key(_cfg)

if key not in store:
    st.warning(
        tr("Questa combinazione non e' ancora disponibile nello store "
        "(il pre-calcolo potrebbe essere ancora in corso). Riprova piu' tardi.")
    )
    st.stop()

df = store[key]

df_base: pd.DataFrame | None = None
compare_gmd_key: str | None = None
if compare_base:
    if key == base_key:
        st.info(tr("Scenario identico al Base."))
    elif base_key not in store:
        st.warning(tr("Scenario Base non disponibile nello store."))
    else:
        df_base = store[base_key]
        compare_gmd_key = base_key


# Alcuni scenari estremi (max incentivi PV + FiT + comunità energetica) non
# convergono nel modello Vensim e la simulazione si ferma prima del 2050.
sim_incomplete = bool(df.loc[FINAL_YEAR].isna().all())
if sim_incomplete:
    last_ok = int(df.dropna(how="all").index.max())
    st.warning(
        tr("Per questa combinazione (incentivi estremi) il modello Vensim non "
           "converge fino al {year}: la simulazione si ferma al {last}. "
           "I valori al {year} e le misure di equity non sono disponibili.",
           year=FINAL_YEAR, last=last_ok)
    )

# --- Indicatori principali (2050) -------------------------------------
st.subheader(tr("Indicatori principali ({year})", year=FINAL_YEAR))
with st.expander(tr("Cosa misurano questi indicatori")):
    st.markdown(tr(KPI_EXPLANATION))
gmd_bounds = gmd_bounds_for_spec(gmd_store, GMD_SPEC)
metrics_base_key = base_key if key != base_key else None
metrics_df_base = store.get(base_key) if metrics_base_key else None
render_summary_metrics(
    df,
    gmd_store,
    key,
    year=FINAL_YEAR,
    gmd_bounds=gmd_bounds,
    df_base=metrics_df_base,
    base_key=metrics_base_key,
)

st.divider()

# --- Output per argomento ---------------------------------------------
render_topic_sections(df, df_base=df_base, section_selector=True)

with st.expander(tr("Dati grezzi (traiettorie)")):
    st.dataframe(df, width="stretch")
    st.download_button(
        tr("Scarica CSV"), df.to_csv().encode("utf-8"),
        file_name=f"pv_batterie_{key}.csv", mime="text/csv")
