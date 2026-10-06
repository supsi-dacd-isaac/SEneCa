"""Configurazione della sezione 2 "Riscaldamento e Risanamento".

Sorgente: "Input and Output Streamlit.xlsx" (foglio "Input", righe con "X" su
"Riscaldamento e Risanamento"; foglio "Output Risc e Risanamento").
"""
from __future__ import annotations

from pathlib import Path

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

INPUT_META = {
    "Grant share HP": {"label": "Rimborso pompe di calore", "unit": "-"},
    "Grant share PelletBoiler": {"label": "Rimborso stufe a legna", "unit": "-"},
    "Grant share DH": {"label": "Rimborso rete termica", "unit": "-"},
    "Retrofit incentive input": {"label": "Incentivo risanamento", "unit": "CHF/m2"},
    "CO2 tax": {"label": "Tassa CO2", "unit": "CHF/tonCO2"},
    "MuKEn scenario": {"label": "Regolamentazione riscaldamento", "unit": "-"},
}

MUKEN_LABELS: dict[float, str] = {
    0.0: "Nessuna",
    1.0: "MoPEc 2014",
    2.0: "MoPEc 2025",
}
MUKEN_LABEL_TO_VALUE: dict[str, float] = {label: val for val, label in MUKEN_LABELS.items()}

# =============================================================
# OUTPUT (foglio "Output Risc e Risanamento")
# =============================================================
OUTPUTS = [
    {"kind": "line_composite", "unit": "kWh/m2y",
     "title": "Consumo specifico finale",
     "explain": "consumo", "legend": "bottom",
     "series": [
         {"label": "Consumo finale", "bases": ["Specific final consumption"]},
         {"label": "Consumo netto", "bases": ["Specific net final consumption"]},
     ]},
    {"kind": "line_composite", "unit": "GWh",
     "title": "Consumi annuali per vettore",
     "legend": "bottom",
     "series": [
         {"label": "Olio", "bases": ["Annual consumption Oil"]},
         {"label": "Gas", "bases": ["Annual consumption Gas"]},
         {"label": "Legna", "bases": ["Annual consumption Wood"]},
         {"label": "Elettricità resistenza", "bases": ["Annual consumption Electricity EH"]},
         {"label": "Elettricità PC", "bases": ["Annual consumption Electricity HP"]},
         {"label": "Calore ambiente", "bases": ["Annual consumption Ambient Heat"]},
         {"label": "Solare", "bases": ["Annual consumption Solar"]},
         {"label": "Rete termica", "bases": ["Annual consumption DH"]},
     ]},
    {"base": "Building area by Performance", "kind": "line", "unit": "Mio m2",
     "title": "Superficie riscaldata per efficienza energetica",
     "legend": "bottom"},
    {"kind": "line_composite", "unit": "Mio CHF",
     "title": "Incentivi e fondi cantonali",
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
  di efficienza superiore, con importi crescenti a seconda del livello raggiunto. Lo slider *Incentivo risanamento* fissa il valore
  specifico in CHF/m².
- 🔥 **Riscaldamento** — l'incentivo copre una frazione del costo di ogni impianto
  sostituito: pompe di calore, caldaie a pellet o legna e collettori solari. Caldaie a
  olio, a gas e riscaldamenti elettrici **non ricevono nulla**, per cui alzare i rimborsi
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
        "base": "Cumulative CO2 emissions",
        "unit": "MtonCO2",
        "decimals": 0,
        "value": "year",
    },
    {
        "label": "Equità tassa CO2",
        "gmd": "gmd_tax",
    },
    {
        "label": "Fondi cantonali cumulati",
        "base": "Annual cantonal funds needed",
        "unit": "Mio CHF",
        "decimals": 0,
        "value": "sum",
    },
]

KPI_EXPLANATION = rf"""
La variazione percentuale sotto ogni valore è il confronto con lo scenario Base.

- **Emissioni cumulate CO2** — emissioni degli edifici residenziali accumulate lungo
  tutto l'orizzonte di simulazione, fino al {FINAL_YEAR}. Essendo un totale cumulato
  conta l'intero percorso e non solo il punto di arrivo: ritardare gli interventi
  peggiora l'indicatore anche a parità di situazione finale.
- **Fondi cantonali cumulati** — somma su tutti gli anni dei fondi che il Cantone deve
  stanziare per finanziare gli incentivi, cioè il costo complessivo della politica per
  le casse cantonali.

### L'indice di equità

**Equità tassa CO2** misura *quanto diversamente* il peso della transizione ricade sulle
famiglie, non quanto è alto in assoluto. La grandezza confrontata è, per ogni archetipo
di famiglia, il saldo fra **tassa CO2 pagata e incentivi ricevuti**: un archetipo che
scalda a olio e non risana paga molto e incassa poco, uno che passa alla pompa di calore
incassa l'incentivo e smette di pagare la tassa.

Il punto di partenza è la *Gini Mean Difference* pesata, cioè la differenza media in
valore assoluto fra tutte le coppie di archetipi, pesata per quante famiglie ciascuno
rappresenta:

$$\mathrm{{GMD}} = \frac{{\sum_i \sum_j w_i w_j\, |x_i - x_j|}}{{2\,W^2}}$$

Vale zero quando tutti gli archetipi sopportano esattamente lo stesso saldo, e cresce
via via che le situazioni divergono.

**Come leggere il numero.** Il GMD grezzo è in CHF per abitazione e poco interpretabile
da solo, quindi viene riscalato da 0 a 1 usando il minimo e il massimo osservati
**sull'intero store degli scenari precalcolati**: 1 identifica lo scenario più equo fra
quelli disponibili, 0 il meno equo. È quindi un indice **relativo** al ventaglio di
scenari e non una misura assoluta: 0.5 significa "a metà strada fra lo scenario migliore
e quello peggiore", e i valori cambierebbero cambiando la griglia degli scenari.
"""

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
