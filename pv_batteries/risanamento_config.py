"""Configurazione della sezione 2 "Riscaldamento e Risanamento".

Sorgente: "Input and Output Streamlit.xlsx" (foglio "Input", righe con "X" su
"Riscaldamento e Risanamento"; foglio "Output Risc e Risanamento").
"""
from __future__ import annotations

from pathlib import Path

from pv_batteries.policy_labels import input_metadata

ROOT = Path(__file__).resolve().parent.parent
VPMX = ROOT / "Vensim" / "SURE.vpmx"
STORE_DIR = ROOT / "precomputed" / "risanamento"
CONSOLIDATED_TRAJ = ROOT / "precomputed" / "risanamento_scenarios.parquet"
CONSOLIDATED_GMD = ROOT / "precomputed" / "risanamento_gmd.parquet"

SECTION = "risanamento"
RUN_NAME = "risan"

YEARS = range(2011, 2051)
FINAL_YEAR = 2050

# =============================================================
# INPUT (6 variabili -> 3*3*3*5*3*3 = 1215 combinazioni)
# =============================================================
INPUT_GRID: dict[str, list[float]] = {
    "Grant share HP": [0.0, 0.2, 0.4],
    "Grant share PelletBoiler": [0.0, 0.2, 0.4],
    "Grant share DH": [0.0, 0.2, 0.4],
    "Retrofit incentive input": [0.0, 25.0, 50.0, 75.0, 100.0],
    "CO2 tax": [0.0, 120.0, 240.0],
    "MuKEn scenario": [0.0, 1.0, 2.0],
}

INPUT_ORDER = list(INPUT_GRID.keys())

# Scenario Base (colonna "Base" in Input and Output Streamlit.xlsx)
BASE_SCENARIO: dict[str, float] = {
    "Grant share HP": 0.2,
    "Grant share PelletBoiler": 0.2,
    "Grant share DH": 0.2,
    "Retrofit incentive input": 50.0,
    "CO2 tax": 120.0,
    "MuKEn scenario": 1.0,
}

INPUT_META = input_metadata(INPUT_ORDER)

MUKEN_LABELS: dict[float, str] = {
    0.0: "Nessuno",
    1.0: "MoPEC 2014",
    2.0: "MoPEC 2025",
}
MUKEN_LABEL_TO_VALUE: dict[str, float] = {label: val for val, label in MUKEN_LABELS.items()}

# =============================================================
# OUTPUT (foglio "Output Risc e Risanamento")
# =============================================================
OUTPUTS = [
    {"kind": "line_composite", "unit": "kWh/m2y",
     "title": "Consumo specifico finale",
     "desc": "Consumo annuo per m² riscaldato. Il consumo netto esclude il calore ambiente delle pompe di calore.",
     "explain": "consumo", "legend": "bottom",
     "series": [
         {"label": "Consumo finale", "bases": ["Specific final consumption"]},
         {"label": "Consumo netto", "bases": ["Specific net final consumption"]},
     ]},
    {"kind": "line_composite", "unit": "GWh",
     "title": "Consumi annuali per vettore",
     "desc": "Riscaldamento e acqua calda in Ticino, incluso il calore ambiente delle pompe di calore.",
     "relative_view": True,
     "relative_note": "Quota di ciascun vettore sul consumo totale per il riscaldamento, incluso il calore ambiente. Nella vista cumulata, le quote sono calcolate sui consumi cumulati.",
     "relative_components": ["Olio", "Gas", "Legna", "Elettricità resistenza", "Elettricità PC", "Calore ambiente", "Solare termico", "Rete termica"],
     "cumulative_title": "Consumi cumulati per vettore",
     "time_basis": "flow",
     "legend": "bottom", "y_min": 0,
     "series": [
         {"label": "Olio", "bases": ["Annual consumption Oil"]},
         {"label": "Gas", "bases": ["Annual consumption Gas"]},
         {"label": "Legna", "bases": ["Annual consumption Wood"]},
         {"label": "Elettricità resistenza", "bases": ["Annual consumption Electricity EH"]},
         {"label": "Elettricità PC", "bases": ["Annual consumption Electricity HP"]},
         {"label": "Calore ambiente", "bases": ["Annual consumption Ambient Heat"]},
         {"label": "Solare termico", "bases": ["Annual consumption Solar"]},
         {"label": "Rete termica", "bases": ["Annual consumption DH"]},
     ]},
    {"base": "Building area by Performance", "kind": "line", "unit": "Mio m2",
     "title": "Superficie riscaldata per efficienza energetica",
     "desc": "Classi di prestazione dell’involucro: da molto bassa a molto alta.",
     "relative_view": True,
     "relative_note": "Quota di ciascuna classe di efficienza sulla superficie riscaldata totale nell’anno.",
     "legend": "bottom"},
    {"kind": "line_composite", "unit": "Mio CHF",
     "title": "Incentivi e fondi cantonali",
     "desc": "Incentivi pagati e quota finanziata dal Cantone, al netto dei fondi federali.",
     "cumulative_title": "Incentivi e fondi cantonali cumulati",
     "time_basis": "flow",
     "explain": "incentivi", "legend": "bottom",
     "series": [
         {"label": "Risanamento", "bases": ["Annual incentives Renovation"]},
         {"label": "Riscaldamento", "bases": ["Annual incentives Heating Technologies"]},
         {"label": "Fondi cantonali", "bases": ["Annual cantonal funds needed"]},
     ]},
]

CONSUMPTION_EXPLANATION = """
Entrambe le curve sono consumi **per metro quadrato riscaldato**: misurano quindi
l'efficienza del parco edifici e non risentono del fatto che la superficie costruita
cresca nel tempo.

- 🏠 **Consumo finale** — tutta l'energia che entra nell'edificio per il riscaldamento:
  olio, gas, legna, elettricità, rete termica e anche il **calore ambiente**, cioè la
  quota che le pompe di calore prelevano gratuitamente da aria, acqua o terreno.
- 🧾 **Consumo netto** — lo stesso conteggio **senza il calore ambiente**, cioè solo
  l'energia che viene effettivamente acquistata o prodotta.

La distanza fra le due curve è quindi il contributo gratuito delle pompe di calore, e
si allarga man mano che queste sostituiscono le caldaie. È il consumo netto quello che
si traduce in bolletta: una pompa di calore può far scendere il consumo netto anche
quando il fabbisogno di calore dell'edificio resta lo stesso.
"""

INCENTIVES_EXPLANATION = """
### 💰 Quali incentivi vengono pagati

- 🧱 **Risanamento** — l'incentivo è versato sui metri quadrati che passano a una classe
  di efficienza superiore, con importi crescenti a seconda del livello raggiunto. Lo slider *Contributo base al risanamento dell’involucro* fissa il valore
  specifico in CHF/m².
- 🔥 **Riscaldamento** — l'incentivo copre una frazione del costo di ogni impianto
  sostituito: pompe di calore, caldaie a pellet o legna e collettori solari. Caldaie a
  olio, a gas e riscaldamenti elettrici **non ricevono nulla**, per cui alzare i contributi
  agisce solo sulla velocità di sostituzione.

### 🏦 Chi paga: fondi cantonali e fondi federali

- Fino al **2024** il Cantone copre circa il **60 %** della spesa complessiva in
  incentivi; il resto arriva dai contributi globali della Confederazione.
- Dal **2025** i fondi federali sono legati al gettito della tassa CO2: partono da metà
  della spesa in incentivi registrata nel 2024 e **calano linearmente fino ad azzerarsi
  nel 2050**.
- I *fondi cantonali necessari* sono semplicemente quello che resta scoperto, cioè
  `incentivi totali − fondi federali`. Per questo la curva tende a
  salire anche a parità di incentivi: il sostegno federale si ritira.

### 🌍 Assunzioni sulla tassa CO2

- Il livello di riferimento è **120 CHF/tonCO2**; lo slider scala tutto rispetto a
  questo valore, e la variazione **entra in vigore solo dal 2025**.
- ⛽ La tassa si scarica sul **prezzo di olio e gas**: con i fattori di emissione usati
  nel modello (circa 265 gCO2/kWh per l'olio e 202 gCO2/kWh per il gas), passare da 120
  a 240 CHF/tonCO2 aggiunge all'incirca 3.2 ct/kWh all'olio e 2.4 ct/kWh al gas. È il
  canale che rende conveniente il cambio di impianto.
- 👛 Ogni archetipo di famiglia paga la tassa in proporzione a quanto olio o gas consuma:
  è questo saldo, al netto degli incentivi ricevuti, a determinare l'indice di equità.
- 🔁 Una tassa più alta aumenta anche i fondi federali disponibili per gli incentivi,
  alleggerendo in proporzione la quota a carico del Cantone.
"""

EXPLANATIONS: dict[str, tuple[str, str]] = {
    "consumo": ("Consumo finale e consumo netto: che differenza c'è",
                CONSUMPTION_EXPLANATION),
    "incentivi": ("Come funzionano incentivi, fondi e tassa CO2",
                  INCENTIVES_EXPLANATION),
}

# Indicatori principali (2050)
SUMMARY_METRICS = [
    {
        "label": "Emissioni cumulate CO2",
        "period_note": 'Emissioni cumulate dal 2026; fondi cantonali cumulati dal 2011, al 2050.',
        "base": "Cumulative CO2 emissions",
        "unit": "MtonCO2",
        "decimals": 0,
        "value": "year",
        "delta_color": "inverse",
    },
    {
        "label": "Equità tassa CO2",
        "gmd": "gmd_tax",
        "delta_color": "normal",
    },
    {
        "label": "Fondi cantonali cumulati",
        "base": "Annual cantonal funds needed",
        "unit": "Mio CHF",
        "decimals": 0,
        "value": "sum",
        "delta_color": "inverse",
    },
]

KPI_EXPLANATION = """Valori **al 2050**; variazioni rispetto allo scenario Base.

- **Emissioni cumulate**: emissioni residenziali accumulate dal 2026 [Mt CO₂].
- **Fondi cantonali cumulati**: incentivi finanziati dal Cantone, al netto dei fondi federali, sommati dal 2011 [Mio CHF].
- **Equità della tassa CO₂**: confronta tra famiglie il saldo tra tassa pagata e incentivi ricevuti.

L’equità riscalata sui precalcolati va da **0 (meno equo) a 1 (più equo)**. Misura le differenze tra famiglie, non quanto pagano in media; non è una percentuale."""

_bases: list[str] = []
for o in OUTPUTS:
    if "base" in o:
        _bases.append(o["base"])
    elif o.get("kind") == "line_composite":
        for spec in o["series"]:
            _bases.extend(spec["bases"])
for m in SUMMARY_METRICS:
    if base := m.get("base"):
        _bases.append(base)
OUTPUT_BASES = list(dict.fromkeys(_bases))

# =============================================================
# EQUITY (GMD 2050) - disuguaglianza legata alla CO2 tax
# =============================================================
GMD_SPEC = {
    "gmd_tax": {
        "value": "Average tax minus incentives archetype",
        "weight": "Cumulative archetype HH",
    },
}

GMD_VARS = sorted({s["value"] for s in GMD_SPEC.values()}
                  | {s["weight"] for s in GMD_SPEC.values()})
