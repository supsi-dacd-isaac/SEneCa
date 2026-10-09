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
WEIGHT_PREFIX = "expl_w_"
WEIGHT_MODE_KEY = "expl_weight_mode"
MODE_RELATIVE = "Pesi relativi"
MODE_ABSOLUTE = "Pesi assoluti"
TOP_N = 5
SUBPAGE_INSPECT = "Esplora un policy mix"
SUBPAGE_RANK = "Migliori policy mix"
SUBPAGES = [SUBPAGE_INSPECT, SUBPAGE_RANK]
SUBPAGE_KEY = "expl_subpage"


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


def _round_weight(value: float) -> float:
    """Tre cifre decimali: 0.125 resta 0.125 e coincide con lo step dello slider."""
    return round(min(max(float(value), 0.0), 1.0), 3)


def _raw_weights() -> dict[str, float]:
    return {
        key: _round_weight(st.session_state.get(f"{WEIGHT_PREFIX}{key}", 0.0))
        for key in cfg.KPI_ORDER
    }


def _store_weights(weights: dict[str, float]) -> None:
    for key, value in weights.items():
        st.session_state[f"{WEIGHT_PREFIX}{key}"] = _round_weight(value)


def _as_relative(weights: dict[str, float], anchor: str) -> dict[str, float]:
    """Scala i pesi perché sommino a 1 e assorbe l'arrotondamento sull'ancora."""
    cleaned = {key: max(float(value), 0.0) for key, value in weights.items()}
    total = sum(cleaned.values())
    if total <= 1e-12:
        even = 1.0 / len(cfg.KPI_ORDER)
        cleaned = {key: even for key in cfg.KPI_ORDER}
    else:
        cleaned = {key: value / total for key, value in cleaned.items()}
    rounded = {key: _round_weight(value) for key, value in cleaned.items()}
    drift = round(1.0 - sum(rounded.values()), 3)
    target = anchor if anchor in rounded else cfg.KPI_ORDER[-1]
    rounded[target] = _round_weight(rounded[target] + drift)
    drift = round(1.0 - sum(rounded.values()), 3)
    if drift:
        for key in cfg.KPI_ORDER:
            if key == target:
                continue
            adjusted = _round_weight(rounded[key] + drift)
            used = round(adjusted - rounded[key], 3)
            if used:
                rounded[key] = adjusted
                drift = round(drift - used, 3)
                if not drift:
                    break
    return rounded


def _init_weights() -> None:
    st.session_state.setdefault(WEIGHT_MODE_KEY, MODE_RELATIVE)
    even = 1.0 / len(cfg.KPI_ORDER)
    for key in cfg.KPI_ORDER:
        st.session_state.setdefault(f"{WEIGHT_PREFIX}{key}", _round_weight(even))


def _is_relative() -> bool:
    return st.session_state.get(WEIGHT_MODE_KEY, MODE_RELATIVE) == MODE_RELATIVE


def _renormalize(changed: str) -> None:
    weights = _raw_weights()
    if not _is_relative():
        _store_weights(weights)
        return
    new_val = _round_weight(weights[changed])
    others = [key for key in cfg.KPI_ORDER if key != changed]
    rest = 1.0 - new_val
    other_sum = sum(weights[key] for key in others)
    if other_sum <= 1e-12:
        share = rest / len(others) if others else 0.0
        scaled = {key: share for key in others}
    else:
        scale = rest / other_sum
        scaled = {key: weights[key] * scale for key in others}
    scaled[changed] = new_val
    _store_weights(_as_relative(scaled, changed))


def _on_mode_change() -> None:
    if _is_relative():
        anchor = cfg.KPI_ORDER[0]
        _store_weights(_as_relative(_raw_weights(), anchor))


def _reset_weights() -> None:
    even = 1.0 / len(cfg.KPI_ORDER)
    weights = {key: even for key in cfg.KPI_ORDER}
    _store_weights(_as_relative(weights, cfg.KPI_ORDER[0]))


def _current_weights() -> dict[str, float]:
    raw = _raw_weights()
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

    st.html(
        """
        <style>
        div.st-key-expl_policy_cards [data-testid="stMetricLabel"],
        div.st-key-expl_policy_cards [data-testid="stMetricLabel"] * {
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: unset !important;
            height: auto !important;
            max-height: none !important;
            line-height: 1.25 !important;
        }
        div.st-key-expl_policy_cards [data-testid="stMetricLabel"] label,
        div.st-key-expl_policy_cards [data-testid="stMetricLabel"] > div {
            display: flex !important;
            flex-wrap: wrap !important;
            align-items: flex-start !important;
        }
        </style>
        """
    )
    with st.container(key="expl_policy_cards"):
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
                        help=cfg.POLICY_META[name].get("help") or None,
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
            help=cfg.POLICY_META[name].get("help") or None,
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
        st.caption(
            f"{len(subset)} scenari di incertezza per il mix selezionato."
        )
        render_echarts(
            options,
            chart_key="expl_policy_boxplot",
            height=520,
        )


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
        st.segmented_control(
            "Modalità di assegnazione",
            options=[MODE_RELATIVE, MODE_ABSOLUTE],
            default=MODE_RELATIVE,
            key=WEIGHT_MODE_KEY,
            on_change=_on_mode_change,
            help=(
                "Pesi relativi: spostando uno slider gli altri si ricalibrano "
                "e la somma resta 1. Pesi assoluti: ogni slider cambia solo "
                "quel KPI."
            ),
        )
        if _is_relative():
            st.markdown(
                "Ogni indicatore è scalato da **0 (peggiore)** a **1 (migliore)** "
                "su tutte le simulazioni. I pesi sommano a **1**: spostando uno "
                "slider gli altri si ricalibrano."
            )
        else:
            st.markdown(
                "Ogni indicatore è scalato da **0 (peggiore)** a **1 (migliore)** "
                "su tutte le simulazioni. Ogni slider cambia solo quel KPI: "
                "gli altri restano fermi e la somma può essere diversa da 1. "
                "Lo score usa i pesi in proporzione tra loro."
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
                r"dove $S=50$. Nello score i pesi sono riportati a somma 1. "
                "I cinque mix con score più alto compaiono a destra e sotto."
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
                        step=0.001,
                        format="%.3g",
                        key=f"{WEIGHT_PREFIX}{key}",
                        help=spec["help"],
                        on_change=_renormalize,
                        args=(key,),
                    )
        raw_sum = sum(_raw_weights().values())
        st.caption(f"Somma dei pesi: **{raw_sum:.3g}**")
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
