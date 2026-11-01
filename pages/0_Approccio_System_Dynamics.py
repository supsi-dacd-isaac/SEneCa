"""Pagina didattica - Approccio System Dynamics."""
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
from pv_batteries.responsive import wrapping_columns  # noqa: E402

CAN_ANSWER = [
    "Come possono evolvere nel lungo periodo la diffusione di **fotovoltaico, "
    "pompe di calore, risanamenti, batterie, veicoli elettrici, sistemi di "
    "gestione dell'energia (EMS) e comunità energetiche** sotto differenti "
    "condizioni regolatorie.",
    "Quali effetti producono diverse combinazioni di **incentivi, tasse, "
    "supplementi sulla rete e regolamentazioni**.",
    "Come l'**elettrificazione di riscaldamento e trasporti** modifica la "
    "domanda elettrica cantonale e la sua ripartizione tra settori.",
    "Come **autoconsumo, EMS, comunità energetiche e produzione decentralizzata** "
    "incidono sulla domanda servita dalla rete, sui costi di distribuzione e sul "
    "prezzo dell'elettricità.",
    "Come evolvono **produzione cantonale, import/export e autosufficienza** "
    "sotto differenti scenari di domanda e offerta.",
    "Quali **interazioni** emergono tra strumenti di policy e meccanismi di "
    "finanziamento: incentivi PV e supplementi, tassa CO₂ e Programma Edifici.",
    "Quale effetto ha un **policy mix** su consumi, emissioni, costi per gli "
    "utenti, **equità distributiva** e differenze tra distretti.",
]

CANNOT_ANSWER = [
    "Prevedere con precisione l'**anno o il numero esatto** di future "
    "installazioni tecnologiche.",
    "Individuare automaticamente la combinazione **«ottimale»** di tecnologie o "
    "politiche minimizzando una funzione obiettivo.",
    "Rappresentare le **decisioni individuali** di singole famiglie, imprese o "
    "proprietari di edifici.",
    "Dimensionare impianti o svolgere valutazioni tecnico-economiche riferite a "
    "un **singolo edificio**.",
    "Verificare la **fattibilità elettrica locale**: power flow, congestioni, "
    "tensioni, capacità di linee e trasformatori.",
    "Simulare il funzionamento **operativo del mercato elettrico** o l'unit "
    "commitment degli impianti.",
    "Rappresentare in modo endogeno **cambiamenti macroeconomici** o "
    "trasformazioni strutturali dell'industria.",
]

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


st.title(tr("Metodologia"))
st.markdown(
    tr("""
**SEneCa** (Sistema Energetico Cantonale) è il simulatore con cui si esplora
la transizione energetica ticinese. Mostra come le politiche e i fattori
esterni di oggi possono plasmarne l'evoluzione fino al 2050: diffusione del
fotovoltaico, risanamento degli edifici, mobilità elettrica, domanda di
elettricità, costi per gli utenti ed equità tra distretti.
""")
)

st.subheader(tr("Cosa può e non può fare il modello"))
st.info(
    tr("""
**Il modello simula, non prevede e non ottimizza.** Permette di formulare
esperimenti *what-if*: si modificano politiche, regolamentazioni e ipotesi di
contesto e si osservano le conseguenze dinamiche che ne derivano, inclusi
effetti indiretti e inattesi tra settori. Il suo valore non sta nell'indicare
un unico percorso «corretto», ma nel fornire un ambiente trasparente in cui
confrontare alternative e capire quali relazioni causali generano le differenze
tra scenari.
"""),
    icon=":material/lightbulb:",
)
st.markdown(tr("""Domande alle quali il modello può e non può contribuire:"""))
col_can, col_cannot = wrapping_columns(2, key="method_scope")
with col_can.container(border=True):
    st.markdown(tr(":green-badge[:material/check_circle: Può contribuire a rispondere a]"))
    st.markdown("\n".join(f"- {tr(item)}" for item in CAN_ANSWER))
with col_cannot.container(border=True):
    st.markdown(tr(":red-badge[:material/block: Non è destinato a]"))
    st.markdown("\n".join(f"- {tr(item)}" for item in CANNOT_ANSWER))

st.divider()

st.subheader(tr("Approccio System Dynamics"))

render_sd_intro()

st.divider()

st.markdown(tr("### Lo sviluppo del modello in quattro passi"))
st.markdown(
    tr("Dalla definizione del problema ai modelli qualitativi, ai dati storici "
    "e alla calibrazione. Il percorso prepara alla lettura delle sezioni "
    "Simulazioni SEneCa.")
)

st.session_state.setdefault(STEP_KEY, STEP_LABELS[0])
choice = st.segmented_control(
    tr("Passo del percorso"),
    STEP_LABELS,
    format_func={value: tr(value) for value in STEP_LABELS}.get,
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
    tr("Indietro"),
    icon=":material/arrow_back:",
    disabled=index == 0,
    on_click=_go_to_step,
    args=(-1,),
    width="stretch",
)
col_next.button(
    tr("Avanti"),
    icon=":material/arrow_forward:",
    disabled=index == len(STEP_LABELS) - 1,
    on_click=_go_to_step,
    args=(1,),
    width="stretch",
)
