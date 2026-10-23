"""Entrypoint Streamlit del modello SURE.

Router: Introduzione, Simulazioni SEneCa, Analisi esplorativa (policy mix e
simulazione live).
"""
from __future__ import annotations

import streamlit as st
from pv_batteries.i18n import tr, language, language_selector

st.set_page_config(page_title="SEneCa", layout="wide")

language_selector()

pages = {
    tr("Home"): [
        st.Page("pages/home.py", title=tr("Contesto e scopo"), default=True),
        st.Page(
            "pages/0_Approccio_System_Dynamics.py", url_path="Approccio_System_Dynamics",
            title=tr("Metodologia"),
        ),
    ],
    tr("Simulazioni SEneCa"): [
        st.Page("pages/1_PV_e_Batterie.py", url_path="PV_e_Batterie", title=tr("PV e batterie")),
        st.Page(
            "pages/2_Riscaldamento_e_Risanamento.py", url_path="Riscaldamento_e_Risanamento",
            title=tr("Riscaldamento e risanamento"),
        ),
        st.Page("pages/3_Veicoli.py", url_path="Veicoli", title=tr("Veicoli")),
        st.Page("pages/4_Elettricità.py", url_path="Elettricità", title=tr("Elettricità")),
    ],
    tr("Analisi esplorativa"): [
        st.Page(
            "pages/5_Analisi_Esplorativa.py", url_path="Analisi_Esplorativa",
            title=tr("Policy mix e incertezza"),
        ),
        st.Page(
            "pages/9_Esplora_SURE_PySD.py", url_path="Esplora_SURE_PySD",
            title=tr("Simulazione in tempo reale"),
        ),
    ],
}

pg = st.navigation(pages, position="sidebar")
if language() == "en" and pg.url_path not in ("", "PV_e_Batterie"):
    st.info("English preview: navigation and PV & Batteries are translated. This section is still being translated.")
pg.run()
