"""Palette SUPSI e colori di servizio condivisi dai grafici."""

SUPSI_PURPLE = "#6929C4"
SUPSI_BLUE = "#0D4CF6"
SUPSI_GREEN = "#60CB65"
SUPSI_TEAL = "#00C4AA"
SUPSI_SKY = "#00A3FF"
SUPSI_SOFT_GRAY = "#A7B4C8"

# Palette categorica predefinita di Streamlit (tema chiaro), per tutti i grafici.
STREAMLIT_CHART_COLORS = (
    "#0068c9",
    "#83c9ff",
    "#ff2b2b",
    "#ffabab",
    "#29b09d",
    "#7defa1",
    "#ff8700",
    "#ffd16a",
    "#6d3fc0",
    "#d5dae5",
)
DATA_COLORS = STREAMLIT_CHART_COLORS
LINE_COLORS = STREAMLIT_CHART_COLORS

BASE_GRAY = "#667085"
CHART_TEXT = "#344054"

# Indici storici delle categorie. Il colore effettivo segue l'ordine della
# palette Streamlit, indipendentemente dal numero di serie.
CATEGORY_INDEX = {
    "SFH": 0, "DFH": 1, "MFH": 2,
    "Bellinzona": 0, "Blenio": 1, "Leventina": 2, "Locarno": 3,
    "Lugano": 4, "Mendrisio": 5, "Riviera": 6, "Vallemaggia": 7,
    "Carbone": 7, "Idroelettrico": 0, "Nucleare": 5,
    "Idroelettrico con pompaggio": 6, "Acqua fluente": 4,
    "Solare": 3, "Rifiuti": 8, "Eolico": 2, "Importazioni": 1,
}


def palette_for(n: int, *, lines: bool = False) -> tuple[str, ...]:
    """Palette categorica predefinita di Streamlit, per qualsiasi numero di serie."""
    del n, lines
    return STREAMLIT_CHART_COLORS


def data_color(index: int, label: str | None = None, *, n: int = 1) -> str:
    colors = palette_for(n, lines=False)
    return colors[index % len(colors)]


def line_color(index: int, label: str | None = None, *, n: int = 1) -> str:
    colors = palette_for(n, lines=True)
    return colors[index % len(colors)]
