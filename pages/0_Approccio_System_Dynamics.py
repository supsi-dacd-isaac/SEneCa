"""Pagina didattica - Approccio System Dynamics."""
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

import echarts_charts as _echarts_charts  # noqa: E402
import sd_explainer.loaders as _sd_loaders  # noqa: E402
import sd_explainer.paths as _sd_paths  # noqa: E402
import sd_explainer.render as _sd_render  # noqa: E402
# I moduli vanno ricaricati dalle dipendenze verso render, che li importa per nome.
importlib.reload(_echarts_charts)
importlib.reload(_sd_paths)
importlib.reload(_sd_loaders)
importlib.reload(_sd_render)
from sd_explainer.render import (  # noqa: E402
    render_sd_intro,
    render_step_calibration,
    render_step_problem_definition,
    render_step_qualitative_model,
    render_step_quantitative_model,
)

STEPS = {
    "1 · Definizione del problema": render_step_problem_definition,
    "2 · Modello qualitativo": render_step_qualitative_model,
    "3 · Modello quantitativo": render_step_quantitative_model,
    "4 · Calibrazione": render_step_calibration,
}
STEP_LABELS = list(STEPS)
STEP_KEY = "sd_step"


def _go_to_step(offset: int) -> None:
    current = STEP_LABELS.index(st.session_state.get(STEP_KEY) or STEP_LABELS[0])
    target = min(max(current + offset, 0), len(STEP_LABELS) - 1)
    st.session_state[STEP_KEY] = STEP_LABELS[target]


st.title("Metodologia")
st.subheader("Approccio System Dynamics")

render_sd_intro()

st.divider()

st.markdown("### Lo sviluppo del modello in quattro passi")
st.markdown(
    "Dalla definizione del problema con gli stakeholder ai modelli "
    "qualitativi, ai dati storici e alla calibrazione. Il percorso prepara "
    "alla lettura delle sezioni Simulazioni SEneCa."
)

st.session_state.setdefault(STEP_KEY, STEP_LABELS[0])
choice = st.segmented_control(
    "Passo del percorso",
    STEP_LABELS,
    key=STEP_KEY,
    label_visibility="collapsed",
)
# Il widget permette di deselezionare e restituire None: senza fallback la pagina
# resterebbe vuota.
active = choice or STEP_LABELS[0]

STEPS[active]()

st.divider()

index = STEP_LABELS.index(active)
col_prev, col_next = st.columns(2)
col_prev.button(
    "Indietro",
    icon=":material/arrow_back:",
    disabled=index == 0,
    on_click=_go_to_step,
    args=(-1,),
    width="stretch",
)
col_next.button(
    "Avanti",
    icon=":material/arrow_forward:",
    disabled=index == len(STEP_LABELS) - 1,
    on_click=_go_to_step,
    args=(1,),
    width="stretch",
)
