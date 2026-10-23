"""Configurazione sezione 4 "Elettricità".



Output orari subscript [Month,Hour,Supplier] o [Month,Hour].

Salvataggio completo (tutti i mesi/anni); visualizzazione su M1/M7 e 2024/2035/2050.

"""

from __future__ import annotations



from pathlib import Path

from pv_batteries.policy_labels import input_metadata



ROOT = Path(__file__).resolve().parent.parent

VPMX = ROOT / "Vensim" / "SURE.vpmx"

STORE_DIR = ROOT / "precomputed" / "elettricita"

CONSOLIDATED_HOURLY = ROOT / "precomputed" / "elettricita_hourly.parquet"

CONSOLIDATED_COMBO_INDEX = ROOT / "precomputed" / "elettricita_combo_index.parquet"



SECTION = "elettricita"

RUN_NAME = "elec"



YEARS = range(2011, 2051)

FINAL_YEAR = 2050



# 2*3*2*2*2*2 = 96 combinazioni
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
# (0-5 sulla pagina Elettricità, due valori). I valori discreti usati qui
# sono 0/0.05 CHF/kWh (= 0/5 ct/kWh).
INPUT_GRID: dict[str, list[float]] = {

    "FiT": [0.0, 0.05],

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

INPUT_META = input_metadata(INPUT_ORDER)



ALL_MONTHS = [f"M{i}" for i in range(1, 13)]



# Visualizzazione Streamlit (subset dello store completo)

DISPLAY_MONTHS = ["M1", "M7"]

DISPLAY_YEARS = [2024, 2035, 2050]



OUTPUTS = [

    {"base": "Electricity dispatched", "caption": 'Elettricità fornita dalla rete, per fonte; include le importazioni.', "has_supplier": True, "unit": "GWh",
     "title": "Elettricità distribuita dalla rete | totale annuo per fonte",
     "desc": "Elettricità oraria dispacciata in rete",
     "relative_view": True,
     "relative_note": "Quota di ciascuna fonte sull’elettricità dispacciata nel periodo selezionato, incluse le importazioni.",
     "extended_layout": True,
     "annual_echarts": True, "annual_data_zoom": True,
     "stacked_echarts": True},

    {"base": "Hourly exported electricity", "caption": 'Elettricità prodotta in Ticino e destinata fuori cantone.', "has_supplier": True, "unit": "GWh",
     "title": "Elettricità esportata | totale annuo per fonte",
     "desc": "Elettricità oraria esportata",
     "relative_view": True,
     "relative_note": "Quota di ciascuna fonte sull’elettricità esportata nel periodo selezionato.",
     "extended_layout": True,
     "annual_echarts": True, "annual_data_zoom": True,
     "stacked_echarts": True},

    {"base": "Electricity consumed", "caption": 'Elettricità usata in Ticino: rete e autoconsumo PV.', "has_supplier": True, "unit": "GWh",
     "title": "Elettricità consumata | totale annuo per fonte",
     "desc": "Elettricità oraria consumata",
     "relative_view": True,
     "relative_note": "Quota di ciascuna fonte sull’elettricità consumata nel periodo selezionato, incluse le importazioni.",
     "extended_layout": True,
     "annual_echarts": True, "annual_data_zoom": True,
     "stacked_echarts": True},

    {"base": "Hourly available supply by Supplier", "caption": 'Produzione locale disponibile, prima della scelta delle fonti da utilizzare.', "has_supplier": True, "unit": "GWh",
     "title": "Offerta elettrica locale | totale annuo per fonte",
     "desc": "Elettricità oraria offerta nel mercato",
     "relative_view": True,
     "relative_note": "Quota di ciascuna fonte sull’offerta locale nel periodo selezionato. Le importazioni sono escluse dal totale.",
     "exclude_suppliers": ["Import"],
     "extended_layout": True,
     "annual_echarts": True, "annual_data_zoom": True,
     "stacked_echarts": True},

    {"base": "PHS hourly demand", "caption": 'Elettricità assorbita per pompare acqua nei bacini di accumulo.', "has_supplier": False, "unit": "GWh",
     "title": "Elettricità per il pompaggio",
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
        "delta_color": "normal",
    },
    {
        "label": "Offerta solare",
        "variable": "Hourly available supply by Supplier",
        "supplier": "Solar",
        "unit": "GWh",
        "decimals": 1,
        "delta_color": "normal",
    },
    {
        "label": "Elettricità consumata",
        "variable": "Electricity consumed",
        "unit": "GWh",
        "decimals": 1,
        "delta_color": "off",
    },
    {
        "label": "Elettricità esportata",
        "variable": "Hourly exported electricity",
        "unit": "GWh",
        "decimals": 1,
        "delta_color": "off",
    },
    {
        "label": "Importazioni",
        "variable": "Electricity dispatched",
        "supplier": "Import",
        "unit": "GWh",
        "decimals": 2,
        "delta_color": "inverse",
    },
]

CONCEPTS_EXPLANATION = """Il modello usa **un giorno tipo per mese**, con queste grandezze:

- **Offerta locale**: elettricità che gli impianti ticinesi possono produrre.
- **Distribuita dalla rete (dispacciata)**: elettricità assegnata alle fonti per coprire la domanda, incluso il pompaggio.
- **Consumata**: elettricità distribuita dalla rete più autoconsumo PV.
- **Esportata**: produzione locale disponibile che non viene usata in Ticino.
- **Pompaggio**: elettricità per riportare acqua nei bacini di accumulo.

I totali mensili e annui sono stimati dai giorni tipo, con **365/12 giorni per mese**."""

KPI_EXPLANATION = """Totali annui **al 2050** [GWh]; variazioni rispetto allo scenario Base.

- **Offerta locale**: produzione disponibile in Ticino, senza importazioni.
- **Offerta solare**: componente PV dell’offerta locale.
- **Consumo**: elettricità usata, rete più autoconsumo PV.
- **Esportazioni**: produzione locale disponibile in eccesso rispetto alla domanda.
- **Importazioni**: elettricità proveniente da fuori cantone.

Importazioni ed esportazioni possono coesistere: produzione e domanda cambiano da un’ora all’altra."""

OUTPUT_BASES = [o["base"] for o in OUTPUTS]

# Nomi Vensim dei supplier → etichette di legenda (pagina Elettricità e Esplora).
SUPPLIER_LABELS: dict[str, str] = {
    "Coal": "Carbone",
    "Hydro": "Idroelettrico",
    "Nuclear": "Nucleare",
    "PHS": "Idroelettrico con pompaggio",
    "RoR": "Acqua fluente",
    "Solar": "Solare",
    "Waste": "Rifiuti",
    "Wind": "Eolico",
    "Import": "Importazioni",
}

