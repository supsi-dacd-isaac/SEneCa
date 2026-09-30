"""Pagina Streamlit - Sezione Veicoli."""
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

import veicoli_config as cfg  # noqa: E402
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


@st.cache_resource(show_spinner="Caricamento scenari pre-calcolati...")
def _traj(section: str):
    return load_traj_store(cfg)


st.title("Veicoli")

store = _traj(cfg.SECTION)
if not store:
    st.warning(
        "Nessuno scenario pre-calcolato. Esegui "
        "`pv_batteries/precompute_veicoli.py` per popolare lo store."
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
        val = st.select_slider(label, options=opts, value=opts[0],
                               format_func=lambda x: f"{x:g}")
        values.append(val)

    compare_base = st.checkbox("Confronta con scenario Base", value=False)
    with st.expander("Scenario Base"):
        for name in cfg.INPUT_ORDER:
            imeta = cfg.INPUT_META[name]
            base_val = cfg.BASE_SCENARIO[name]
            unit = f" {imeta['unit']}" if imeta["unit"] != "-" else ""
            st.markdown(f"- {imeta['label']}: `{base_val:g}`{unit}")

key = combo_key(values)
base_key = base_combo_key(cfg)

if key not in store:
    st.warning("Combinazione non ancora disponibile nello store.")
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
    st.warning(f"Simulazione non converge fino al {cfg.FINAL_YEAR} (ultimo anno: {last_ok}).")

st.subheader(f"Indicatori principali ({cfg.FINAL_YEAR})")
with st.expander("Cosa misurano questi indicatori"):
    st.markdown(cfg.KPI_EXPLANATION)
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
)

st.divider()

render_section_layout(
    df, cfg.OUTPUTS, cfg.OUTPUT_LAYOUT, cfg.FINAL_YEAR, df_base=df_base,
)

with st.expander("Dati grezzi"):
    st.dataframe(df, width="stretch")
    st.download_button("Scarica CSV", df.to_csv().encode("utf-8"),
                       file_name=f"veicoli_{key}.csv", mime="text/csv")
