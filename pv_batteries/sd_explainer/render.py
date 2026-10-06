"""Rendering tab per la pagina Approccio System Dynamics."""
from __future__ import annotations

import re
from html import escape

import streamlit as st

from echarts_charts import (
    build_grouped_bar_options,
    build_line_options,
    build_pie_options,
    build_stacked_bar_options,
    render_echarts,
)
from sd_explainer.loaders import (
    _year_column,
    calibration_to_grouped,
    load_calibration_csv,
    load_calibration_extra,
    load_map_html,
    load_historical_hydro_production,
    load_production_csv,
    load_pv_buildings_input,
    load_sector_csv,
    load_workshop_priorities,
    production_line_series,
    sector_csv_to_stacked,
    sector_pie_at_year,
)
from sd_explainer.paths import (
    IMAGE_ARCHITECTURE,
    IMAGE_CLD,
    IMAGE_WORKSHOP,
    MAP_HTML,
)
from ui_colors import SUPSI_BLUE, SUPSI_PURPLE, SUPSI_SOFT_GRAY

DISTRICTS = [
    "Bellinzona", "Blenio", "Leventina", "Locarno",
    "Lugano", "Mendrisio", "Riviera", "Vallemaggia",
]
BUILDING_TYPES = ["SFH", "DFH", "MFH"]

_LOOP_BADGE = re.compile(r":loop-([rb])\[([^\]]+)\]")


def _render_loop_markdown(content: str) -> None:
    """Badge R/B con tinte SUPSI distinte, senza giudizio positivo/negativo."""

    def replace(match: re.Match[str]) -> str:
        kind = match.group(1)
        label = escape(match.group(2).replace("**", ""))
        return f'<span class="sure-loop-badge sure-loop-badge-{kind}">{label}</span>'

    st.markdown(_LOOP_BADGE.sub(replace, content), unsafe_allow_html=True)


def _render_loop_badge_style() -> None:
    st.html(
        f"""<style>
        .sure-loop-badge {{
            display: inline-block;
            padding: 0.08em 0.42em;
            border-radius: 0.35rem;
            font-weight: 600;
            line-height: 1.45;
            white-space: nowrap;
        }}
        .sure-loop-badge-r {{ color: {SUPSI_PURPLE}; background: #EFE3FA; }}
        .sure-loop-badge-b {{ color: #006F63; background: #C9F2E9; }}
        </style>"""
    )


def _render_echarts_line(
    years: list[str],
    series: dict[str, list[float | None]],
    *,
    unit: str,
    chart_key: str,
    title: str,
    height: int = 420,
    y_max: float | None = None,
) -> None:
    st.markdown(f"**{title}**")
    options = build_line_options(years, series, unit=unit)
    if y_max is not None:
        options["yAxis"]["max"] = y_max
    render_echarts(options, chart_key=chart_key, height=height)


def _render_echarts_stacked(
    categories: list[str],
    series: dict[str, list[float]],
    *,
    unit: str,
    chart_key: str,
    title: str,
    height: int = 420,
) -> None:
    st.markdown(f"**{title}**")
    options = build_stacked_bar_options(categories, series, unit=unit)
    render_echarts(options, chart_key=chart_key, height=height)


def _render_echarts_pie(
    categories: list[str],
    values: list[float],
    *,
    unit: str,
    chart_key: str,
    title: str,
    height: int = 380,
) -> None:
    st.markdown(f"**{title}**")
    options = build_pie_options(categories, values, unit=unit)
    options["tooltip"] = {"trigger": "item", "formatter": "{b}: {c} GWh ({d}%)"}
    render_echarts(options, chart_key=chart_key, height=height)


def _render_echarts_grouped(
    categories: list[str],
    series: dict[str, list[float | None]],
    *,
    unit: str,
    chart_key: str,
    title: str,
    height: int = 420,
) -> None:
    st.markdown(f"**{title}**")
    order = list(series.keys())
    options = build_grouped_bar_options(
        categories, series, unit=unit, series_order=order,
    )
    options["grid"] = {"bottom": "14%"}
    render_echarts(options, chart_key=chart_key, height=height)


def _show_image(path, caption: str) -> None:
    if path.exists():
        st.image(str(path), caption=caption, width="stretch")
    else:
        st.warning(f"Immagine non trovata: `{path}`")


def render_sd_intro() -> None:
    _render_loop_badge_style()
    st.markdown(
        """
        **System Dynamics (SD)** è una metodologia di simulazione concepita per
        analizzare il comportamento nel tempo di sistemi complessi caratterizzati da
        **accumuli, ritardi, non-linearità e meccanismi di retroazione**. Non considera
        l'evoluzione del sistema come una successione di eventi indipendenti, ma come
        il prodotto della **struttura causale** che collega le sue componenti: il
        comportamento osservato emerge dall'interazione tra gli stati accumulati, i
        flussi che li modificano e le informazioni su cui gli attori decidono.
        """
    )

    col_blocks, col_loops = st.columns(2)
    with col_blocks.container(border=True):
        st.markdown(":brick: La struttura")
        st.markdown(
            """
            - **Stock** — quantità accumulate nel tempo
            - **Flussi** — ciò che incrementa o riduce gli stock
            - **Variabili ausiliarie** — relazioni tecniche, economiche,
              comportamentali e istituzionali
            - **Parametri e variabili esogene** — andamenti specificati fuori dalla
              struttura endogena
            """
        )
        st.latex(r"S(t) = S(t_0) + \int_{t_0}^{t} \left[ I(\tau) - O(\tau) \right] d\tau")
        st.markdown(
            """
            Nel modello cantonale gli **stock** sono per esempio gli edifici
            appartenenti a una certa configurazione tecnologica o il parco veicoli per
            alimentazione; i **flussi** sono installazioni, sostituzioni, costruzioni,
            demolizioni e dismissioni.
            """
        )
    with col_loops.container(border=True):
        st.markdown(":repeat: I feedback loop")
        _render_loop_markdown(
            """
            Un **feedback loop** è una catena causale in cui una variazione iniziale
            produce effetti che tornano a influenzare la variabile di partenza.

            - :loop-r[R · Reinforcing] amplifica la variazione. Ad esempio, il **peer effect**
              del fotovoltaico: più impianti visibili sui tetti aumentano
              familiarità e accettazione, quindi le adozioni successive.
            - :loop-b[B · Balancing] la contrasta e stabilizza. Ad esempio, la **saturazione**
              del potenziale: ogni installazione riduce il numero di edifici
              con tetto idoneo ancora disponibili.

            La loro combinazione genera le tipiche **curve di diffusione a S**: partenza
            lenta, accelerazione, rallentamento vicino alla saturazione.
            """
        )

    st.info(
        """
        **Simulare non è ottimizzare.** Il modello non cerca la configurazione che
        minimizza o massimizza una funzione obiettivo e non assume che gli attori
        conoscano in anticipo l'evoluzione futura del sistema. Famiglie, aziende e
        autorità decidono con **razionalità limitata**, sulla base di prezzi, costi,
        incentivi e diffusione osservati nell'anno corrente: il modello calcola
        un'**utilità percepita** e la traduce in una probabilità di scelta. Le
        politiche si valutano confrontando gli scenari che ne risultano.
        """,
        icon=":material/lightbulb:",
    )


def _render_model_architecture() -> None:
    st.markdown("### Architettura complessiva del modello")
    st.markdown(
        """
        Il modello è organizzato in **quattro macrocomponenti**: la *domanda e
        adozione delle tecnologie* (residenziale, trasporti, industria e terziario)
        determina consumi e autoconsumo; l'*offerta energetica e il bilancio
        elettrico* confrontano quella domanda con la produzione decentralizzata e
        centralizzata, determinando dispaccio, import ed export.

        Le altre due chiudono i cicli di retroazione: le *utility e le reti di
        distribuzione* traducono bilancio e costi di rete nel prezzo finale
        dell'elettricità, mentre le *autorità pubbliche* agiscono con incentivi,
        tasse e regolamentazioni, il cui finanziamento dipende a sua volta dai
        consumi. Prezzo e politiche tornano così a orientare le adozioni successive.
        """
    )

    _, col_fig, _ = st.columns([0.10, 0.8, 0.10])
    with col_fig:
        _show_image(
            IMAGE_ARCHITECTURE,
            "Architettura funzionale del modello: quattro macrocomponenti che formano "
            "un unico sistema dinamico.",
        )

    col_a, col_b, col_c = st.columns(3)
    with col_a.container(border=True):
        st.markdown("**:material/layers: Struttura ibrida**")
        st.markdown(
            "Rappresentazione *bottom-up* del residenziale tramite **archetipi "
            "edilizi**, aggregata *top-down* in domanda, produzione, costi ed "
            "emissioni; prezzi e costi di rete tornano poi a orientare le decisioni."
        )
    with col_b.container(border=True):
        st.markdown("**:timer_clock: Risoluzione temporale**")
        st.markdown(
            "Orizzonte **2011-2050** con passo **annuale**, coerente con i cicli di "
            "sostituzione e investimento. Il solo bilancio elettrico usa **profili "
            "orari** su giorni rappresentativi."
        )
    with col_c.container(border=True):
        st.markdown("**:material/map: Risoluzione spaziale**")
        st.markdown(
            "**Otto distretti** ticinesi per le caratteristiche territoriali, più il "
            "livello **cantonale** per bilancio e rete e quello **federale** per gli "
            "strumenti nazionali."
        )


def _render_policy_priorities() -> None:
    st.markdown("### Quali policy possono essere valutate?")
    st.markdown(
        """
        Le leve rappresentate nel modello non sono state scelte a tavolino. Nei
        workshop gli stakeholder hanno indicato quali temi considerassero
        **prioritari** e quali marginali per una decisione cantonale: il grafico
        riporta quante volte ciascuna voce è stata segnalata a priorità alta o bassa.
        """
    )

    prio = load_workshop_priorities()
    order = st.segmented_control(
        "Ordina per",
        ["Priorità alta", "Priorità bassa"],
        default="Priorità alta",
        key="sd_prio_order",
    )
    if (order or "Priorità alta") == "Priorità alta":
        prio = prio.sort_values("Priorità Alta")
    else:
        prio = prio.sort_values("Priorità Bassa")

    labels = [str(v) for v in prio["Voce"].tolist()]
    options = {
        "toolbox": {"feature": {"saveAsImage": {}, "dataView": {"readOnly": True}}},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "legend": {"top": 0, "data": ["Priorità Alta", "Priorità Bassa"]},
        "grid": {"left": 330, "right": 40, "top": 40, "bottom": 40},
        "xAxis": {"type": "value", "name": "menzioni", "minInterval": 1},
        "yAxis": {"type": "category", "data": labels, "axisLabel": {"width": 320}},
        "series": [
            {
                "name": "Priorità Alta",
                "type": "bar",
                "itemStyle": {"color": SUPSI_BLUE},
                "data": [int(v) for v in prio["Priorità Alta"].tolist()],
            },
            {
                "name": "Priorità Bassa",
                "type": "bar",
                "itemStyle": {"color": SUPSI_SOFT_GRAY},
                "data": [int(v) for v in prio["Priorità Bassa"].tolist()],
            },
        ],
    }
    render_echarts(
        options, chart_key="sd_workshop_priorities", height=760, tooltip_decimals=0,
    )
    st.caption(
        "Esito dell'esercizio di prioritizzazione con il gruppo core degli "
        "stakeholder (settimo workshop, ottobre 2025)."
    )

    st.markdown(
        """
        Questa lista spiega buona parte di come il modello si è sviluppato. Le voci in
        cima — accumuli domestici, teleriscaldamento, prezzi di mercato, obblighi di
        efficienza, incentivi al fotovoltaico, comunità energetiche e ricarica
        pubblica — sono diventate leve manipolabili,
        mentre i temi giudicati marginali sono rimasti fuori o sono entrati come
        semplici assunzioni di scenario. Anche la profondità di rappresentazione
        segue la stessa logica: dove gli stakeholder chiedevano di poter confrontare
        politiche alternative, il modello è endogeno e dettagliato.
        """
    )


def render_step_problem_definition() -> None:
    st.markdown(
        """
        ### Definizione problema

        L'obiettivo finale è costruire un modello che rappresenti nel modo più accurato
        possibile il comportamento del sistema in analisi. Poiché lo studio della
        transizione è un problema complesso che coinvolge un sistema complesso, come
        quello energetico, il primo passo consiste nel definire chiaramente il sistema
        oggetto di studio, individuandone i confini e gli elementi principali.

        Questo è ciò che abbiamo fatto durante il primo incontro, in cui abbiamo descritto
        gli elementi del sistema sulla base delle tre categorie definite dal
        **Multi-Level Perspective (MLP)**:

        - :earth_africa: **Landscape** → livello macro: contesto esterno e fattori di lungo periodo
        - :brick: **Regimes** → livello intermedio: strutture, regole e pratiche consolidate
        - :arrow_heading_up: **Nicchie** → livello micro: innovazioni e sperimentazioni
        """
    )
    _, col_mlp, _ = st.columns([0.10, 0.8, 0.10])
    with col_mlp:
        _show_image(
            IMAGE_WORKSHOP,
            "Risultati dell'analisi svolta durante il primo workshop. "
            "Il numero nei cerchi indica le menzioni del relativo elemento.",
        )

    st.markdown(
        """
        #### A cosa è servito questo esercizio

        La mappatura MLP è servita soprattutto a decidere **che cosa sta dentro il
        confine del sistema cantonale e che cosa no**.

        Alcuni elementi emersi dal workshop restano fuori dal perimetro endogeno e
        sono assunti come **dati di fatto**: il modello non ne calcola l'evoluzione,
        la riceve come ipotesi di scenario. È il caso, ad esempio, delle **tensioni
        geopolitiche**, che entrano solo attraverso il loro effetto sui prezzi dei
        vettori energetici, o del **cambiamento climatico**, il cui andamento è
        esogeno. Cambiare queste ipotesi significa cambiare scenario, non far girare
        una dinamica interna al modello.

        I **regimi** individuati come principali sono invece il cuore di ciò che il
        modello simula:

        - **Edifici** — stock edilizio, riscaldamento, risanamento, PV e batterie
        - **Produzione e distribuzione dell'energia** — impianti, bilancio elettrico,
          reti e prezzo finale
        - **Trasporti** — parco veicoli, motorizzazioni e infrastruttura di ricarica
        - **Elementi culturali** — non modellati esplicitamente, ma incorporati nel
          comportamento osservato: i parametri delle decisioni sono **calibrati su
          dati storici**, che già contengono abitudini, preferenze e resistenze al
          cambiamento della popolazione ticinese
        """
    )

    st.divider()
    _render_model_architecture()

    st.divider()
    _render_policy_priorities()


def render_step_qualitative_model() -> None:
    st.markdown(
        """
        ### Modello qualitativo

        Una volta definito il sistema, il passo successivo consiste nella costruzione di
        **mappe concettuali** con i **Causal Loop Diagram (CLD)**, tipici del metodo
        **System Dynamics**. Il CLD non contiene numeri: serve a rendere esplicito
        *quali* variabili si influenzano a vicenda e *in che direzione*.
        """
    )

    col_arrows, col_loops = st.columns(2)
    with col_arrows.container(border=True):
        st.markdown("**:material/arrow_right_alt: Come si legge una freccia**")
        st.markdown(
            """
            - :blue-badge[**+**] le due variabili si muovono **nella stessa
              direzione**: se la prima cresce, la seconda cresce
            - :blue-badge[**−**] si muovono in **direzione opposta**: se la prima
              cresce, la seconda cala
            """
        )
    with col_loops.container(border=True):
        st.markdown("**:material/loop: Come si legge un loop**")
        _render_loop_markdown(
            """
            - :loop-r[**R** · Reinforcing] il giro di frecce **amplifica** la
              variazione di partenza: la spinge sempre più lontano
            - :loop-b[**B** · Balancing] il giro la **contrasta**: riporta il
              sistema verso un equilibrio
            """
        )

    _, col_fig, _ = st.columns([0.10, 0.8, 0.10])
    with col_fig:
        _show_image(
            IMAGE_CLD,
            "Causal Loop Diagram dei principali feedback del modello SURE-Ticino: "
            "sedici loop collegano adozione tecnologica, domanda dalla rete, prezzo "
            "dell'elettricità, costi di rete e strumenti di policy. Il CLD è una rappresentazione " 
            "qualitativa della struttura causale: non mostra parametri, formule, ritardi né la " 
            "disaggregazione per archetipo. Il comportamento simulato nasce dall'implementazione " 
            "quantitativa congiunta di queste relazioni, non dalla presenza grafica di un singolo loop. "
            "mostra parametri, formule, ritardi né la disaggregazione per archetipo. Il "
            "comportamento simulato nasce dall'implementazione quantitativa congiunta di "
            "queste relazioni, non dalla presenza grafica di un singolo loop.",
        )

    st.markdown("#### Le quattro famiglie di feedback")
    st.markdown(
        "I sedici loop del diagramma si raggruppano in quattro meccanismi ricorrenti. "
        "Riconoscerli aiuta a interpretare i risultati delle sezioni *Risultati*."
    )

    col_1, col_2 = st.columns(2)
    with col_1.container(border=True):
        st.markdown("**:material/groups: Diffusione sociale e limiti fisici**")
        _render_loop_markdown(
            """
            :loop-r[R1] :loop-r[R2] :loop-r[R10] **Peer effect.** Più
            impianti PV, pompe di calore e veicoli elettrici in circolazione, più la
            tecnologia diventa visibile e familiare, più cresce chi la considera.

            :loop-b[B1] :loop-b[B2] **Saturazione.** Ogni installazione
            riduce il bacino di chi può ancora adottare: tetti idonei che si esauriscono,
            edifici già convertiti.

            :loop-b[B4] **Comunità energetiche.** Chi accede all'elettricità della
            comunità senza impianto proprio ha meno motivi per installarlo dopo.

            Insieme producono le tipiche **curve a S**: partenza lenta, accelerazione,
            rallentamento finale.
            """
        )
    with col_2.container(border=True):
        st.markdown("**:material/bolt: Prezzo dell'elettricità**")
        _render_loop_markdown(
            """
            :loop-r[R3] **Utility death spiral.** L'autoconsumo riduce i kWh
            acquistati dalla rete, ma i costi fissi di distribuzione restano: si
            ripartiscono su meno energia, il prezzo unitario sale e rende l'autoconsumo
            ancora più prezioso.

            :loop-r[R4] :loop-r[R11] **Elettrificazione.** Pompe di calore e
            veicoli elettrici fanno l'opposto: più domanda su cui spalmare i costi fissi,
            prezzo unitario più basso, tecnologia più conveniente.

            :loop-r[R9] **Risanamento.** Meno fabbisogno significa meno domanda e
            quindi prezzi unitari più alti, che aumentano il risparmio ottenibile
            isolando l'involucro.
            """
        )

    col_3, col_4 = st.columns(2)
    with col_3.container(border=True):
        st.markdown("**:material/electrical_services: Costi di adeguamento della rete**")
        _render_loop_markdown(
            """
            :loop-r[R5] **PV.** Più impianti richiedono più rinforzi di rete, i
            costi finiscono nel prezzo, e un prezzo alto rende l'autoconsumo più
            redditizio: il loop si rinforza.

            :loop-b[B3] :loop-b[B5] **Pompe di calore e veicoli elettrici.**
            Stessi rinforzi, stesso aumento di prezzo, ma effetto opposto: qui
            l'elettricità è un **costo operativo**, quindi le adozioni rallentano.
            """
        )
    with col_4.container(border=True):
        st.markdown("**:material/account_balance: Politiche e loro finanziamento**")
        _render_loop_markdown(
            """
            :loop-r[R7] :loop-r[R8] **Supplementi di rete.** Più installazioni
            PV incentivate, più fondi servono, più sale il supplemento federale e
            cantonale sull'elettricità: il prezzo cresce e l'autoconsumo diventa ancora
            più attraente.

            :loop-r[R6] **Co-adozione PV e pompe di calore.** Una pompa di calore
            aumenta i consumi autoconsumabili e rende il PV più redditizio; il PV abbassa
            il costo percepito dell'elettricità per la pompa di calore.
            """
        )

    with st.expander(
        "Perché lo stesso aumento di prezzo accelera il PV ma frena pompe di calore "
        "e veicoli elettrici?"
    ):
        _render_loop_markdown(
            """
            È l'asimmetria tra :loop-r[R5] da un lato e :loop-b[B3]
            :loop-b[B5] dall'altro, e dipende da **che ruolo ha il prezzo** per
            ciascuna tecnologia.

            Per il **fotovoltaico** l'elettricità di rete è ciò che si evita di
            comprare: se il prezzo sale, ogni kWh autoconsumato vale di più e
            l'investimento rende di più. Per **pompe di calore e veicoli elettrici**
            l'elettricità è invece il carburante: se il prezzo sale, il costo di
            esercizio aumenta e l'alternativa fossile torna relativamente più
            competitiva.

            Lo stesso segnale di prezzo, quindi, spinge in direzioni opposte a seconda
            che la tecnologia **consumi** o **sostituisca** elettricità di rete. È un
            esempio di come il comportamento del sistema non si legga dalla singola
            freccia, ma dal giro completo.
            """
        )

def render_step_quantitative_model() -> None:
    st.markdown(
        """
        ### Modello quantitativo

        Per tradurre la struttura causale in un modello che produca numeri, la prima
        cosa da fare è **raccogliere i dati reali** del sistema: da dove parte lo
        stato iniziale, come si sono mossi gli stock negli anni passati, quali
        traiettorie il modello deve essere in grado di riprodurre.

        Qui sotto trovi alcuni esempi di quei dati, divisi tra **produzione** e
        **consumi**. Non sono rappresentazioni esaustive né dettagliate: servono a
        dare un'idea del tipo di informazione raccolta e della sua granularità.
        """
    )

    view = st.segmented_control(
        "Area di approfondimento",
        ["Produzione", "Consumi"],
        default="Produzione",
        key="sd_quant_view",
    )

    if (view or "Produzione") == "Produzione":
        st.subheader("Produzione storica")
        st.markdown(
            """
            Produzione annua di energia elettrica in Ticino, 2011–2024. A sinistra le
            fonti idroelettriche (bacini, acqua fluente, pompaggio) e le altre fonti;
            a destra il dettaglio delle fonti non idroelettriche, con crescita del
            solare negli ultimi anni.
            """
        )
        years1, series1 = load_historical_hydro_production()
        prod_df = load_production_csv()
        years2, series2 = production_line_series(
            prod_df, ["Fotovoltaico", "Acqua fluente", "Cogenerazione", "Eolico"],
        )
        series2 = {
            ("Rifiuti" if name == "Cogenerazione" else name): values
            for name, values in series2.items()
        }
        c1, c2 = st.columns(2)
        with c1:
            _render_echarts_line(
                years1, series1, unit="GWh",
                chart_key="sd_prod_hydro",
                title="Produzione totale annua",
            )
        with c2:
            _render_echarts_line(
                years2, series2, unit="GWh",
                chart_key="sd_prod_other",
                title="Produzione totale annua (dettaglio)",
            )

        st.subheader("Adozione pannelli fotovoltaici")
        st.markdown(
            "La diffusione del fotovoltaico è ricostruita **impianto per impianto** e "
            "poi aggregata secondo le dimensioni che il modello usa per distinguere "
            "gli archetipi: a sinistra per **distretto**, a destra per **tipo di edificio**."
        )
        years_dist, series_dist = load_pv_buildings_input("Distretto")
        years_type, series_type = load_pv_buildings_input("Tipo di edificio")
        c_pv1, c_pv2 = st.columns(2)
        with c_pv1:
            _render_echarts_line(
                years_dist, series_dist,
                unit="edifici con PV",
                chart_key="sd_pv_buildings_distretto",
                title="Edifici con fotovoltaico per distretto (cumulati)",
                height=460,
            )
        with c_pv2:
            _render_echarts_line(
                years_type, series_type,
                unit="edifici con PV",
                chart_key="sd_pv_buildings_tipo",
                title="Edifici con fotovoltaico per tipo di edificio (cumulati)",
                height=460,
            )

    else:
        st.subheader("Consumi storici per settore")
        st.markdown(
            """
            Consumi storici per settore finale di utilizzo e consumo di elettricità.
            Seleziona un anno per la ripartizione a torta.
            """
        )

        df_energy = load_sector_csv("Historical energy consumption.csv")
        cats_e, series_e = sector_csv_to_stacked(df_energy)
        years_e = sorted(int(y) for y in df_energy[_year_column(df_energy)].tolist())

        df_elec = load_sector_csv("Historical electricity consumption.csv")
        cats_el, series_el = sector_csv_to_stacked(df_elec)
        years_el = sorted(int(y) for y in df_elec[_year_column(df_elec)].tolist())

        c1, c2 = st.columns([1.5, 1])
        with c1:
            _render_echarts_stacked(
                cats_e, series_e, unit="GWh",
                chart_key="sd_energy_stacked",
                title="Consumo energia annuale per settore",
            )
        with c2:
            year1 = st.selectbox("Anno (consumi totali)", years_e, key="sd_year_energy")
            pie_cats, pie_vals = sector_pie_at_year(df_energy, year1)
            _render_echarts_pie(
                pie_cats, pie_vals, unit="GWh",
                chart_key=f"sd_energy_pie_{year1}",
                title=f"Ripartizione {year1}",
            )

        c1, c2 = st.columns([1.5, 1])
        with c1:
            _render_echarts_stacked(
                cats_el, series_el, unit="GWh",
                chart_key="sd_elec_stacked",
                title="Consumo elettricità annuale per settore",
            )
        with c2:
            year2 = st.selectbox("Anno (elettricità)", years_el, key="sd_year_elec")
            pie_cats, pie_vals = sector_pie_at_year(df_elec, year2)
            _render_echarts_pie(
                pie_cats, pie_vals, unit="GWh",
                chart_key=f"sd_elec_pie_{year2}",
                title=f"Ripartizione {year2}",
            )

        st.subheader("Settore residenziale")
        st.markdown(
            """
            Il settore residenziale è la principale fonte di consumo. Gli edifici sono
            categorizzati in **archetipi** (tipo, PV, tecnologia di riscaldamento,
            efficienza). La mappa mostra un esempio per il comune di Massagno.
            """
        )
        map_html = load_map_html()
        if map_html is None:
            st.warning(f"Mappa HTML non trovata: `{MAP_HTML}`")
        else:
            st.components.v1.html(map_html, height=600, scrolling=True)


CALIBRATION_CHARTS = (
    ("Fotovoltaico", "sd_cal_pv", "Nuove installazioni annue PV"),
    ("Pompe di calore", "sd_cal_hp", "Nuove installazioni annue pompe di calore"),
    ("Accumulatori", "sd_cal_bat", "Nuovi accumulatori residenziali per anno"),
    ("Veicoli elettrici", "sd_cal_bev", "Nuove immatricolazioni annue di veicoli elettrici"),
)


def _calibration_series(tech: str) -> tuple[list[str], dict[str, list]]:
    """Serie osservata e simulata 2011-2024 per una delle tecnologie calibrate."""
    files = {
        "Fotovoltaico": "Calibration_PV.csv",
        "Pompe di calore": "Calibration_HP.csv",
    }
    if tech in files:
        return calibration_to_grouped(load_calibration_csv(files[tech]))
    return load_calibration_extra(tech)


def render_step_calibration() -> None:
    st.markdown(
        """
        ### Calibrazione

        Non tutti i parametri del modello si possono leggere in una fonte. Costi,
        rendimenti, vite utili e superfici sono **osservabili** e vengono assegnati
        direttamente dai dati. I parametri che descrivono il **comportamento** delle
        persone — quanto pesano il prezzo, l'incentivo o l'esempio dei vicini nel
        decidere se installare un impianto — non lo sono: vanno *stimati*.

        Calibrare significa cercare i valori di questi parametri per cui il modello,
        lasciato correre sul periodo **2011-2024**, riproduce le decisioni che in
        quegli anni sono state osservate davvero.
        """
    )

    col_a, col_b, col_c = st.columns(3)
    with col_a.container(border=True):
        st.markdown("**:material/tune: Cosa si stima**")
        st.markdown(
            "I coefficienti delle **funzioni di utilità** dei moduli di scelta: il "
            "peso di ciascun attributo e le costanti proprie di ogni segmento di "
            "decisori. I parametri tecnici ed economici restano invece fissi."
        )
    with col_b.container(border=True):
        st.markdown("**:material/database: Contro quali dati**")
        st.markdown(
            "Le serie annuali osservate di adozione: fotovoltaico, pompe di calore, "
            "accumulatori, sostituzioni di riscaldamento, risanamenti e "
            "immatricolazioni di veicoli, disaggregate per distretto e tipologia."
        )
    with col_c.container(border=True):
        st.markdown("**:material/function: Con quale criterio**")
        st.markdown(
            "Per le scelte discrete si massimizza la **verosimiglianza**, che "
            "confronta quote di mercato e non valori assoluti. Per le grandezze "
            "continue si minimizza la somma dei **quadrati degli scarti**."
        )

    st.warning(
        """
        **Calibrare non vuol dire prevedere.** Un modello che ricostruisce bene il
        passato non è una sfera di cristallo: la calibrazione fissa il *modo* in cui
        gli attori reagiscono a prezzi, costi e incentivi, non l'evoluzione futura di
        quelle grandezze. Le traiettorie al 2050 non vanno quindi lette come la
        previsione di ciò che accadrà, ma come il **confronto fra scenari**: ciò che
        conta è la distanza fra una politica e l'altra, non il valore puntuale di una
        singola curva.
        """,
        icon=":material/compare_arrows:",
    )

    st.divider()
    st.markdown("#### Quanto bene il modello ricostruisce il passato")
    st.markdown(
        "Le barre confrontano, anno per anno, le adozioni **osservate** con quelle "
        "**simulate**. Sopra, il totale cumulato **osservato** sul periodo di "
        "calibrazione."
    )

    data = {tech: _calibration_series(tech) for tech, _, _ in CALIBRATION_CHARTS}

    metric_cols = st.columns(4)
    for col, (tech, _, _) in zip(metric_cols, CALIBRATION_CHARTS):
        _, series = data[tech]
        observed = sum(v for v in series["Dati storici"] if v is not None)
        col.metric(tech, f"{observed:,.0f}".replace(",", "'"))

    rows = [CALIBRATION_CHARTS[:2], CALIBRATION_CHARTS[2:]]
    for row in rows:
        for col, (tech, chart_key, title) in zip(st.columns(2), row):
            years, series = data[tech]
            with col:
                _render_echarts_grouped(
                    years, series,
                    unit="adozioni/anno",
                    chart_key=chart_key,
                    title=title,
                )
