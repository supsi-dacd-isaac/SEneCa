"""Caricamento dati statici per la pagina System Dynamics."""
from __future__ import annotations

import os
from urllib.parse import quote

import pandas as pd
import streamlit as st
from dotenv import dotenv_values

from sd_explainer.paths import (
    EV_INPUT_CSV,
    HOUR_FACTORS_CSV,
    MAP_HTML,
    PLOTS_DATA,
    PV_INPUT_CSV,
    ROOT,
    SIM_ADOPTIONS_CSV,
)

CARTO_TILE_URL = (
    "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png"
)


def _year_column(df: pd.DataFrame) -> str:
    for col in ("year", "Year"):
        if col in df.columns:
            return col
    raise ValueError("Colonna anno non trovata nel CSV")


@st.cache_data(show_spinner=False)
def load_sector_csv(filename: str) -> pd.DataFrame:
    """CSV settori (sep=';') con colonna year/Year."""
    return pd.read_csv(PLOTS_DATA / filename, sep=";", on_bad_lines="skip")


def sector_csv_to_stacked(df: pd.DataFrame) -> tuple[list[str], dict[str, list[float]]]:
    """DataFrame settori -> categorie (anni) e serie impilate."""
    year_col = _year_column(df)
    categories = [str(int(y)) for y in df[year_col].tolist()]
    series = {
        str(col): [float(v) for v in df[col].tolist()]
        for col in df.columns
        if col != year_col
    }
    return categories, series


def sector_pie_at_year(df: pd.DataFrame, year: int) -> tuple[list[str], list[float]]:
    """Ripartizione settori per un anno (grafico a torta)."""
    year_col = _year_column(df)
    row = df.loc[df[year_col] == year]
    if row.empty:
        return [], []
    row = row.iloc[0]
    categories = [str(c) for c in df.columns if c != year_col]
    values = [float(row[c]) for c in categories]
    return categories, values


@st.cache_data(show_spinner=False)
def load_production_csv() -> pd.DataFrame:
    return load_sector_csv("Historical electricity production.csv")


def _hour_factors_row(raw: pd.DataFrame, name: str, cols: list) -> pd.Series:
    loc = raw.loc[name]
    if isinstance(loc, pd.DataFrame):
        loc = loc.iloc[0]
    return pd.to_numeric(loc[cols], errors="coerce").fillna(0.0)


@st.cache_data(show_spinner=False)
def load_historical_hydro_production(
) -> tuple[list[str], dict[str, list[float]]]:
    """Produzione elettrica storica 2011-2024 dalle serie di input del modello.

    Idroelettrico = bacini (inflow HS + apporto naturale ai bacini PHS, GWh).
    Acqua fluente e pompaggio sono le produzioni annue RR e PHS. Altro somma
    rifiuti, eolico e fotovoltaico.
    """
    raw = pd.read_csv(HOUR_FACTORS_CSV, index_col=0)
    cols = [
        c for c in raw.columns
        if str(c).strip().isdigit() and 2011 <= int(c) <= 2024
    ]
    hs = (
        _hour_factors_row(raw, "Annual HS inflow for Ticino", cols)
        + _hour_factors_row(raw, "Annual HS inflow NOT for Ticino", cols)
    )
    phsn = (
        _hour_factors_row(raw, "Annual PHSn inflow for Ticino", cols)
        + _hour_factors_row(raw, "Annual PHSn inflow NOT for Ticino", cols)
    )
    ror = (
        _hour_factors_row(raw, "RR annual production for Ticino", cols)
        + _hour_factors_row(raw, "RR annual production NOT for Ticino", cols)
    )
    phs = _hour_factors_row(raw, "PHS annual production", cols)
    other = (
        _hour_factors_row(raw, "Waste annual production", cols)
        + _hour_factors_row(raw, "Wind annual production", cols)
        + _hour_factors_row(raw, "PV annual production", cols)
    )
    years = [str(int(c)) for c in cols]
    return years, {
        "Idroelettrico": [float(v) for v in (hs + phsn) / 1000.0],
        "Acqua fluente": [float(v) for v in ror],
        "Idroelettrico con pompaggio": [float(v) for v in phs],
        "Altro": [float(v) for v in other],
    }


def production_line_series(
    df: pd.DataFrame, columns: list[str],
) -> tuple[list[str], dict[str, list[float | None]]]:
    year_col = _year_column(df)
    years = [str(int(y)) for y in df[year_col].tolist()]
    series = {
        col: [float(v) for v in df[col].tolist()]
        for col in columns
        if col in df.columns
    }
    return years, series


@st.cache_data(show_spinner=False)
def load_calibration_csv(filename: str) -> pd.DataFrame:
    """Calibrazione: righe Simulate/Dati storici, colonne anni."""
    return pd.read_csv(PLOTS_DATA / filename, sep=";", index_col=0, on_bad_lines="skip")


def calibration_to_grouped(df: pd.DataFrame) -> tuple[list[str], dict[str, list[float | None]]]:
    """Wide calibrazione -> anni + serie per riga."""
    years = [str(int(c)) for c in df.columns]
    series = {
        str(idx): [float(v) if pd.notna(v) else None for v in df.loc[idx].tolist()]
        for idx in df.index
    }
    return years, series


@st.cache_data(show_spinner=False)
def load_workshop_priorities() -> pd.DataFrame:
    """Priorità indicate dagli stakeholder: voce, menzioni alta e bassa.

    Valori estratti dal grafico del settimo workshop (ottobre 2025).
    """
    return pd.read_csv(PLOTS_DATA / "Workshop_priorities.csv", sep=";")


@st.cache_data(show_spinner=False)
def _load_map_template() -> str | None:
    """Legge una sola volta l'HTML statico, senza includere credenziali nella cache."""
    if not MAP_HTML.exists():
        return None
    return MAP_HTML.read_text(encoding="utf-8")


def load_map_html() -> str | None:
    """Aggiunge la chiave CARTO all'URL delle tile prima di mostrare la mappa."""
    html = _load_map_template()
    if html is None:
        return None

    api_key = (
        os.environ.get("CARTO_API_KEY")
        or dotenv_values(ROOT / ".env").get("CARTO_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return html
    return html.replace(
        CARTO_TILE_URL,
        f"{CARTO_TILE_URL}?key={quote(api_key, safe='')}",
        1,
    )


_EXTRA_CALIBRATION = {
    "Accumulatori": (
        PV_INPUT_CSV,
        [
            "Adoption Battery Type[SFH]",
            "Adoption Battery Type[DFH]",
            "Adoption Battery Type[MFH]",
        ],
    ),
    "Veicoli elettrici": (EV_INPUT_CSV, ["Adoption Vehicles[BEV]"]),
}


@st.cache_data(show_spinner=False)
def load_calibration_extra(
    tech: str,
) -> tuple[list[str], dict[str, list[float | None]]]:
    """Osservato contro simulato per accumulatori e veicoli elettrici.

    L'osservato viene dagli input del modello (`Vensim/`), il simulato dalla
    corsa di calibrazione usata per le figure della documentazione.
    """
    obs_path, rows = _EXTRA_CALIBRATION[tech]

    obs_raw = pd.read_csv(obs_path, index_col=0)
    years = [c for c in obs_raw.columns if c.strip().isdigit() and int(c) <= 2024]
    observed = sum(
        pd.to_numeric(obs_raw.loc[row, years], errors="coerce").fillna(0.0)
        for row in rows
    )

    sim_raw = pd.read_csv(SIM_ADOPTIONS_CSV, index_col=0)
    simulated = sim_raw[rows].sum(axis=1)
    simulated = simulated.reindex([int(y) for y in years])

    return years, {
        "Dati storici": [float(v) for v in observed],
        "Simulate": [None if pd.isna(v) else float(v) for v in simulated],
    }


@st.cache_data(show_spinner=False)
def load_pv_buildings_input(
    dimension: str,
) -> tuple[list[str], dict[str, list[float]]]:
    """Edifici con PV, cumulati 2011-2024, per distretto o tipo edilizio.

    Fonte: `Vensim/PVinput.csv`, gli stessi dati osservati che alimentano il
    modello. Le serie sono la somma cumulata delle adozioni annuali.
    """
    prefix = {
        "Distretto": "Adoption PV District[",
        "Tipo di edificio": "Adoption PV Type[",
    }[dimension]

    raw = pd.read_csv(PV_INPUT_CSV, index_col=0)
    years = [c for c in raw.columns if c.strip().isdigit() and int(c) <= 2024]
    rows = [idx for idx in raw.index if str(idx).startswith(prefix)]

    series: dict[str, list[float]] = {}
    for idx in rows:
        label = str(idx)[len(prefix):].rstrip("]")
        values = pd.to_numeric(raw.loc[idx, years], errors="coerce").fillna(0.0)
        series[label] = [float(v) for v in values.cumsum()]
    return years, series
