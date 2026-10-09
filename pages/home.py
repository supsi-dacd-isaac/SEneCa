"""Home dell'app Streamlit del modello SURE.

I contenuti sintetizzano il Capitolo 1 della documentazione tecnica
(`SEneCa_documentation.pdf`): contesto del progetto, perimetro analitico del
modello e motivazione dell'applicazione web.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTATION = ROOT / "SEneCa_documentation.pdf"
SURE_URL = "https://sweet-sure.ch/"

CAN_ANSWER = [
    "Come possono evolvere nel lungo periodo la diffusione di **fotovoltaico, "
    "pompe di calore, risanamenti, batterie e veicoli elettrici** sotto "
    "differenti condizioni regolatorie.",
    "Quali effetti producono diverse combinazioni di **incentivi, tasse, "
    "supplementi sulla rete e regolamentazioni**.",
    "Come l'**elettrificazione di riscaldamento e trasporti** modifica la "
    "domanda elettrica cantonale e la sua ripartizione tra settori.",
    "Come **autoconsumo e produzione decentralizzata** incidono sulla domanda "
    "servita dalla rete, sui costi di distribuzione e sul prezzo dell'elettricità.",
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

WEBAPP_ADVANTAGES = [
    (
        ":material/school:",
        "Meno competenze tecniche",
        "Eseguire il modello non richiede più di conoscerne la struttura interna "
        "né di disporre dell'ambiente Vensim.",
    ),
    (
        ":material/replay:",
        "Scenari riproducibili",
        "La definizione di uno scenario si riduce a un insieme di leve "
        "selezionate, semplice da ricostruire e condividere.",
    ),
    (
        ":material/forum:",
        "Risultati discutibili",
        "Indicatori e visualizzazioni standardizzate facilitano il confronto tra "
        "utenti con competenze differenti.",
    ),
]


@st.cache_data(show_spinner=False)
def _documentation_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


st.title("Modello SEneCa per il Ticino")
st.markdown(
    "**La chiave per comprendere la transizione energetica del Canton Ticino**"
)
st.markdown(
    """
**SEneCa** (Sistema Energetico Cantonale) è il simulatore con cui si esplora
la transizione energetica ticinese. Mostra come le politiche e i fattori
esterni di oggi possono plasmarne l'evoluzione fino al 2050: diffusione del
fotovoltaico, risanamento degli edifici, mobilità elettrica, domanda di
elettricità, costi per gli utenti ed equità tra distretti.
"""
)
st.markdown(
    """
Sviluppato da **SUPSI** nell'ambito del progetto **SURE — Sustainable and
Resilient Energy for Switzerland**, il modello è uno strumento di analisi di
scenari. Questa webapp lo rende consultabile: si provano nuove politiche o
cambiamenti dei fattori esterni e si osserva come il sistema cantonale
potrebbe evolvere, compresi gli effetti che si propagano da un settore
all'altro.
"""
)

with st.expander("Contesto del progetto SURE", expanded=False):
    st.markdown(
        """
La transizione energetica svizzera non dipende soltanto dall'introduzione di
tecnologie a basse emissioni: richiede che il sistema resti sicuro,
economicamente sostenibile e socialmente accettabile lungo l'intero percorso.
È la domanda a cui risponde il progetto **SURE — Sustainable and Resilient
Energy for Switzerland**, di cui il caso ticinese è la declinazione cantonale.
"""
    )

    col_ch, col_ti = st.columns(2)
    with col_ch.container(border=True):
        st.markdown("#### :earth_africa: SURE, livello nazionale")
        st.markdown(
            """
Consorzio del programma federale **SWEET** (Call 1-2020), dieci partner di
ricerca guidati dal **Paul Scherrer Institute**. Valuta in modo integrato
sostenibilità e resilienza della transizione lungo più dimensioni: impatti
ambientali, uso delle risorse, salute pubblica, costi e benefici economici,
sicurezza dell'approvvigionamento e benessere sociale.

Non si limita a identificare le configurazioni future possibili, ma indaga
**attraverso quali dinamiche** vi si arriva, quali compromessi emergono tra
obiettivi ambientali, economici e sociali, quanto i percorsi siano vulnerabili
agli shock e quali strategie reggano in una pluralità di futuri plausibili.
"""
        )
    with col_ti.container(border=True):
        st.markdown("#### :round_pushpin: Il caso Ticino, WP13")
        st.markdown(
            """
Nella struttura federale svizzera gli obiettivi climatici sono definiti a
Berna, ma sono i **Cantoni** ad avere le competenze attuative: devono tradurli
in percorsi di decarbonizzazione compatibili con risorse, infrastrutture e
accettazione politica e sociale del territorio.

Il WP13, condotto da **SUPSI**, costruisce lo strumento che collega i due
livelli. Il modello nasce da un percorso **partecipativo** con gli stakeholder
cantonali (amministrazione, aziende elettriche, associazioni, politica) che
ne hanno definito il problema, le variabili rilevanti e gli indicatori. Non è
quindi una semplice regionalizzazione di dati nazionali.
"""
        )

with st.expander(
    "Il modello SEneCa - Sistema Energetico Cantonale", expanded=False,
):
    st.info(
        """
**Il modello simula, non prevede e non ottimizza.** Permette di formulare
esperimenti *what-if*: si modificano politiche, regolamentazioni e ipotesi di
contesto e si osservano le conseguenze dinamiche che ne derivano, inclusi
effetti indiretti e inattesi tra settori. Il suo valore non sta nell'indicare
un unico percorso «corretto», ma nel fornire un ambiente trasparente in cui
confrontare alternative e capire quali relazioni causali generano le differenze
tra scenari.
""",
        icon=":material/lightbulb:",
    )

    st.markdown(
        """Domande alle quali il modello può e non può contribuire:"""
    )

    col_can, col_cannot = st.columns(2)
    with col_can.container(border=True):
        st.markdown(":green-badge[:material/check_circle: Può contribuire a rispondere a]")
        st.markdown("\n".join(f"- {item}" for item in CAN_ANSWER))
    with col_cannot.container(border=True):
        st.markdown(":red-badge[:material/block: Non è destinato a]")
        st.markdown("\n".join(f"- {item}" for item in CANNOT_ANSWER))

with st.expander("Perché una web application", expanded=False):
    st.markdown(
        """
Il modello SEneCa è sviluppato in **Vensim**: usarlo direttamente richiede
di conoscerne la struttura interna e di disporre del relativo ambiente
software. Questa applicazione è lo **strato di accesso e comunicazione** che
apre le capacità di analisi del modello anche a utenti non specializzati:
limita la modifica agli input rilevanti, automatizza l'esecuzione delle
simulazioni e presenta i risultati in forma interpretabile. Non sostituisce il
modello, lo rende utilizzabile.
"""
    )

    for col, (icon, title, body) in zip(st.columns(3), WEBAPP_ADVANTAGES):
        with col.container(border=True):
            st.markdown(f"#### {icon} {title}")
            st.markdown(body)

with st.expander("Vuoi saperne di più?", expanded=False):
    col_link, col_doc = st.columns(2)
    with col_link.container(border=True):
        st.markdown("#### :material/link: Il progetto SWEET SURE")
        st.markdown(
            "Consorzio, partner di ricerca, pubblicazioni e risultati a livello "
            "nazionale sul sito ufficiale del progetto."
        )
        st.link_button("Vai a sweet-sure.ch", SURE_URL)
    with col_doc.container(border=True):
        st.markdown("#### :material/menu_book: Documentazione tecnica")
        st.markdown(
            "Struttura del modello, formulazioni matematiche, dati di input, "
            "calibrazione, architettura della web app e limitazioni (102 pagine)."
        )
        if DOCUMENTATION.exists():
            st.download_button(
                "Scarica la documentazione (PDF)",
                data=_documentation_bytes(str(DOCUMENTATION)),
                file_name=DOCUMENTATION.name,
                mime="application/pdf",
            )
        else:
            st.caption("Documentazione non trovata.")

st.html(
    """
    <style>
    div.st-key-scopri_metodologia button {
        background-color: #FFF1E6 !important;
        color: #C45E12 !important;
        border: 2px solid #E87722 !important;
    }
    div.st-key-scopri_metodologia button:hover,
    div.st-key-scopri_metodologia button:focus {
        background-color: #FDE0CC !important;
        color: #C45E12 !important;
        border: 2px solid #E87722 !important;
    }
    div.st-key-esplora_simulazioni button {
        background-color: #E8EEFF !important;
        color: #0D4CF6 !important;
        border: 2px solid #0D4CF6 !important;
    }
    div.st-key-esplora_simulazioni button:hover,
    div.st-key-esplora_simulazioni button:focus {
        background-color: #D6E0FF !important;
        color: #0D4CF6 !important;
        border: 2px solid #0D4CF6 !important;
    }
    </style>
    """
)
col_metodo, col_sim = st.columns(2)
with col_metodo:
    if st.button(
        "Scopri la metodologia",
        key="scopri_metodologia",
        use_container_width=True,
    ):
        st.switch_page("pages/0_Approccio_System_Dynamics.py")
with col_sim:
    if st.button(
        "Esplora le simulazioni",
        key="esplora_simulazioni",
        use_container_width=True,
    ):
        st.switch_page("pages/1_PV_e_Batterie.py")
