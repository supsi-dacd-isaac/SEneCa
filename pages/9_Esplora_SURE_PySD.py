"""Esplora scenari SURE — backend PySD.

Sidebar con gli stessi input delle pagine Risultati, raggruppati per sezione.
I risultati sono divisi in quattro sottopagine selezionabili, impaginate come le
pagine Risultati omonime.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parent.parent
PVBAT = PROJECT_DIR / "pv_batteries"
for p in (str(PROJECT_DIR), str(PVBAT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pysd_explore_config as cfg  # noqa: E402
importlib.reload(cfg)  # evita config stale se Streamlit tiene sys.modules
import sure_paths as paths  # noqa: E402
import sure_pysd as sp  # noqa: E402
importlib.reload(sp)
import elettricita_config as elec_cfg  # noqa: E402
import explore_results_charts as erc  # noqa: E402
import section_ui_hourly as _sui_h  # noqa: E402
importlib.reload(elec_cfg)
importlib.reload(_sui_h)
importlib.reload(erc)
from explore_results_charts import (  # noqa: E402
    df_has_results_columns,
    render_elettricita_from_pysd,
    render_pv_topic_sections,
    render_risanamento_section,
    render_veicoli_section,
)
from section_ui import render_section_picker  # noqa: E402
import risanamento_config as ris_cfg  # noqa: E402
import veicoli_config as vei_cfg  # noqa: E402

# Sottopagine dei risultati, con gli stessi titoli delle pagine pre-calcolate.
SUBPAGE_PV = "PV e Batterie"
SUBPAGE_RIS = "Riscaldamento e Risanamento"
SUBPAGE_VEI = "Veicoli"
SUBPAGE_ELEC = "Elettricità"
SUBPAGES = [SUBPAGE_PV, SUBPAGE_RIS, SUBPAGE_VEI, SUBPAGE_ELEC]
EXPLORE_SECTION_KEY = "explore_section"

# Bump per invalidare @st.cache_resource dopo cambio OUTPUTS / prune
ENGINE_CACHE_VERSION = "results_charts_v2_elec"

DELTA_COLS = [
    "PV residential power by Type[SFH]",
    "PV residential power by Type[DFH]",
    "PV residential power by Type[MFH]",
    "Levy Evolution",
    "Annual CO2 emissions",
    "Cumulative CO2 emissions",
    "Specific net final consumption",
    "Specific final consumption",
    "Vehicles by type[BEV]",
]
YEARS = range(2011, 2051)


def _params_fingerprint(params: dict[str, float]) -> str:
    blob = json.dumps({k: round(float(v), 8) for k, v in sorted(params.items())},
                      sort_keys=True)
    return hashlib.md5(blob.encode()).hexdigest()


# =============================================================
# ENGINE
# =============================================================
def default_variant() -> str:
    """Traduzione piu' recente: le precedenti restano in Vensim/ solo per confronto."""
    return paths.variant()


@st.cache_resource(show_spinner="Caricamento e potatura del modello PySD (una tantum)...")
def get_engine(variant: str, _version: str = ENGINE_CACHE_VERSION):
    paths.set_variant(variant)
    if not paths.pysd_py().exists():
        raise FileNotFoundError(
            f"Modello PySD tradotto non trovato: {paths.pysd_py()}. "
            "Esegui la pipeline di traduzione prima di avviare l'app."
        )
    model = sp.load_model(prune=True)
    const = sp.build_constant_params(model)
    return {"model": model, "const": const, "lock": threading.Lock()}


@st.cache_data(show_spinner=False)
def run_live(variant: str, params_fp: str, params_json: str, _engine) -> pd.DataFrame:
    params = json.loads(params_json)
    with _engine["lock"]:
        df = sp.run_scenario(
            _engine["model"],
            scenario_inputs=params,
            const_params=_engine["const"],
            timestamps=YEARS,
            flatten=True,
        )
    df.index = pd.Index(df.index, name="Time")
    return df


def get_scenario(ui: dict[str, float], variant: str) -> tuple[pd.DataFrame, str]:
    pysd_params = cfg.ui_to_pysd_params(ui)

    with st.spinner(
        "Simulazione PySD live (può richiedere alcuni minuti con tutti gli output "
        "Risultati)..."
    ):
        fp = _params_fingerprint(pysd_params)
        df = run_live(variant, fp, json.dumps(pysd_params, sort_keys=True),
                      get_engine(variant))
    return df, "live"


# =============================================================
# SIDEBAR
# =============================================================
def render_sidebar() -> tuple[dict[str, float], bool, str]:
    variant = default_variant()
    paths.set_variant(variant)

    st.sidebar.header("Input di policy")
    n_ok = sum(1 for i in cfg.ALL_INPUTS if i.supported)
    n_tot = len(cfg.ALL_INPUTS)
    st.sidebar.caption(
        f"Sezioni allineate alle pagine Simulazioni SEneCa. "
        f"**{n_ok}/{n_tot}** leve applicate 1:1 come costanti in "
        f"`{paths.pysd_py().name}`."
    )
    ui: dict[str, float] = {}

    for section_title, inputs in cfg.SECTIONS:
        with st.sidebar.expander(section_title, expanded=(section_title.startswith("1."))):
            for inp in inputs:
                key = f"exp_{inp.name}"
                help_txt = inp.note or None
                label = inp.label
                if inp.unit:
                    label = f"{label} ({inp.unit})" if inp.unit != "-" else label

                if not inp.supported:
                    if inp.choice_labels:
                        st.selectbox(
                            label,
                            options=[inp.choice_labels[v] for v in inp.values
                                     if v in inp.choice_labels],
                            index=list(inp.values).index(inp.default)
                            if inp.default in inp.values else 0,
                            disabled=True,
                            help=help_txt or "Non disponibile in PySD",
                            key=key,
                        )
                    elif inp.binary:
                        st.radio(
                            label, ("No", "Sì"),
                            index=int(inp.default),
                            horizontal=True,
                            disabled=True,
                            help=help_txt or "Non disponibile in PySD",
                            key=key,
                        )
                    else:
                        scale = inp.scale
                        st.select_slider(
                            label,
                            options=inp.values,
                            value=inp.default,
                            format_func=lambda x, scale=scale: f"{x * scale:g}",
                            disabled=True,
                            help=help_txt or "Non disponibile in PySD",
                            key=key,
                        )
                    ui[inp.name] = float(inp.default)
                    continue

                if inp.choice_labels:
                    labels = [inp.choice_labels[v] for v in inp.values
                              if v in inp.choice_labels]
                    inv = {inp.choice_labels[v]: v for v in inp.values
                           if v in inp.choice_labels}
                    default_label = inp.choice_labels.get(
                        inp.default, labels[0] if labels else "")
                    idx = labels.index(default_label) if default_label in labels else 0
                    chosen = st.selectbox(
                        label, options=labels, index=idx,
                        help=help_txt, key=key,
                    )
                    ui[inp.name] = float(inv[chosen])
                elif inp.binary:
                    choice = st.radio(
                        label, ("No", "Sì"),
                        index=int(inp.default),
                        horizontal=True,
                        help=help_txt, key=key,
                    )
                    ui[inp.name] = 1.0 if choice == "Sì" else 0.0
                else:
                    scale = inp.scale
                    ui[inp.name] = float(st.select_slider(
                        label,
                        options=inp.values,
                        value=inp.default,
                        format_func=lambda x, scale=scale: f"{x * scale:g}",
                        help=help_txt, key=key,
                    ))

    if st.sidebar.button("Ripristina scenario base", width="stretch"):
        for inp in cfg.ALL_INPUTS:
            key = f"exp_{inp.name}"
            if inp.choice_labels and inp.default in inp.choice_labels:
                st.session_state[key] = inp.choice_labels[inp.default]
            elif inp.binary:
                st.session_state[key] = "Sì" if inp.default else "No"
            else:
                st.session_state[key] = inp.default
        st.rerun()

    run_clicked = st.sidebar.button(
        "Simula e confronta vs base", type="primary", width="stretch",
    )
    return ui, run_clicked, variant


# =============================================================
# PLOTS
# =============================================================
def _delta_table(base_df: pd.DataFrame, user_df: pd.DataFrame) -> pd.DataFrame:
    year = 2050.0
    rows = []
    for col in DELTA_COLS:
        if col not in base_df.columns or col not in user_df.columns:
            continue
        b = float(base_df.loc[year, col]) if year in base_df.index else float("nan")
        u = float(user_df.loc[year, col]) if year in user_df.index else float("nan")
        d = u - b
        rel = d / b if abs(b) > 1e-12 else float("nan")
        rows.append({
            "Variabile": col,
            "Base 2050": b,
            "Scelta 2050": u,
            "Delta": d,
            "Delta %": rel * 100.0,
        })
    return pd.DataFrame(rows)


def render_results(ui: dict[str, float], user_df: pd.DataFrame, base_df: pd.DataFrame,
                   src_user: str, src_base: str):
    st.subheader("Scenario scelto vs scenario base")
    st.caption(f"**Scelta** ({src_user}): {cfg.format_ui_summary(ui)}")
    st.caption(
        f"**Base** ({src_base}): valori BASE delle pagine Simulazioni SEneCa (mappati su PySD). "
        "Linee tratteggiate = Base (stesso stile delle sezioni Simulazioni SEneCa)."
    )

    # Sottopagine al posto delle tab: ogni blocco impagina i risultati come la
    # pagina omonima, selettori interni inclusi.
    active = render_section_picker(SUBPAGES, key=EXPLORE_SECTION_KEY)
    st.subheader(active)

    if active == SUBPAGE_PV:
        if not df_has_results_columns(user_df):
            st.warning(
                "Colonne Risultati assenti dalla simulazione: la traduzione PySD "
                "caricata non contiene le variabili di questa sezione."
            )
        else:
            render_pv_topic_sections(
                user_df, df_base=base_df, section_selector=True,
            )
    elif active == SUBPAGE_RIS:
        render_risanamento_section(
            user_df, ris_cfg.OUTPUTS, ris_cfg.FINAL_YEAR, df_base=base_df,
            explanations=ris_cfg.EXPLANATIONS,
        )
    elif active == SUBPAGE_VEI:
        render_veicoli_section(
            user_df, vei_cfg.OUTPUTS, vei_cfg.OUTPUT_LAYOUT, vei_cfg.FINAL_YEAR,
            df_base=base_df,
        )
    else:
        render_elettricita_from_pysd(
            user_df, df_base_wide=base_df, section_selector=True,
        )

    st.divider()
    st.markdown("**Differenza al 2050** (indicatori chiave)")
    delta = _delta_table(base_df, user_df)
    if not delta.empty:
        shown = delta.copy()
        for col in ("Base 2050", "Scelta 2050", "Delta"):
            shown[col] = shown[col].map(lambda x: f"{x:.4g}")
        shown["Delta %"] = shown["Delta %"].map(lambda x: f"{x:.2f}")
        st.dataframe(shown, width="stretch", hide_index=True)
    else:
        st.caption("Nessuna colonna delta disponibile in questo DataFrame.")

    with st.expander("Tabella completa scenario scelto"):
        st.dataframe(user_df, width="stretch")
        st.download_button(
            "Scarica CSV scenario scelto",
            user_df.to_csv().encode("utf-8"),
            file_name="scenario_scelto.csv",
            mime="text/csv",
        )


# =============================================================
# MAIN
# =============================================================
st.title("Simulazione in tempo reale")
st.caption(
    f"Simulazione live con {len(sp.OUTPUTS)} output Risultati "
    "(PV / Risanamento / Veicoli / Elettricità); tipicamente alcuni minuti "
    "(il sottografo orario allunga la run)."
)

ui, run_clicked, variant = render_sidebar()

if run_clicked:
    base_ui = cfg.base_ui_values()
    user_df, src_user = get_scenario(ui, variant)
    base_df, src_base = get_scenario(base_ui, variant)
    st.session_state["exp_user_df"] = user_df
    st.session_state["exp_base_df"] = base_df
    st.session_state["exp_ui"] = ui
    st.session_state["exp_src_user"] = src_user
    st.session_state["exp_src_base"] = src_base

if "exp_user_df" in st.session_state:
    render_results(
        st.session_state["exp_ui"],
        st.session_state["exp_user_df"],
        st.session_state["exp_base_df"],
        st.session_state.get("exp_src_user", ""),
        st.session_state.get("exp_src_base", ""),
    )
else:
    st.info(
        "Imposta gli input nella barra laterale (sezioni 1–4) e premi "
        "**Simula e confronta vs base**. I grafici (incl. Elettricità oraria) "
        "appaiono nelle quattro sottopagine allineate alle pagine Simulazioni SEneCa. "
        "Se hai risultati in cache da prima dell'aggiornamento, rilancia la simulazione."
    )
