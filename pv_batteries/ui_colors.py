"""Palette SUPSI e colori di servizio condivisi dai grafici."""

SUPSI_PURPLE = "#6929C4"
SUPSI_BLUE = "#0D4CF6"
SUPSI_GREEN = "#60CB65"
SUPSI_TEAL = "#00C4AA"
SUPSI_SKY = "#00A3FF"
SUPSI_SOFT_GRAY = "#A7B4C8"

# Le tinte chiare SUPSI funzionano bene come superfici. Per linee sottili su
# bianco usiamo varianti più scure della stessa tinta.
DATA_COLORS = (
    SUPSI_BLUE,
    SUPSI_PURPLE,
    SUPSI_TEAL,
    SUPSI_SKY,
    SUPSI_GREEN,
    "#9654D8",
    "#4D74B8",
    "#426878",
    "#547D55",
)
LINE_COLORS = (
    SUPSI_BLUE,
    SUPSI_PURPLE,
    "#008875",
    "#007DBD",
    "#2D8437",
    "#7D35BC",
    "#345AAF",
    "#426878",
    "#456D48",
)

BASE_GRAY = "#667085"
CHART_TEXT = "#344054"

# Le categorie che ricorrono in più grafici mantengono la stessa tinta anche
# quando l'ordine delle serie cambia. Le altre seguono l'ordine del grafico.
CATEGORY_INDEX = {
    "SFH": 0, "DFH": 1, "MFH": 2,
    "Bellinzona": 0, "Blenio": 1, "Leventina": 2, "Locarno": 3,
    "Lugano": 4, "Mendrisio": 5, "Riviera": 6, "Vallemaggia": 7,
    "Carbone": 7, "Idroelettrico": 0, "Nucleare": 5,
    "Idroelettrico con pompaggio": 6, "Acqua fluente": 4,
    "Solare": 3, "Rifiuti": 8, "Eolico": 2, "Importazioni": 1,
}


def data_color(index: int, label: str | None = None) -> str:
    slot = CATEGORY_INDEX.get(label, index)
    return DATA_COLORS[slot % len(DATA_COLORS)]


def line_color(index: int, label: str | None = None) -> str:
    slot = CATEGORY_INDEX.get(label, index)
    return LINE_COLORS[slot % len(LINE_COLORS)]
