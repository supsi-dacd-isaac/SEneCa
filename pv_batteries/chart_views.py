"""Viste temporali e riferimenti storici, senza modificare le traiettorie."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from pv_batteries.i18n import tr, chart_text
from pv_batteries.history_data import available_history

ROOT = Path(__file__).resolve().parent.parent


def transform_series(frame: pd.DataFrame, basis: str | None, mode: str) -> pd.DataFrame:
    """Stock: incremento t→t+1. Flussi: somma inclusiva degli anni mostrati.

    Un intervallo mancante resta mancante; non viene convertito in zero né
    interpolato. Il punto finale di uno stock non permette un incremento.
    """
    frame = frame.sort_index()
    if frame.empty:
        return frame.copy()
    if basis == "stock" and mode == "annual":
        result = frame.shift(-1) - frame
        contiguous = frame.index.to_series().shift(-1) - frame.index.to_series() == 1
        return result.where(contiguous, axis=0)
    if basis == "flow" and mode == "cumulative":
        full = frame.reindex(range(int(frame.index.min()), int(frame.index.max()) + 1))
        return full.cumsum(skipna=False).reindex(frame.index)
    return frame.copy()


def relative_series(frame: pd.DataFrame, denominator: pd.Series | None = None) -> pd.DataFrame:
    """Percent of the complete row total; zero/missing totals have no share."""
    total = (frame.sum(axis=1, min_count=len(frame.columns))
             if denominator is None else denominator.reindex(frame.index))
    valid = frame.notna().all(axis=1) & frame.ge(0).all(axis=1) & total.gt(0)
    return frame.div(total.where(valid), axis=0).mul(100)


def composition_series(frame: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """Normalize disjoint components, optionally against an explicit total."""
    components = meta.get("relative_components", list(frame.columns))
    denominator = None
    if total_label := meta.get("relative_denominator"):
        denominator = frame.reindex(columns=[total_label]).iloc[:, 0]
    return relative_series(frame.reindex(columns=components), denominator)


def composition_controls(meta: dict, key: str) -> bool:
    if not meta.get("relative_view"):
        return False
    labels = {"absolute": tr("Valori assoluti"), "relative": tr("Quote sul totale [%]")}
    value = st.segmented_control(tr("Rappresentazione"), list(labels),
                                 format_func=labels.get, default="absolute",
                                 key=f"{key}_composition")
    if value == "relative":
        st.caption(tr(meta.get("relative_note", "Quota sul totale di tutti i tipi nell’anno, calcolata separatamente per ogni scenario. Nascondere una serie non cambia il denominatore.")))
        if meta.get("relative_note"):
            st.caption(tr("Ogni scenario usa il proprio totale. Nascondere una serie non cambia il denominatore. Un totale nullo non ha una quota definita."))
    return value == "relative"


def temporal_controls(meta: dict, key: str, start: int) -> tuple[str, str, str]:
    basis = meta.get("time_basis")
    if not basis:
        return "native", meta["unit"], ""
    if basis == "stock":
        labels = {"native": meta.get("stock_label", "Capacità totale installata"),
                  "annual": meta.get("annual_label", "Variazione annua")}
    else:
        labels = {"native": "Valori annui", "cumulative": f"Cumulati dal {start}"}
    display_labels = {value: tr("Cumulati dal {year}", year=start) if value == "cumulative" else tr(label)
                      for value, label in labels.items()}
    mode = st.segmented_control(tr("Vista temporale"), options=list(labels),
                                format_func=display_labels.get, default="native",
                                key=f"{key}_time_view") or "native"
    unit = meta["unit"]
    note = ""
    if basis == "stock" and mode == "annual":
        unit += "/anno"
        note = ("Il punto dell’anno t indica la variazione tra t e t+1. "
                "L’ultimo anno non è disponibile senza il punto successivo.")
    elif mode == "cumulative":
        note = tr("Somma dei valori annui dal {start} fino all’anno indicato, incluso.", start=start)
    return mode, unit, note


@st.cache_data(show_spinner=False, max_entries=3)
def historical_series(source: str, relative: bool = False) -> pd.DataFrame:
    if source == "pv_production":
        if relative:
            return pd.DataFrame()  # No observed self-consumption/export split.
        raw = pd.read_csv(ROOT / "content/system_dynamics/plots_data/Historical electricity production.csv", sep=";")
        return raw.set_index("year")[["Fotovoltaico"]].rename(columns={"Fotovoltaico": "Produzione"})
    filename = "EVinput.csv" if source == "vehicle_adoptions" else "PVinput.csv"
    raw = pd.read_csv(ROOT / "Vensim" / filename, index_col=0)
    if source == "pv_capacity":
        rows = {'"Capacity PV 30 - 100 kW"': "30–100 kW",
                '"Capacity PV > 100 kW"': "> 100 kW"}
    elif source == "vehicle_adoptions":
        types = ("Petrol", "Diesel", "PetrolHEV", "PetrolPHEV", "DieselHEV", "DieselPHEV", "BEV")
        if relative:
            names = [f"Adoption Vehicles[{kind}]" for kind in types]
            full = available_history(raw, names)
            return relative_series(full)[["Adoption Vehicles[BEV]"]].rename(columns={"Adoption Vehicles[BEV]": "BEV"})
        rows = {"Adoption Vehicles[BEV]": "BEV"}
    else:
        raise ValueError(f"Fonte storica sconosciuta: {source}")
    result = available_history(raw, list(rows))
    return result.rename(columns=rows)


def add_historical_options(options: dict, historical: pd.DataFrame, *, net_change=False) -> None:
    """Punti storici distinti dalle linee di scenario; nessun prolungamento."""
    from echarts_charts import place_line_legend
    from ui_colors import line_color
    labels = [s["name"] for s in options["series"] if not s["name"].endswith(" (Base)")]
    for label in historical:
        if label not in labels:
            continue
        suffix = "storico: incremento netto" if net_change else "storico"
        options["series"].append({
            "name": f"{label} ({suffix})", "type": "scatter", "symbol": "diamond",
            "symbolSize": 9, "z": 5,
            "itemStyle": {"color": line_color(labels.index(label), label, n=len(labels)),
                          "borderColor": "#333333", "borderWidth": 1},
            "data": [None if pd.isna(v) else float(v) for v in historical[label]],
        })
    place_line_legend(options)


def render_calibration_reference(technology: str, *, key: str) -> None:
    """Le adozioni hanno un proprio grafico, non si sovrappongono ai MW."""
    if not st.checkbox(tr("Mostra calibrazione — {technology}", technology=tr(technology)), key=f"{key}_calibration"):
        return
    from sd_explainer.loaders import load_calibration_series
    from echarts_charts import build_line_options, render_echarts
    years, series = load_calibration_series(technology)
    frame = pd.DataFrame(series, index=[int(y) for y in years])
    mode, _, note = temporal_controls({"time_basis": "flow", "unit": "edifici/anno"},
                                      f"{key}_calibration", int(frame.index.min()))
    frame = transform_series(frame, "flow", mode)
    count_unit = "veicoli" if technology == "Veicoli elettrici" else "edifici"
    unit = count_unit if mode == "cumulative" else count_unit + "/anno"
    chart_series = {name: [None if pd.isna(v) else float(v) for v in frame[name]]
                    for name in frame}
    options = build_line_options(list(frame.index), chart_series, unit=unit)
    options["series"][0].update(type="bar", smooth=False)
    options["series"][1]["name"] = "Simulato (corsa di calibrazione)"
    options["legend"]["data"] = [s["name"] for s in options["series"]]
    st.markdown(tr("**Calibrazione delle adozioni — {technology}** ({unit})", technology=tr(technology), unit=chart_text(unit)))
    st.caption(tr("Osservato: input del modello. Simulato: corsa di calibrazione della "
               "documentazione, distinta dallo scenario selezionato. "
               "Il confronto è sul numero di adozioni, non sulla potenza installata."))
    if note:
        st.caption(tr(note))
    render_echarts(options, chart_key=f"{key}_calibration_chart", height=350)
