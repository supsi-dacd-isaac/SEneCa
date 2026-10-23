"""Configurazione della sezione "PV e Batterie".

Sorgente: "Input and Output Streamlit.xlsx" (fogli "Input" e "Output PV e
Batterie"). Gli input sono le righe con "X" nella colonna "PV e Batterie".

Nota FiT: nel modello Vensim e' in CHF/kWh; l'Excel lo esprime in ct/kWh
(0-10). I valori discreti usati qui sono 0/0.05/0.10 CHF/kWh (= 0/5/10 ct/kWh).
"""
from __future__ import annotations

from pathlib import Path

from pv_batteries.policy_labels import input_metadata

ROOT = Path(__file__).resolve().parent.parent
VPMX = ROOT / "Vensim" / "SURE.vpmx"
STORE_DIR = ROOT / "precomputed" / "pv_batteries"
CONSOLIDATED_TRAJ = ROOT / "precomputed" / "pv_batteries_scenarios.parquet"
CONSOLIDATED_GMD = ROOT / "precomputed" / "pv_batteries_gmd.parquet"

YEARS = range(2011, 2051)
FINAL_YEAR = 2050

BUILDING_TYPE_ORDER = ["SFH", "DFH", "MFH"]

DISTRICT_ORDER = [
    "Bellinzona", "Blenio", "Leventina", "Locarno",
    "Lugano", "Mendrisio", "Riviera", "Vallemaggia",
]

# =============================================================
# INPUT (6 variabili -> 3*3*3*3*2*2 = 324 combinazioni)
# nome variabile Vensim -> lista di valori discreti ammessi
# =============================================================
INPUT_GRID: dict[str, list[float]] = {
    "PV rebate cantonal": [0.0, 0.1, 0.2],
    "FiT": [0.0, 0.05, 0.10],
    "Battery Rebate": [0.0, 0.25, 0.5],
    "PV rebate federal": [0.0, 0.2, 0.4],
    "PV reg scenario": [0.0, 1.0],
    "Energy Community scenario": [0.0, 1.0],
}

INPUT_ORDER = list(INPUT_GRID.keys())

# Input binari in sidebar (bottoni Sì/No invece di slider)
BINARY_INPUTS = frozenset({"PV reg scenario", "Energy Community scenario"})
BINARY_LABELS = ("No", "Sì")

# Scenario Base (colonna "Base" in Input and Output Streamlit.xlsx)
BASE_SCENARIO: dict[str, float] = {
    "PV rebate cantonal": 0.1,
    "FiT": 0.0,
    "Battery Rebate": 0.0,
    "PV rebate federal": 0.2,
    "PV reg scenario": 1.0,
    "Energy Community scenario": 0.0,
}

# Etichette/unita' per la UI (allineate all'Excel)
INPUT_META = input_metadata(INPUT_ORDER)

# =============================================================
# OUTPUT (foglio "Output PV e Batterie")
# base = nome variabile Vensim senza il subscript [Famiglia] (espanso a runtime)
# kind = "line" (traiettoria 2011-2050) | "bar" (valore anno singolo)
# =============================================================
OUTPUTS = [
    {"base": "PV residential power by Type", "kind": "line", "unit": "MW",
     "title": "Potenza PV residenziale per tipo",
     "desc": 'Potenza installata negli edifici residenziali ticinesi, per tipologia.',
     "time_basis": "stock", "stock_label": "Potenza totale installata",
     "annual_label": "Nuova potenza installata nell’anno",
     "type_order": BUILDING_TYPE_ORDER},
    {"kind": "line_composite", "unit": "kW",
     "title": "Potenza PV non residenziale",
     "desc": 'Totale cantonale; le classi indicano la potenza del singolo impianto.',
     "time_basis": "stock", "stock_label": "Potenza totale installata",
     "annual_label": "Nuova potenza installata nell’anno",
     "history": "pv_capacity",
     "history_position": "bottom",
     "history_note": "Dati di input da PVinput.csv, disponibili per 30–100 e >100 kW. "
                     "La classe <30 kW non ha una serie storica separata.",
     "series": [
         {"label": "< 30 kW", "bases": ['"Capacity PV < 30 kW total"']},
         {"label": "30–100 kW", "bases": ['"Capacity PV 30 - 100 kW total"']},
         {"label": "> 100 kW", "bases": ['"Capacity PV > 100 kW total"']},
     ]},
    {"base": "Share of buildings with PV by Type", "kind": "bar", "year": 2050,
     "title": "Share edifici con PV per tipo",
     "desc": 'Percentuale degli edifici di ciascuna tipologia con PV.',
     "unit": "%",
     "echarts": True, "scale": 100, "type_order": BUILDING_TYPE_ORDER, "y_max": 100},
    {"base": "Share of buildings with PV by District", "kind": "bar", "year": 2050,
     "title": "Share edifici con PV per distretto",
     "desc": 'Percentuale degli edifici di ciascun distretto con PV.',
     "unit": "%",
     "echarts": True, "scale": 100, "district_order": DISTRICT_ORDER, "y_max": 100},
    {"base": "Battery residential Type", "kind": "line", "unit": "MWh",
     "title": "Capacita' batterie residenziale per tipo",
     "desc": 'Energia accumulabile nelle batterie residenziali, per tipologia di edificio.',
     "time_basis": "stock",
     "type_order": BUILDING_TYPE_ORDER},
    {"kind": "line_composite", "unit": "MWh",
     "title": "Capacita' batterie non residenziale",
     "desc": 'Energia accumulabile; le classi in kW si riferiscono agli impianti PV.',
     "time_basis": "stock",
     "series": [
         {"label": "< 100 kW", "bases": ['"Total Battery capacity < 100 kW"']},
         {"label": "> 100 kW", "bases": ['"Total Battery capacity > 100 kW"']},
     ]},
    {"base": "Total Battery capacity District", "kind": "bar", "year": 2050,
     "title": "Capacita' batterie per distretto",
     "desc": 'Energia accumulabile nelle batterie di ciascun distretto.',
     "unit": "MWh",
     "echarts": True, "district_order": DISTRICT_ORDER, "height": 430},
    {"base": "Batteries by Type", "kind": "bar", "year": 2050, "unit": "%",
     "title": "Share edifici con batteria per tipo",
     "desc": 'Percentuale degli edifici di ciascuna tipologia con batteria.',
     "echarts": True, "scale": 100, "type_order": BUILDING_TYPE_ORDER, "y_max": 100,
     "height": 430},
    {"base": "Electricity price", "kind": "line", "unit": "CHF/kWh",
     "title": "Prezzo finale al consumatore",
     "desc": "Somma di tutte le componenti, per distretto",
     "district_order": DISTRICT_ORDER, "tooltip_decimals": 3,
     "legend": "bottom", "height": 430},
    {"base": "Energy price", "kind": "line", "unit": "CHF/kWh",
     "title": "Componente energia",
     "desc": "Costo di acquisto dell'energia, per distretto",
     "district_order": DISTRICT_ORDER, "tooltip_decimals": 3,
     "height": 430},
    {"base": "TSO charge", "kind": "line", "unit": "CHF/kWh",
     "title": "Componente rete di trasporto (TSO)",
     "desc": "Costo della rete ad alta tensione, uguale per tutti i distretti",
     "tooltip_decimals": 3, "height": 430},
    {"base": "DSO charge", "kind": "line", "unit": "CHF/kWh",
     "title": "Componente rete di distribuzione (DSO)",
     "desc": "Costo della rete di distribuzione locale, per distretto",
     "district_order": DISTRICT_ORDER, "tooltip_decimals": 3,
     "height": 430},
    {"base": "Annual grid upgrading cost District", "kind": "line",
     "unit": "Mio CHF", "scale": 1e-6,
     "title": "Costi di rinforzo rete per distretto",
     "cumulative_title": "Investimenti cumulati di rinforzo rete per distretto",
     "time_basis": "flow",
     "desc": "Investimento annuo per potenziare la rete a bassa tensione",
     "district_order": DISTRICT_ORDER, "tooltip_decimals": 2,
     "legend": "bottom", "height": 430},
    {"base": "Levy Evolution", "kind": "line", "unit": "CHF/kWh",
     "title": "Supplemento federale in bolletta",
     "desc": 'Importo federale aggiunto al prezzo di ogni kWh consumato.',
     "tooltip_decimals": 3},
    {"base": "Cantonal Levy Evolution", "kind": "line", "unit": "CHF/kWh",
     "title": "Supplemento cantonale in bolletta",
     "desc": 'Importo cantonale aggiunto al prezzo di ogni kWh consumato.',
     "tooltip_decimals": 3},
    {"kind": "line_composite", "unit": "GWh",
     "title": "Energia PV annuale",
     "relative_view": True,
     "relative_components": ["Autoconsumo (SC)", "In rete"],
     "relative_denominator": "Produzione",
     "relative_note": "Autoconsumo e immissione in rete in percentuale della produzione PV annuale. La produzione è il denominatore, non una terza componente.",
     "history": "pv_production",
     "history_note": "Produzione PV storica cantonale in GWh, disponibile fino al 2023. "
                     "Non sono disponibili serie storiche separate per autoconsumo e immissione in rete.",
     "desc": "Produzione PV = autoconsumo + immissione in rete, in Ticino.",
     "height": 450,
     "series": [
         {"label": "Produzione", "bases": ["Total PV electricity production"]},
         {"label": "In rete", "bases": ["Total PV electricity injected in the grid"]},
         {"label": "Autoconsumo (SC)", "bases": ["Total PV electricity SC"]},
     ]},
    {"kind": "bar_grouped", "unit": "GWh", "year": 2050,
     "title": "Domanda e PV per distretto",
     "desc": "Barre: energia annua. Linee: produzione e autoconsumo rispetto al fabbisogno elettrico del distretto.",
     "district_order": DISTRICT_ORDER, "height": 450,
     "series": [
         {"label": "Domanda", "base": "Total annual demand Districts", "scale": 1e-6},
         {"label": "Produzione PV", "base": "Total PV electricity production District"},
         {"label": "Autoconsumo (SC)", "base": "PV electricity SC by District"},
     ]},
]

# Ordine e raggruppamento grafici in pagina (base Vensim o title dei composite)
CHART_ALIASES: dict[str, str] = {
    "Total Battery capacity < 100 kW": "Capacita' batterie non residenziale",
}

OUTPUT_GROUPS: list[dict] = [
    {
        "title": "Adozione fotovoltaico",
        "charts": [
            "PV residential power by Type",
            "Potenza PV non residenziale",
            "Share of buildings with PV by Type",
            "Share of buildings with PV by District",
        ],
    },
    {
        "title": "Adozione batterie",
        "charts": [
            "Battery residential Type",
            "Total Battery capacity < 100 kW",
            "Batteries by Type",
            "Total Battery capacity District",
        ],
    },
    {
        "title": "Produzione e consumi",
        "charts": [
            "Energia PV annuale",
            "Domanda e PV per distretto",
        ],
    },
    {
        # Due righe da due colonne: prezzo | rinforzo, poi i due supplementi.
        "title": "Prezzo elettricità e costi",
        "column_rows": [
            [
                {
                    # Un solo grafico alla volta, scelto da menu a tendina: le
                    # componenti hanno ordini di grandezza diversi e affiancarle
                    # le rende illeggibili.
                    "key": "componenti-prezzo",
                    "explain": "prezzo",
                    "selector": "Componente del prezzo",
                    "charts": [
                        "Electricity price",
                        "Energy price",
                        "DSO charge",
                    ],
                },
                {
                    "key": "rinforzo-rete",
                    "explain": "rinforzo",
                    "charts": [
                        "Annual grid upgrading cost District",
                    ],
                },
            ],
            [
                {
                    "key": "supplemento-federale",
                    "explain": "levy_federal",
                    "charts": ["Levy Evolution"],
                },
                {
                    "key": "supplemento-cantonale",
                    "explain": "levy_cantonal",
                    "charts": ["Cantonal Levy Evolution"],
                },
            ],
        ],
    },
]

# Variabili salvate nello store ma non disegnate come grafico: alimentano i KPI
# in cima alla pagina (foglio Excel: "Anni rappresentazione grafico" = 2050).
EXTRA_OUTPUT_BASES = [
    "Average electricity and heating and retrofit cost",
]

_bases: list[str] = []
for o in OUTPUTS:
    if "base" in o:
        _bases.append(o["base"])
    elif o.get("kind") == "line_composite":
        for spec in o["series"]:
            _bases.extend(spec["bases"])
    elif o.get("kind") == "bar_grouped":
        for spec in o["series"]:
            _bases.append(spec["base"])
_bases.extend(EXTRA_OUTPUT_BASES)
OUTPUT_BASES = list(dict.fromkeys(_bases))

# =============================================================
# EQUITY (GMD 2050) - ispirato al Notebook.ipynb
# value = variabile di cui si misura la disuguaglianza
# weight = variabile peso (numero di famiglie per archetipo), allineata per subscript
# =============================================================
GMD_SPEC = {
    "gmd_levy": {
        "value": "Average levy minus incentives archetype",
        "weight": "Cumulative archetype HH",
    },
    "gmd_cost": {
        "value": "Electricity and heating and retrofit annual cost",
        "weight": "Annual archetypes",
    },
}

# Tutte le variabili Vensim che servono al GMD (valori + pesi)
GMD_VARS = sorted({s["value"] for s in GMD_SPEC.values()}
                  | {s["weight"] for s in GMD_SPEC.values()})
