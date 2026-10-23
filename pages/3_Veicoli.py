"""Pagina Streamlit - Sezione Veicoli."""
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

import veicoli_config as cfg  # noqa: E402
from pv_batteries.policy_labels import control_label, format_value
importlib.reload(cfg)
import section_store as _section_store  # noqa: E402
import echarts_charts as _echarts_charts  # noqa: E402
import section_ui as _section_ui  # noqa: E402
importlib.reload(_section_store)
importlib.reload(_echarts_charts)
importlib.reload(_section_ui)
from section_store import base_combo_key, combo_key, load_traj_store  # noqa: E402
from section_ui import (  # noqa: E402
    render_configured_summary_metrics,
    render_section_layout,
    sim_incomplete,
)


@st.cache_resource(show_spinner=False)
def _traj(section: str):
    return load_traj_store(cfg)


st.title(tr("Veicoli"))

store = _traj(cfg.SECTION)
if not store:
    st.warning(
        tr("Scenari pre-calcolati non disponibili. "
        "Contatta l’amministratore per ripristinare i dati della release.")
    )
    st.stop()

with st.sidebar:
    st.header(tr("Scenario selezionato"))
    values = []
    for name in cfg.INPUT_ORDER:
        meta = cfg.INPUT_META[name]
        opts = cfg.INPUT_GRID[name]
        label = control_label(meta)
        val = st.select_slider(
            tr(label), options=opts, value=cfg.BASE_SCENARIO[name], key=f"vehicles_input_{name}",
            format_func=lambda x, meta=meta: format_value(meta, x, with_unit=False),
            help=tr(meta.get("help") or None),
        )
        values.append(val)

    compare_base = st.checkbox(tr("Confronta con scenario Base"), value=False, key="vehicles_compare_base")
    with st.expander(tr("Scenario Base")):
        for name in cfg.INPUT_ORDER:
            imeta = cfg.INPUT_META[name]
            base_val = cfg.BASE_SCENARIO[name]
            st.markdown(tr('- {v0}: **{v1}**', v0=imeta['label'], v1=format_value(imeta, base_val)))

key = combo_key(values)
base_key = base_combo_key(cfg)

if key not in store:
    st.warning(tr("Combinazione non ancora disponibile nello store."))
    st.stop()

df = store[key]

df_base = None
if compare_base:
    if key == base_key:
        st.info(tr("Scenario identico al Base."))
    elif base_key not in store:
        st.warning(tr("Scenario Base non disponibile nello store."))
    else:
        df_base = store[base_key]

if sim_incomplete(df, cfg.FINAL_YEAR):
    last_ok = int(df.dropna(how="all").index.max())
    st.warning(tr('Simulazione non converge fino al {v0} (ultimo anno: {v1}).', v0=cfg.FINAL_YEAR, v1=last_ok))

st.subheader(tr('Indicatori principali ({v0})', v0=cfg.FINAL_YEAR))
with st.expander(tr("Cosa misurano questi indicatori")):
    st.markdown(tr(cfg.KPI_EXPLANATION))
metrics_base_key = base_key if key != base_key else None
metrics_df_base = store.get(base_key) if metrics_base_key else None
render_configured_summary_metrics(
    cfg.SUMMARY_METRICS,
    df,
    year=cfg.FINAL_YEAR,
    gmd_store={},
    key=key,
    gmd_bounds={},
    df_base=metrics_df_base,
    base_key=metrics_base_key,
    radar_chart_key="kpi_radar_veicoli",
)

st.divider()

render_section_layout(
    df, cfg.OUTPUTS, cfg.OUTPUT_LAYOUT, cfg.FINAL_YEAR, df_base=df_base,
)

with st.expander(tr("Dati grezzi")):
    st.dataframe(df, width="stretch")
    st.download_button(tr("Scarica CSV"), df.to_csv().encode("utf-8"),
                       file_name=f"veicoli_{key}.csv", mime="text/csv")
