"""Pagina Streamlit — Analisi esplorativa policy × incertezza.

I 6400 scenari sono pre-calcolati. L'utente assegna pesi ai KPI (somma = 1);
la pagina ricalcola lo score di ogni policy mix e mostra i 5 migliori.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
PVBAT = ROOT / "pv_batteries"
for p in (str(ROOT), str(PVBAT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import exploratory_config as cfg  # noqa: E402
importlib.reload(cfg)
import exploratory as expl  # noqa: E402
importlib.reload(expl)
import echarts_charts as _echarts  # noqa: E402
importlib.reload(_echarts)
from echarts_charts import (  # noqa: E402
    build_boxplot_options,
    build_multi_radar_options,
    build_stacked_bar_options,
    render_echarts,
)
from ui_colors import SUPSI_BLUE, SUPSI_SOFT_GRAY  # noqa: E402

WEIGHT_PREFIX = "expl_w_"
TOP_N = 5
SUBPAGE_INSPECT = "Esplora un policy mix"
SUBPAGE_RANK = "Migliori policy mix"
SUBPAGES = [SUBPAGE_INSPECT, SUBPAGE_RANK]
SUBPAGE_KEY = "expl_subpage"
INSPECT_LAST_PID_KEY = "expl_inspect_last_pid"
INSPECT_LAST_OPTIONS_KEY = "expl_inspect_last_options"


@st.cache_data(show_spinner="Caricamento delle 6400 simulazioni...")
def _load_kpis(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)


@st.cache_data(show_spinner="Caricamento simulazioni parziali...")
def _load_rows(row_dir: str, signature: tuple) -> pd.DataFrame:
    files = sorted(Path(row_dir).glob("w*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(fp) for fp in files], ignore_index=True)


def _load_store() -> pd.DataFrame:
    if cfg.CONSOLIDATED_KPIS.exists():
        return _load_kpis(str(cfg.CONSOLIDATED_KPIS))
    part_dir = cfg.STORE_DIR / "parts"
    if not part_dir.exists():
        return pd.DataFrame()
    files = list(part_dir.glob("w*.parquet"))
    if not files:
        return pd.DataFrame()
    signature = tuple(
        (fp.name, int(fp.stat().st_mtime), int(fp.stat().st_size))
        for fp in sorted(files)
    )
    return _load_rows(str(part_dir), signature)


def _init_weights() -> None:
    even = 1.0 / len(cfg.KPI_ORDER)
    for key in cfg.KPI_ORDER:
        st.session_state.setdefault(f"{WEIGHT_PREFIX}{key}", even)


def _renormalize(changed: str) -> None:
    weights = {
        key: float(st.session_state.get(f"{WEIGHT_PREFIX}{key}", 0.0))
        for key in cfg.KPI_ORDER
    }
    new_val = min(max(weights[changed], 0.0), 1.0)
    others = [key for key in cfg.KPI_ORDER if key != changed]
    rest = 1.0 - new_val
    other_sum = sum(max(weights[key], 0.0) for key in others)
    if other_sum <= 1e-12:
        share = rest / len(others) if others else 0.0
        for key in others:
            st.session_state[f"{WEIGHT_PREFIX}{key}"] = share
    else:
        scale = rest / other_sum
        for key in others:
            st.session_state[f"{WEIGHT_PREFIX}{key}"] = max(weights[key], 0.0) * scale
    st.session_state[f"{WEIGHT_PREFIX}{changed}"] = new_val


def _reset_weights() -> None:
    even = 1.0 / len(cfg.KPI_ORDER)
    for key in cfg.KPI_ORDER:
        st.session_state[f"{WEIGHT_PREFIX}{key}"] = even


def _current_weights() -> dict[str, float]:
    raw = {
        key: float(st.session_state.get(f"{WEIGHT_PREFIX}{key}", 0.0))
        for key in cfg.KPI_ORDER
    }
    total = sum(raw.values())
    if total <= 0:
        even = 1.0 / len(cfg.KPI_ORDER)
        return {key: even for key in cfg.KPI_ORDER}
    return {key: val / total for key, val in raw.items()}


def _wrap_policy_label(label: str, max_chars: int = 18) -> str:
    """Spezza le etichette lunghe su due righe per l'asse del grafico."""
    if len(label) <= max_chars:
        return label
    parts = label.split()
    if len(parts) < 2:
        return label
    best = 1
    best_score = abs(len(" ".join(parts[:1])) - len(" ".join(parts[1:])))
    for i in range(1, len(parts)):
        score = abs(len(" ".join(parts[:i])) - len(" ".join(parts[i:])))
        if score < best_score:
            best, best_score = i, score
    return " ".join(parts[:best]) + "\n" + " ".join(parts[best:])


def _composition_chart(top: pd.DataFrame) -> None:
    shares = expl.policy_value_shares(top)
    categories = [_wrap_policy_label(cfg.POLICY_META[name]["label"])
                  for name in cfg.POLICY_ORDER]
    # Due serie: valore "alto"/attivo e valore "basso", in percentuale.
    high_vals: list[float] = []
    low_vals: list[float] = []
    high_labels: list[str] = []
    low_labels: list[str] = []
    for name in cfg.POLICY_ORDER:
        opts = cfg.POLICY_GRID[name]
        low, high = opts[0], opts[-1]
        share_map = shares.get(name, {})
        low_share = share_map.get(float(low), 0.0) * 100.0
        high_share = share_map.get(float(high), 0.0) * 100.0
        low_vals.append(round(low_share, 1))
        high_vals.append(round(high_share, 1))
        low_labels.append(cfg.format_policy_value(name, low))
        high_labels.append(cfg.format_policy_value(name, high))

    series = {
        "Valore basso / assente": low_vals,
        "Valore alto / presente": high_vals,
    }
    options = build_stacked_bar_options(
        categories, series, unit="%",
        series_order=["Valore alto / presente", "Valore basso / assente"],
    )
    for item in options["series"]:
        item["itemStyle"]["color"] = (
            SUPSI_BLUE if item["name"] == "Valore alto / presente"
            else SUPSI_SOFT_GRAY
        )
    options["xAxis"] = {"type": "value", "max": 100, "name": "% dei 5 migliori"}
    options["yAxis"] = {
        "type": "category",
        "data": categories,
        "inverse": True,
        "axisLabel": {
            "interval": 0,
            "width": 240,
            "overflow": "none",
            "hideOverlap": False,
        },
    }
    options["grid"] = {"left": 260, "right": "8%", "top": "8%", "bottom": "16%"}
    render_echarts(options, chart_key="expl_policy_shares", height=420)

    cards = st.columns(len(cfg.POLICY_ORDER))
    for col, name, high_lab, high_pct in zip(
        cards, cfg.POLICY_ORDER, high_labels, high_vals, strict=True,
    ):
        with col:
            with st.container(border=True):
                st.metric(
                    cfg.POLICY_META[name]["label"],
                    f"{high_pct:.0f}%",
                    delta=high_lab,
                    delta_color="off",
                )


RADAR_LABELS = {
    "gmd_levy": "Equità\nlevy",
    "gmd_tax": "Equità\ntassa CO₂",
    "gmd_cost": "Equità\ncosto",
    "avg_cost": "Costo\nfamiglia",
    "pv_production": "Produzione\nPV",
    "net_consumption": "Consumo\nnetto",
    "co2_cum": "Emissioni\nCO₂",
    "cantonal_spend": "Spesa\ncantonale",
}


def _boxplot_five(values) -> tuple[list[float], list[float]]:
    """Tukey: [min, Q1, mediana, Q3, max] e lista degli outlier."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return [0.0, 0.0, 0.0, 0.0, 0.0], []
    q1, med, q3 = np.percentile(arr, [25, 50, 75])
    iqr = q3 - q1
    fence_lo, fence_hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = arr[(arr >= fence_lo) & (arr <= fence_hi)]
    if inside.size == 0:
        inside = arr
    lo, hi = float(inside.min()), float(inside.max())
    outliers = [float(v) for v in arr if v < lo or v > hi]
    return [lo, float(q1), float(med), float(q3), hi], outliers


def _render_policy_selectors() -> dict[str, float]:
    values: dict[str, float] = {}
    for name in cfg.POLICY_ORDER:
        opts = cfg.POLICY_GRID[name]
        labels = [cfg.format_policy_value(name, val) for val in opts]
        chosen = st.segmented_control(
            cfg.POLICY_META[name]["label"],
            options=labels,
            default=labels[0],
            key=f"expl_pol_{name}",
        )
        chosen = chosen or labels[0]
        values[name] = float(opts[labels.index(chosen)])
    return values


def _render_inspect_mix(scaled: pd.DataFrame) -> None:
    st.subheader("Esplora un policy mix")
    st.markdown(
        "Scegli il livello di ciascuna leva: a destra vedi, per ogni KPI "
        "già scalato da **0 (peggiore)** a **1 (migliore)**, il range sugli "
        "scenari di incertezza."
    )
    col_pol, col_box = st.columns([1, 1.4])
    with col_pol:
        values = _render_policy_selectors()
    pid = cfg.policy_id_from_values(values)
    subset = scaled.loc[scaled["policy_id"] == pid]
    with col_box:
        if subset.empty:
            st.warning("Questo mix non è ancora nello store.")
            return
        categories = [RADAR_LABELS[key].replace("\n", " ") for key in cfg.KPI_ORDER]
        boxes: list[list[float]] = []
        outliers: list[list[float]] = []
        for i, key in enumerate(cfg.KPI_ORDER):
            five, outs = _boxplot_five(subset[f"{key}_s"])
            boxes.append(five)
            outliers.extend([i, v] for v in outs)
        options = build_boxplot_options(
            categories, boxes, unit="scalato (1 = migliore)",
            y_min=0.0, y_max=1.0, outliers=outliers,
        )
        options["animationDuration"] = 0
        options["animationDurationUpdate"] = 450
        options["animationEasingUpdate"] = "cubicOut"
        previous_options = None
        if st.session_state.get(INSPECT_LAST_PID_KEY) != pid:
            previous_options = st.session_state.get(INSPECT_LAST_OPTIONS_KEY)
        st.caption(
            f"{len(subset)} scenari di incertezza per il mix selezionato."
        )
        render_echarts(
            options,
            chart_key="expl_policy_boxplot",
            height=520,
            previous_options=previous_options,
            animate_initial=False,
        )
        st.session_state[INSPECT_LAST_PID_KEY] = pid
        st.session_state[INSPECT_LAST_OPTIONS_KEY] = options


def _render_best_mixes(scaled: pd.DataFrame) -> None:
    st.subheader("Migliori policy mix")
    st.markdown(
        "Modifica i **pesi**, cioè l'importanza relativa dei KPI, e vedi "
        f"quali sono i **{TOP_N} policy mix** con la prestazione media "
        "migliore considerando tutti gli scenari di incertezza. Più in "
        "basso appare la **composizione** di quei mix: quali leve "
        "singole risultano attive o al valore alto."
    )
    _init_weights()
    w = _current_weights()
    ranked = expl.score_policy_mixes(scaled, w)
    complete = ranked[ranked["n_samples"] >= cfg.N_SAMPLES]
    if not complete.empty:
        ranked = complete
    if ranked.empty:
        st.error("Impossibile calcolare lo score con i dati disponibili.")
        return
    top = expl.top_n_mixes(ranked, TOP_N)

    col_weights, col_radar = st.columns(2)
    with col_weights:
        st.subheader("Pesi dei KPI")
        st.markdown(
            "Ogni indicatore è scalato da **0 (peggiore)** a **1 (migliore)** "
            "su tutte le simulazioni. I pesi sommano a **1**: spostando uno "
            "slider gli altri si ricalibrano."
        )
        with st.expander("Come si calcola lo score"):
            st.markdown(
                "Per ogni simulazione il vettore dei KPI scalati viene moltiplicato "
                "per i pesi. Lo **score di un policy mix** è la media di questi "
                "valori sui 50 scenari di incertezza, tutti con lo stesso peso:"
            )
            st.latex(
                r"\mathrm{score}_p = \frac{1}{S}\sum_{s=1}^{S}\sum_{k} "
                r"w_k\,\tilde{x}_{p,s,k}"
            )
            st.markdown(
                r"dove $S=50$ e $\sum_k w_k = 1$. I cinque mix con score più alto "
                "compaiono a destra e sotto."
            )
        sub_left, sub_right = st.columns(2)
        mid = (len(cfg.KPI_ORDER) + 1) // 2
        for col, keys in (
            (sub_left, cfg.KPI_ORDER[:mid]),
            (sub_right, cfg.KPI_ORDER[mid:]),
        ):
            with col:
                for key in keys:
                    spec = cfg.KPI_SPEC[key]
                    st.slider(
                        spec["label"],
                        min_value=0.0,
                        max_value=1.0,
                        step=0.01,
                        key=f"{WEIGHT_PREFIX}{key}",
                        help=spec["help"],
                        on_change=_renormalize,
                        args=(key,),
                    )
        st.caption(f"Somma dei pesi: **{sum(w.values()):.2f}**")
        st.button("Ripristina pesi uguali", on_click=_reset_weights)

    with col_radar:
        st.subheader(f"Profilo dei {TOP_N} mix migliori")
        st.caption(
            "Ogni asse è un KPI scalato (1 = migliore). I poligoni usano la "
            "media dei 50 scenari di incertezza."
        )
        _top_radar(top)

    st.divider()
    st.subheader(f"Composizione dei {TOP_N} policy mix migliori")
    st.markdown(
        "Per ogni leva: che percentuale dei mix in classifica assume il valore "
        "alto/presente. Esempio: 100% su Comunità energetica significa che tutti e "
        f"{TOP_N} i migliori la attivano; 20% sugli incentivi cantonali PV "
        "significa che lo fa un mix su cinque."
    )
    _composition_chart(top)

    with st.expander("Tutti i 128 policy mix ordinati per score"):
        show = ranked.copy()
        show.insert(0, "Rank", range(1, len(show) + 1))
        for name in cfg.POLICY_ORDER:
            show[cfg.POLICY_META[name]["label"]] = [
                cfg.format_policy_value(name, float(v)) for v in show[name]
            ]
        keep = (
            ["Rank", "score", "score_std", "n_samples"]
            + [cfg.POLICY_META[n]["label"] for n in cfg.POLICY_ORDER]
        )
        pretty = show[keep].rename(columns={
            "score": "Score", "score_std": "σ score", "n_samples": "N scenari",
        })
        st.dataframe(pretty, width="stretch", hide_index=True)
        st.download_button(
            "Scarica classifica CSV",
            pretty.to_csv(index=False).encode("utf-8"),
            file_name="exploratory_ranking.csv",
            mime="text/csv",
        )


def _top_radar(top: pd.DataFrame) -> None:
    labels = [RADAR_LABELS[key] for key in cfg.KPI_ORDER]
    series: dict[str, list[float | None]] = {}
    order: list[str] = []
    for i, row in enumerate(top.to_dict("records"), start=1):
        name = f"#{i}"
        order.append(name)
        series[name] = [
            None if pd.isna(row[f"{key}_s"]) else float(row[f"{key}_s"])
            for key in cfg.KPI_ORDER
        ]
    options = build_multi_radar_options(
        labels, series, axis_max=1.0, series_order=order,
    )
    render_echarts(options, chart_key="expl_top_radar", height=560)


st.title("Policy mix e incertezza")
st.markdown(
    "Qui le **leve di policy** e i **parametri incerti** vengono mossi insieme: "
    "non si chiede quale mix vince in un futuro unico, ma quali restano "
    "interessanti quando il contesto può andare in direzioni diverse."
)

col_mix, col_unc, col_kpi = st.columns(3)
with col_mix.container(border=True):
    st.markdown("#### :material/tune: Policy mix")
    st.markdown(
        "Ogni mix è una combinazione di incentivi e regolamenti "
        "(PV, batterie, riscaldamento, risanamento, comunità energetica). "
        "Sono **7 leve su due livelli** ciascuna, per un totale di "
        "**128 policy mix** possibili."
    )
with col_unc.container(border=True):
    st.markdown("#### :material/casino: Incertezza")
    st.markdown(
        "Costi, domanda, tassi e vita utile delle tecnologie non sono noti "
        "con certezza. Lo stesso ventaglio di futuri plausibili viene "
        "applicato a **ogni** mix, così il confronto resta equo."
    )
with col_kpi.container(border=True):
    st.markdown("#### :material/analytics: Indicatori")
    st.markdown(
        "Per ogni combinazione di policy mix e scenario di incertezza "
        "si calcolano **8 KPI**: costi (famiglia e spesa cantonale), "
        "**equità distributiva** (levy, tassa CO₂, costo) ed **emissioni**, "
        "        insieme a produzione PV e consumo netto."
    )

st.session_state.setdefault(SUBPAGE_KEY, SUBPAGES[0])
choice = st.segmented_control(
    "Vista",
    SUBPAGES,
    key=SUBPAGE_KEY,
    label_visibility="collapsed",
)
active = choice or SUBPAGES[0]

df = _load_store()
expected = cfg.n_policy_mixes() * cfg.N_SAMPLES
if df.empty:
    st.warning(
        "Store dell'analisi esplorativa non trovato. Esegui "
        "`pv_batteries/precompute_exploratory.py` per popolare le 6400 simulazioni."
    )
    st.stop()
if len(df) < expected:
    st.info(
        f"Pre-calcolo in corso o incompleto: {len(df)}/{expected} simulazioni "
        "disponibili. Il ranking usa solo i mix già completi."
    )
    if st.button("Ricarica risultati"):
        st.cache_data.clear()
        st.rerun()

usable = df.dropna(subset=cfg.KPI_ORDER, how="any")
if usable.empty:
    st.error("Nessuna simulazione completa nello store.")
    st.stop()

scaled = expl.scale_kpis(usable)

if active == SUBPAGE_INSPECT:
    _render_inspect_mix(scaled)
else:
    _render_best_mixes(scaled)
