"""Configurazione sezione 3 "Veicoli".

Sorgente: "Input and Output Streamlit.xlsx" (fogli Input + Output Veicoli).
Nessun calcolo GMD richiesto.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VPMX = ROOT / "Vensim" / "SURE.vpmx"
STORE_DIR = ROOT / "precomputed" / "veicoli"
CONSOLIDATED_TRAJ = ROOT / "precomputed" / "veicoli_scenarios.parquet"
CONSOLIDATED_GMD = ROOT / "precomputed" / "veicoli_gmd.parquet"  # non usato

SECTION = "veicoli"
RUN_NAME = "veic"

YEARS = range(2011, 2051)
FINAL_YEAR = 2050

DISTRICT_ORDER = [
    "Bellinzona", "Blenio", "Leventina", "Locarno",
    "Lugano", "Mendrisio", "Riviera", "Vallemaggia",
]

# 3*4*4*3 = 144 combinazioni
# "ICE ban year" e' stato rimosso dagli input di "Input and Output Streamlit.xlsx":
# resta al default del modello (2050, nessun divieto effettivo), che coincide con
# il valore Base usato finora.
INPUT_GRID: dict[str, list[float]] = {
    "EV charger incentive input": [0.0, 2000.0, 4000.0],
    "CO2 coefficient ICE": [1.0, 2.0, 3.0, 4.0],
    "EV annual cost reduction input": [0.0, 0.01, 0.02, 0.03],
    "ICE fuel price input": [2.0, 2.5, 3.0],
}

INPUT_ORDER = list(INPUT_GRID.keys())

# Scenario Base (colonna "Base" in Input and Output Streamlit.xlsx)
BASE_SCENARIO: dict[str, float] = {
    "EV charger incentive input": 2000.0,
    "CO2 coefficient ICE": 2.0,
    "EV annual cost reduction input": 0.01,
    "ICE fuel price input": 2.0,
}

INPUT_META = {
    "EV charger incentive input": {"label": "Incentivo colonnina EV", "unit": "CHF"},
    "CO2 coefficient ICE": {"label": "Coefficiente tassa ICE", "unit": "-"},
    "EV annual cost reduction input": {"label": "Riduzione annuale costo EV", "unit": "-"},
    "ICE fuel price input": {"label": "Prezzo carburante ICE", "unit": "CHF/l"},
}

OUTPUTS = [
    {"base": "Adoption Vehicles", "kind": "line", "unit": "veicoli",
     "title": "Immatricolazioni annue per tipo",
     "legend": "bottom"},
    {"base": "Vehicles by type", "kind": "line", "unit": "veicoli",
     "title": "Parco veicoli per tipo",
     "legend": "bottom"},
    {"base": "Annual CO2 emissions vehicles flow", "kind": "line", "unit": "MtonCO2",
     "title": "Emissioni annuali CO2",
     # Prima del 2026 la serie riflette la sola inizializzazione del modello.
     "start_year": 2026, "legend": "bottom"},
    {"base": "EV by district", "kind": "bar", "year": 2050, "unit": "veicoli",
     "title": "BEV per distretto",
     "district_order": DISTRICT_ORDER},
]

# Griglia grafici: ogni riga = coppia affiancata (base Vensim)
OUTPUT_LAYOUT = [
    ["Adoption Vehicles", "Vehicles by type"],
    ["Annual CO2 emissions vehicles flow", "EV by district"],
]

SUMMARY_METRICS = [
    {
        "label": "Emissioni cumulate CO2",
        "base": "Cumulative CO2 emissions vehicles",
        "unit": "MtonCO2",
        "decimals": 0,
        "value": "year",
    },
    {
        "label": "Totale EV",
        "base": "Vehicles by type",
        "elem": "BEV",
        "unit": "veicoli",
        "decimals": 0,
        "value": "year",
    },
    {
        # Fuori dal radar: il parco totale e' esogeno, quindi la quota varia
        # esattamente come il totale EV e duplicherebbe quell'asse.
        "label": "Quota EV sul parco",
        "base": "Vehicles by type",
        "elem": "BEV",
        "over": "Vehicles by type",
        "unit": "%",
        "decimals": 1,
        "value": "year",
        "radar": False,
    },
]

KPI_EXPLANATION = f"""
Tutti gli indicatori sono riferiti al **{FINAL_YEAR}**; la variazione percentuale sotto
ogni valore è il confronto con lo scenario Base.

- **Emissioni cumulate CO2** — emissioni dei veicoli accumulate lungo tutto l'orizzonte
  di simulazione. Essendo un totale cumulato conta l'intero percorso e non solo il punto
  di arrivo: raggiungere tardi la stessa flotta elettrica lascia comunque più CO2 in
  atmosfera.
- **Totale EV** — veicoli elettrici a batteria (BEV) circolanti. Gli ibridi plug-in sono
  contati a parte e non rientrano in questo valore.
- **Quota EV sul parco** — gli stessi BEV espressi come percentuale del parco veicoli
  totale. Il parco complessivo è un'ipotesi esogena del modello e non reagisce agli
  incentivi, quindi questa quota si muove esattamente come il totale EV: è una lettura
  più comoda, non un'informazione in più, ed è il motivo per cui non compare nel radar.

Questa sezione non ha un indice di equità: gli effetti distributivi della transizione
sono misurati nelle pagine *PV e Batterie* e *Riscaldamento e Risanamento*.
"""

OUTPUT_BASES = list(dict.fromkeys(
    [o["base"] for o in OUTPUTS if "base" in o]
    + [m["base"] for m in SUMMARY_METRICS if "base" in m]
))

GMD_SPEC: dict = {}
GMD_VARS: list[str] = []
