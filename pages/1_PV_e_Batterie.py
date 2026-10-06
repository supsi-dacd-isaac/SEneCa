"""Pagina Streamlit - Sezione "PV e Batterie decentralizzate".

Serve all'istante le 486 combinazioni pre-calcolate (precompute_pv_batteries.py):
6 slider discreti -> traiettorie/valori 2050 degli output + misure di equity GMD.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
PVBAT = ROOT / "pv_batteries"
for p in (str(ROOT), str(PVBAT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pv_batteries_config as _cfg  # noqa: E402
importlib.reload(_cfg)
from pv_batteries_config import (  # noqa: E402
    BASE_SCENARIO, BINARY_INPUTS, BINARY_LABELS, FINAL_YEAR,
    GMD_SPEC, INPUT_GRID, INPUT_META, INPUT_ORDER,
)
import explore_results_charts as _erc  # noqa: E402
import gmd as _gmd  # noqa: E402
import section_ui as _section_ui  # noqa: E402
import echarts_charts as _echarts_charts  # noqa: E402
import section_store as _section_store  # noqa: E402
importlib.reload(_gmd)
importlib.reload(_section_ui)
importlib.reload(_echarts_charts)
importlib.reload(_section_store)
importlib.reload(_erc)
from explore_results_charts import (  # noqa: E402
    _LEGACY_PV_CAPACITY_BASES,
    match_cols,
    render_pv_topic_sections as render_topic_sections,
)
from gmd import gmd_bounds_for_spec, scale_gmd_equity  # noqa: E402
from section_ui import (  # noqa: E402
    GMD_DISPLAY_CAPTION,
    fmt_scaled_gmd,
    render_kpi_radar,
)
from section_store import (  # noqa: E402
    base_combo_key, combo_key, load_gmd_store, load_traj_store,
)

@st.cache_resource(show_spinner="Caricamento scenari pre-calcolati...")
def _traj(section: str):
    return load_traj_store(_cfg)


@st.cache_resource(show_spinner=False)
def _gmd(section: str):
    return load_gmd_store(_cfg)


def total_pv_power_mw(df: pd.DataFrame, year: int) -> float | None:
    if year not in df.index:
        return None
    res_cols = match_cols(df, "PV residential power by Type")
    if not res_cols:
        return None
    res = df.loc[year, res_cols]
    if res.isna().all():
        return None
    nr_kw = sum(
        float(df.loc[year, base])
        for base in _LEGACY_PV_CAPACITY_BASES
        if base in df.columns and pd.notna(df.loc[year, base])
    )
    return float(res.sum()) + nr_kw / 1000.0


def total_battery_mwh(df: pd.DataFrame, year: int) -> float | None:
    cols = match_cols(df, "Total Battery capacity District")
    if not cols or year not in df.index:
        return None
    row = df.loc[year, cols]
    if row.isna().all():
        return None
    return float(row.sum())


def avg_annual_cost_chf(df: pd.DataFrame, year: int) -> float | None:
    cols = match_cols(df, "Average electricity and heating and retrofit cost")
    if not cols or year not in df.index:
        return None
    val = df.loc[year, cols[0]]
    return None if pd.isna(val) else float(val)


def _fmt_metric(value: float | None, unit: str, *, decimals: int = 0) -> str:
    if value is None:
        return "n/d"
    return f"{value:.{decimals}f} {unit}"


def _pct_delta_vs_base(cur: float | None, base: float | None) -> str | None:
    if cur is None or base is None:
        return None
    if base == 0:
        if cur == 0:
            return "0% vs Base"
        return None
    pct = (cur - base) / base * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}% vs Base"


def render_summary_metrics(
    df: pd.DataFrame,
    gmd_store: dict[str, dict],
    key: str,
    *,
    year: int,
    gmd_bounds: dict[str, tuple[float, float]],
    df_base: pd.DataFrame | None = None,
    base_key: str | None = None,
) -> None:
    """Indicatori principali al 2050: PV, batterie, costo, GMD levy/cost."""
    gmd_row = gmd_store.get(key, {})
    gmd_base_row = gmd_store.get(base_key, {}) if base_key else {}

    pv = total_pv_power_mw(df, year)
    bat = total_battery_mwh(df, year)
    cost = avg_annual_cost_chf(df, year)
    gmd_levy = scale_gmd_equity(
        gmd_row.get("gmd_levy"), *gmd_bounds["gmd_levy"]
    )
    gmd_cost = scale_gmd_equity(
        gmd_row.get("gmd_cost"), *gmd_bounds["gmd_cost"]
    )

    pv_base = total_pv_power_mw(df_base, year) if df_base is not None else None
    bat_base = total_battery_mwh(df_base, year) if df_base is not None else None
    cost_base = avg_annual_cost_chf(df_base, year) if df_base is not None else None
    gmd_levy_base = (
        scale_gmd_equity(gmd_base_row.get("gmd_levy"), *gmd_bounds["gmd_levy"])
        if gmd_base_row else None
    )
    gmd_cost_base = (
        scale_gmd_equity(gmd_base_row.get("gmd_cost"), *gmd_bounds["gmd_cost"])
        if gmd_base_row else None
    )

    items = (
        ("Potenza PV totale", _fmt_metric(pv, "MW"), pv, pv_base),
        ("Capacità batterie totale", _fmt_metric(bat, "MWh"), bat, bat_base),
        ("Costo medio annuale", _fmt_metric(cost, "CHF"), cost, cost_base),
        ("Equità levy (GMD)", fmt_scaled_gmd(gmd_levy), gmd_levy, gmd_levy_base),
        ("Equità costo (GMD)", fmt_scaled_gmd(gmd_cost), gmd_cost, gmd_cost_base),
    )
    cols = st.columns(len(items))
    for col, (label, display, value, value_base) in zip(cols, items, strict=True):
        with col:
            with st.container(border=True):
                st.metric(
                    label, display, delta=_pct_delta_vs_base(value, value_base),
                    help=GMD_DISPLAY_CAPTION if "Equità" in label else None,
                )

    render_kpi_radar(
        [(label, value, value_base) for label, _, value, value_base in items],
        chart_key=f"kpi_radar_{key}",
    )


def _format_input_value(name: str, value: float) -> str:
    if name in BINARY_INPUTS:
        return "Sì" if value == 1.0 else "No"
    return f"{value:g}"


def _render_binary_input(label: str, *, default: float = 0.0) -> float:
    default_label = "Sì" if default == 1.0 else "No"
    selected = st.segmented_control(
        label,
        options=list(BINARY_LABELS),
        default=default_label,
    )
    return 1.0 if selected == "Sì" else 0.0


st.title("PV e Batterie decentralizzate")

store = _traj("pv_batteries")
gmd_store = _gmd("pv_batteries")

if not store:
    st.warning(
        "Nessuno scenario pre-calcolato trovato. Esegui "
        "`pv_batteries/precompute_pv_batteries.py` per popolare lo store."
    )
    st.stop()

with st.sidebar:
    st.header("Scenario selezionato")
    values = []
    for name in INPUT_ORDER:
        meta = INPUT_META[name]
        opts = INPUT_GRID[name]
        label = f"{meta['label']}" + (f" ({meta['unit']})"
                                      if meta["unit"] != "-" else "")
        if name in BINARY_INPUTS:
            val = _render_binary_input(label, default=opts[0])
        else:
            val = st.select_slider(label, options=opts, value=opts[0],
                                   format_func=lambda x: f"{x:g}")
        values.append(val)

    compare_base = st.checkbox("Confronta con scenario Base", value=False)
    with st.expander("Scenario Base"):
        for name in INPUT_ORDER:
            imeta = INPUT_META[name]
            base_val = BASE_SCENARIO[name]
            if name in BINARY_INPUTS:
                st.markdown(
                    f"- {imeta['label']}: **{_format_input_value(name, base_val)}**"
                )
            else:
                unit = f" {imeta['unit']}" if imeta["unit"] != "-" else ""
                st.markdown(f"- {imeta['label']}: `{base_val:g}`{unit}")

key = combo_key(values)
base_key = base_combo_key(_cfg)

if key not in store:
    st.warning(
        "Questa combinazione non e' ancora disponibile nello store "
        "(il pre-calcolo potrebbe essere ancora in corso). Riprova piu' tardi."
    )
    st.stop()

df = store[key]

df_base: pd.DataFrame | None = None
compare_gmd_key: str | None = None
if compare_base:
    if key == base_key:
        st.info("Scenario identico al Base.")
    elif base_key not in store:
        st.warning("Scenario Base non disponibile nello store.")
    else:
        df_base = store[base_key]
        compare_gmd_key = base_key


# Alcuni scenari estremi (max incentivi PV + FiT + comunità energetica) non
# convergono nel modello Vensim e la simulazione si ferma prima del 2050.
sim_incomplete = bool(df.loc[FINAL_YEAR].isna().all())
if sim_incomplete:
    last_ok = int(df.dropna(how="all").index.max())
    st.warning(
        f"Per questa combinazione (incentivi estremi) il modello Vensim non "
        f"converge fino al {FINAL_YEAR}: la simulazione si ferma al {last_ok}. "
        f"I valori al {FINAL_YEAR} e le misure di equity non sono disponibili."
    )

KPI_EXPLANATION = f"""
Tutti gli indicatori sono riferiti al **{FINAL_YEAR}**; la variazione percentuale sotto
ogni valore è il confronto con lo scenario Base.

- **Potenza PV totale** — potenza fotovoltaica installata sul territorio, somma degli
  impianti residenziali e di quelli non residenziali di ogni taglia.
- **Capacità batterie totale** — capacità di accumulo installata, sommata sugli otto
  distretti.
- **Costo medio annuale** — spesa media di una famiglia per elettricità, riscaldamento
  e risanamento dell'edificio.

### Gli indici di equità

I due indici di equità misurano **quanto diversamente il costo della transizione ricade
sulle famiglie**, non quanto è alto. Partono dalla *Gini Mean Difference* pesata,
cioè la differenza media in valore assoluto fra tutte le coppie di archetipi di
famiglia, pesata per quante famiglie rappresenta ciascun archetipo:

$$\\mathrm{{GMD}} = \\frac{{\\sum_i \\sum_j w_i w_j\\, |x_i - x_j|}}{{2\\,W^2}}$$

Vale zero quando tutti gli archetipi sopportano esattamente lo stesso onere, e cresce
via via che le situazioni divergono.

- **Equità levy** — la grandezza $x$ è il saldo fra supplementi pagati e incentivi
  ricevuti da ciascun archetipo. Risponde alla domanda: chi finanzia gli incentivi e
  chi invece li incassa?
- **Equità costo** — la grandezza $x$ è il costo annuo totale per energia e risanamento
  di ciascun archetipo.

**Come leggere il numero.** Il GMD grezzo è in CHF e poco interpretabile da solo, quindi
viene riscalato su una scala da 0 a 1 usando il valore minimo e massimo osservati
**sull'intero store degli scenari precalcolati**: 1 identifica lo scenario più equo
fra quelli disponibili, 0 il meno equo. È quindi un indice **relativo** al ventaglio di
scenari, non una misura assoluta di equità: un valore di 0.5 significa "a metà strada
fra lo scenario migliore e quello peggiore", e i valori cambierebbero se si cambiasse
la griglia degli scenari.
"""

# --- Indicatori principali (2050) -------------------------------------
st.subheader(f"Indicatori principali ({FINAL_YEAR})")
with st.expander("Cosa misurano questi indicatori"):
    st.markdown(KPI_EXPLANATION)
gmd_bounds = gmd_bounds_for_spec(gmd_store, GMD_SPEC)
metrics_base_key = base_key if key != base_key else None
metrics_df_base = store.get(base_key) if metrics_base_key else None
render_summary_metrics(
    df,
    gmd_store,
    key,
    year=FINAL_YEAR,
    gmd_bounds=gmd_bounds,
    df_base=metrics_df_base,
    base_key=metrics_base_key,
)

st.divider()

# --- Output per argomento ---------------------------------------------
render_topic_sections(df, df_base=df_base, section_selector=True)

with st.expander("Dati grezzi (traiettorie)"):
    st.dataframe(df, width="stretch")
    st.download_button(
        "Scarica CSV", df.to_csv().encode("utf-8"),
        file_name=f"pv_batterie_{key}.csv", mime="text/csv")
