"""Viste temporali e riferimenti storici, senza modificare le traiettorie."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
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


def temporal_controls(meta: dict, key: str, start: int) -> tuple[str, str, str]:
    basis = meta.get("time_basis")
    if not basis:
        return "native", meta["unit"], ""
    if basis == "stock":
        labels = {"native": meta.get("stock_label", "Capacità totale installata"),
                  "annual": meta.get("annual_label", "Variazione annua")}
    else:
        labels = {"native": "Valori annui", "cumulative": f"Cumulati dal {start}"}
    mode = st.segmented_control("Vista temporale", options=list(labels),
                                format_func=labels.get, default="native",
                                key=f"{key}_time_view") or "native"
    unit = meta["unit"]
    note = ""
    if basis == "stock" and mode == "annual":
        unit += "/anno"
        note = ("Il punto dell’anno t indica la variazione tra t e t+1. "
                "L’ultimo anno non è disponibile senza il punto successivo.")
    elif mode == "cumulative":
        note = f"Somma dei valori annui dal {start} fino all’anno indicato, incluso."
    return mode, unit, note


@st.cache_data(show_spinner=False, max_entries=3)
def historical_series(source: str) -> pd.DataFrame:
    if source == "pv_production":
        raw = pd.read_csv(ROOT / "content/system_dynamics/plots_data/Historical electricity production.csv", sep=";")
        return raw.set_index("year")[["Fotovoltaico"]].rename(columns={"Fotovoltaico": "Produzione"})
    filename = "EVinput.csv" if source == "vehicle_adoptions" else "PVinput.csv"
    raw = pd.read_csv(ROOT / "Vensim" / filename, index_col=0)
    if source == "pv_capacity":
        rows = {'"Capacity PV 30 - 100 kW"': "30–100 kW",
                '"Capacity PV > 100 kW"': "> 100 kW"}
    elif source == "vehicle_adoptions":
        rows = {c: c[len("Adoption Vehicles["):-1] for c in raw.index
                if c.startswith("Adoption Vehicles[")}
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
    if not st.checkbox(f"Mostra calibrazione — {technology}", key=f"{key}_calibration"):
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
    st.markdown(f"**Calibrazione delle adozioni — {technology}** ({unit})")
    st.caption("Osservato: input del modello. Simulato: corsa di calibrazione della "
               "documentazione, distinta dallo scenario selezionato. "
               "Il confronto è sul numero di adozioni, non sulla potenza installata.")
    if note:
        st.caption(note)
    render_echarts(options, chart_key=f"{key}_calibration_chart", height=350)
