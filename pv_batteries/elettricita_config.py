"""Configurazione sezione 4 "Elettricità".



Output orari subscript [Month,Hour,Supplier] o [Month,Hour].

Salvataggio completo (tutti i mesi/anni); visualizzazione su M1/M7 e 2024/2035/2050.

"""

from __future__ import annotations



from pathlib import Path



ROOT = Path(__file__).resolve().parent.parent

VPMX = ROOT / "Vensim" / "SURE.vpmx"

STORE_DIR = ROOT / "precomputed" / "elettricita"

CONSOLIDATED_HOURLY = ROOT / "precomputed" / "elettricita_hourly.parquet"

CONSOLIDATED_COMBO_INDEX = ROOT / "precomputed" / "elettricita_combo_index.parquet"



SECTION = "elettricita"

RUN_NAME = "elec"



YEARS = range(2011, 2051)

FINAL_YEAR = 2050



# 3*3*2*2*2*2 = 144 combinazioni
#
# Le due leve idroelettriche continue ("Seasonal PHS annual production 2050" e
# "Additional annual inflow for Ticino") non esistono piu' nel modello: sono
# state sostituite dai quattro provvedimenti binari del PECC.
#
# "Deflussi minimi LPAc" e "Cambiamento climatico Hydro" non sono piu' input
# della pagina: non vengono impostati, quindi restano al default del modello
# pubblicato (entrambi = 1).
#
# Nota FiT: nel modello Vensim e' in CHF/kWh; l'Excel lo esprime in ct/kWh
# (0-10). I valori discreti usati qui sono 0/0.05/0.10 CHF/kWh (= 0/5/10 ct/kWh).
INPUT_GRID: dict[str, list[float]] = {

    "FiT": [0.0, 0.05, 0.10],

    "PV rebate federal": [0.0, 0.2, 0.4],

    "Provvedimento 1.2": [0.0, 1.0],

    "Provvedimento 1.3": [0.0, 1.0],

    "Provvedimento 1.4": [0.0, 1.0],

    "Provvedimento 1.7": [0.0, 1.0],

}



INPUT_ORDER = list(INPUT_GRID.keys())

# Input binari in sidebar (bottoni Sì/No invece di slider)
BINARY_INPUTS = frozenset({
    "Provvedimento 1.2", "Provvedimento 1.3", "Provvedimento 1.4",
    "Provvedimento 1.7",
})
BINARY_LABELS = ("No", "Sì")

# Scenario Base (colonna "Base" in Input and Output Streamlit.xlsx)
BASE_SCENARIO: dict[str, float] = {
    "FiT": 0.0,
    "PV rebate federal": 0.2,
    "Provvedimento 1.2": 0.0,
    "Provvedimento 1.3": 0.0,
    "Provvedimento 1.4": 0.0,
    "Provvedimento 1.7": 0.0,
}

INPUT_META = {

    "FiT": {"label": "FiT", "unit": "CHF/kWh"},

    "PV rebate federal": {"label": "PV rebate federale", "unit": "-"},

    "Provvedimento 1.2": {"label": "Provv. 1.2 PECC (hydro dam)", "unit": "-"},

    "Provvedimento 1.3": {"label": "Provv. 1.3 PECC (PHS)", "unit": "-"},

    "Provvedimento 1.4": {"label": "Provv. 1.4 PECC (RoR)", "unit": "-"},

    "Provvedimento 1.7": {"label": "Provv. 1.7 PECC (hydro dam)", "unit": "-"},

}



ALL_MONTHS = [f"M{i}" for i in range(1, 13)]



# Visualizzazione Streamlit (subset dello store completo)

DISPLAY_MONTHS = ["M1", "M7"]

DISPLAY_YEARS = [2024, 2035, 2050]



OUTPUTS = [

    {"base": "Electricity dispatched", "has_supplier": True, "unit": "GWh",
     "title": "Elettricita' dispacciata | totale annuo per supplier",
     "desc": "Elettricità oraria dispacciata in rete",
     "extended_layout": True,
     "annual_echarts": True, "annual_data_zoom": True,
     "stacked_echarts": True},

    {"base": "Hourly exported electricity", "has_supplier": True, "unit": "GWh",
     "title": "Elettricita' esportata | totale annuo per supplier",
     "desc": "Elettricità oraria esportata",
     "extended_layout": True,
     "annual_echarts": True, "annual_data_zoom": True,
     "stacked_echarts": True},

    {"base": "Electricity consumed", "has_supplier": True, "unit": "GWh",
     "title": "Elettricita' consumata | totale annuo per supplier",
     "desc": "Elettricità oraria consumata",
     "extended_layout": True,
     "annual_echarts": True, "annual_data_zoom": True,
     "stacked_echarts": True},

    {"base": "Hourly available supply by Supplier", "has_supplier": True, "unit": "GWh",
     "title": "Elettricita' offerta nel mercato | totale annuo per supplier",
     "desc": "Elettricità oraria offerta nel mercato",
     "exclude_suppliers": ["Import"],
     "extended_layout": True,
     "annual_echarts": True, "annual_data_zoom": True,
     "stacked_echarts": True},

    {"base": "PHS hourly demand", "has_supplier": False, "unit": "GWh",
     "title": "Domanda oraria PHS",
     "desc": "Domanda oraria PHS",
     "hourly_area_echarts": True},

]



# KPI al FINAL_YEAR: totale annuo (somma di mesi e ore) della variabile oraria,
# per singolo supplier se indicato.
SUMMARY_METRICS = [
    {
        "label": "Offerta locale",
        "variable": "Hourly available supply by Supplier",
        "unit": "GWh",
        "decimals": 1,
    },
    {
        "label": "Offerta solare",
        "variable": "Hourly available supply by Supplier",
        "supplier": "Solar",
        "unit": "GWh",
        "decimals": 1,
    },
    {
        "label": "Elettricità consumata",
        "variable": "Electricity consumed",
        "unit": "GWh",
        "decimals": 1,
    },
    {
        "label": "Elettricità esportata",
        "variable": "Hourly exported electricity",
        "unit": "GWh",
        "decimals": 1,
    },
    {
        "label": "Importazioni",
        "variable": "Electricity dispatched",
        "supplier": "Import",
        "unit": "GWh",
        "decimals": 2,
    },
]

CONCEPTS_EXPLANATION = """
Le quattro grandezze descrivono lo stesso kWh in momenti diversi del suo percorso. Il
modello simula **un giorno tipo per ogni mese**, ora per ora, distinguendo le fonti
(*supplier*): solare, eolico, nucleare, acqua fluente, bacini idroelettrici,
pompaggio, rifiuti, carbone e importazioni.

- ⚡ **Offerta (produzione disponibile)** — quanta elettricità ciascuna fonte
  *potrebbe* mettere a disposizione in quell'ora, dati gli impianti installati e le
  condizioni di sole, vento e portate. È un potenziale, non ancora un consumo. Nei
  grafici di questa pagina le importazioni sono escluse, quindi va letta come
  **offerta locale**.
- 🔀 **Dispacciata** — la parte di quell'offerta che viene effettivamente immessa in
  rete per coprire la domanda di quell'ora. Il modello la assegna seguendo un ordine
  di priorità fra le fonti, fino a coprire il fabbisogno: consumo degli utenti più
  l'assorbimento degli impianti di pompaggio.
- 🏠 **Consumata** — l'elettricità realmente utilizzata in Ticino: la dispacciata più
  l'**autoconsumo fotovoltaico**, cioè la quota di produzione PV usata direttamente
  nell'edificio senza mai passare dalla rete.
- 🌍 **Esportata** — il surplus, cioè `offerta − dispacciata`. È l'energia che le fonti
  locali potrebbero produrre ma che in quell'ora nessuno consuma qui, e che quindi
  esce dal cantone.

In sintesi: **offerta = dispacciata + esportata**, mentre la **consumata** aggiunge
alla dispacciata l'autoconsumo fotovoltaico, che non transita dalla rete.

🔄 **Domanda oraria PHS** — sta a parte rispetto alle quattro: è l'elettricità che gli
impianti di pompaggio *assorbono* per risalire l'acqua nei bacini. Non è un consumo
finale ma un accumulo, e rientra nella domanda che il dispacciamento deve coprire.

📅 **Nota sulle quantità.** Poiché il modello calcola un giorno rappresentativo per
mese, i totali mensili e annuali mostrati qui sono riscalati sui giorni di un mese
medio (365/12 ≈ 30.4). I profili orari sono invece il giorno tipo così com'è.
"""

KPI_EXPLANATION = f"""
Tutti gli indicatori sono totali dell'anno **{FINAL_YEAR}**; la variazione percentuale
sotto ogni valore è il confronto con lo scenario Base.

- **Offerta locale** — elettricità che le fonti in Ticino potrebbero produrre
  nell'anno, **escluse le importazioni**. Cresce con il fotovoltaico e con i
  provvedimenti PECC sull'idroelettrico.
- **Offerta solare** — la sola quota fotovoltaica dell'indicatore precedente: è la
  parte su cui agiscono direttamente la tariffa di ritiro (FiT) e il rimborso
  federale.
- **Elettricità consumata** — quanto viene effettivamente usato in Ticino, cioè rete
  più autoconsumo fotovoltaico.
- **Elettricità esportata** — il surplus che esce dal cantone perché prodotto in ore
  in cui non c'è domanda locale. Una crescita marcata segnala che la produzione
  aggiuntiva non trova sbocco nel momento in cui viene generata.
- **Importazioni** — elettricità dispacciata proveniente da fuori cantone, cioè le ore
  in cui la produzione locale non basta a coprire la domanda.

Letti insieme, esportazioni e importazioni raccontano il **disallineamento temporale**
fra produzione e consumo: nello stesso scenario possono crescere entrambe, perché si
riferiscono a ore diverse dell'anno.
"""

OUTPUT_BASES = [o["base"] for o in OUTPUTS]


