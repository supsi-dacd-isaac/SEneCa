"""Entrypoint Streamlit del modello SURE.

Router: Introduzione, Simulazioni SEneCa, Analisi esplorativa (policy mix e
simulazione live).
"""
from __future__ import annotations

import streamlit as st
from pv_batteries.i18n import tr, language_selector
from pv_batteries.responsive import apply_responsive_styles

st.set_page_config(page_title="SEneCa", layout="wide")

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
# Register navigation before shared widgets, including on the first cold visit.
# Otherwise the initial widget identity can be based on the legacy page context.
language_selector()
apply_responsive_styles()
pg.run()
