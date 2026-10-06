"""Entrypoint Streamlit del modello SURE.

Router: Introduzione, Risultati, Analisi esplorativa (policy mix e
simulazione live).
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SURE - Modello cantonale", layout="wide")

pages = {
    "Introduzione": [
        st.Page("pages/home.py", title="Home", default=True),
        st.Page(
            "pages/0_Approccio_System_Dynamics.py",
            title="Approccio System Dynamics",
        ),
    ],
    "Risultati": [
        st.Page("pages/1_PV_e_Batterie.py", title="PV e Batterie"),
        st.Page(
            "pages/2_Riscaldamento_e_Risanamento.py",
            title="Riscaldamento e Risanamento",
        ),
        st.Page("pages/3_Veicoli.py", title="Veicoli"),
        st.Page("pages/4_Elettricità.py", title="Elettricità"),
    ],
    "Analisi esplorativa": [
        st.Page(
            "pages/5_Analisi_Esplorativa.py",
            title="Policy mix e incertezza",
        ),
        st.Page(
            "pages/9_Esplora_SURE_PySD.py",
            title="Simulazione in tempo reale",
        ),
    ],
}

pg = st.navigation(pages, position="sidebar")
pg.run()
