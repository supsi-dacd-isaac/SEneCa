"""Configurazione dell'analisi esplorativa policy × incertezza.

Sorgente: foglio "Exploratory analysis" di Input and Output Streamlit.xlsx.
7 leve a 2 livelli -> 128 policy mix; 17 parametri incerti campionati 50 volte.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
VPMX = ROOT / "Vensim" / "SURE.vpmx"
STORE_DIR = ROOT / "precomputed" / "exploratory"
SAMPLES_PATH = STORE_DIR / "uncertainty_samples.parquet"
CONSOLIDATED_KPIS = ROOT / "precomputed" / "exploratory_kpis.parquet"

SECTION = "exploratory"
RUN_NAME = "expl"
YEARS = range(2011, 2051)
FINAL_YEAR = 2050
CANTONAL_SPEND_START = 2025
N_SAMPLES = 50
SAMPLE_SEED = 20261004

# Interruttore del modello: attiva Cantonal PV support / Renewable heating
# incentives al posto di PV rebate cantonal e Grant share *.
EXPLORATORY_SWITCH = "Exploratory analysis"

# =============================================================
# POLICY (7 leve, ciascuna min/max -> 128 mix)
# =============================================================
POLICY_GRID: dict[str, list[float]] = {
    "Cantonal PV support": [0.0, 1.0],
    "Battery Rebate": [0.0, 0.3],
    "Renewable heating incentives": [0.0, 0.2],
    "Retrofit incentive input": [50.0, 100.0],
    "PV reg scenario": [0.0, 1.0],
    "MuKEn scenario": [0.0, 2.0],
    "Energy Community scenario": [0.0, 1.0],
}
POLICY_ORDER = list(POLICY_GRID.keys())

POLICY_META = {
    "Cantonal PV support": {
        "label": "Incentivi cantonali PV",
        "unit": "-",
        "kind": "binary",
    },
    "Battery Rebate": {
        "label": "Rimborso batterie",
        "unit": "-",
        "kind": "numeric",
    },
    "Renewable heating incentives": {
        "label": "Incentivi riscaldamento rinnovabile",
        "unit": "-",
        "kind": "numeric",
    },
    "Retrofit incentive input": {
        "label": "Incentivo risanamento",
        "unit": "CHF/m2",
        "kind": "numeric",
    },
    "PV reg scenario": {
        "label": "Obbligo PV nuovi edifici",
        "unit": "-",
        "kind": "binary",
    },
    "MuKEn scenario": {
        "label": "Regolamentazione riscaldamento",
        "unit": "-",
        "kind": "muken",
    },
    "Energy Community scenario": {
        "label": "Comunità energetica (RCP)",
        "unit": "-",
        "kind": "binary",
    },
}

MUKEN_LABELS: dict[float, str] = {
    0.0: "Nessuna",
    2.0: "MoPEc 2025",
}

# =============================================================
# INCERTEZZA (17 parametri, uniforme su [min, max])
# =============================================================
UNCERTAINTY_BOUNDS: dict[str, tuple[float, float]] = {
    "PV uncertain cost": (-0.2, 0.2),
    "PV uncertain remuneration": (-0.2, 0.2),
    "Retrofit uncertain cost": (-0.1, 0.1),
    "Interest rate uncertainty": (-0.3, 0.3),
    "Import price uncertainty": (-0.3, 1.0),
    "Battery uncertain cost": (-0.2, 0.2),
    "Construction rate uncertainty": (-0.2, 0.2),
    "Demolition rate uncertainty": (-0.2, 0.2),
    "Industry demand uncertainty": (-0.2, 0.2),
    "Tertiary demand uncertainty": (-0.2, 0.2),
    "Oil/gas lifetime uncertainty": (-0.2, 0.2),
    "Wood/pellet lifetime uncertainty": (-0.2, 0.2),
    "HP lifetime uncertainty": (-0.2, 0.2),
    "Oil/gas carrier cost uncertainty": (-0.2, 0.2),
    "Wood/pellet carrier cost uncertainty": (-0.2, 0.2),
    "HP cost uncertainty": (-0.3, 0.3),
    "HP efficiency uncertainty": (-0.2, 0.2),
}
UNCERTAINTY_ORDER = list(UNCERTAINTY_BOUNDS.keys())

# =============================================================
# KPI
# higher_is_better: True se un valore grezzo piu' alto e' preferibile
# prima della normalizzazione 0=peggiore, 1=migliore.
# =============================================================
KPI_SPEC: dict[str, dict] = {
    "gmd_levy": {
        "label": "Equità levy",
        "unit": "-",
        "higher_is_better": False,
        "help": "Gini Mean Difference sul saldo supplementi − incentivi PV. "
                "Valore grezzo più basso = minore disuguaglianza.",
    },
    "gmd_tax": {
        "label": "Equità tassa CO₂",
        "unit": "-",
        "higher_is_better": False,
        "help": "Gini Mean Difference sul saldo tassa CO₂ − incentivi. "
                "Valore grezzo più basso = minore disuguaglianza.",
    },
    "gmd_cost": {
        "label": "Equità costo",
        "unit": "-",
        "higher_is_better": False,
        "help": "Gini Mean Difference sul costo annuo energia e risanamento. "
                "Valore grezzo più basso = minore disuguaglianza.",
    },
    "avg_cost": {
        "label": "Costo medio energia per famiglia",
        "unit": "CHF/abitazione",
        "higher_is_better": False,
        "help": "Costo medio annuo per elettricità, riscaldamento e risanamento "
                "al 2050.",
    },
    "pv_production": {
        "label": "Produzione PV annuale",
        "unit": "GWh",
        "higher_is_better": True,
        "help": "Energia fotovoltaica prodotta nell'anno 2050.",
    },
    "net_consumption": {
        "label": "Consumo netto specifico medio",
        "unit": "kWh/m²",
        "higher_is_better": False,
        "help": "Consumo specifico netto di riscaldamento al 2050 "
                "(senza calore ambiente).",
    },
    "co2_cum": {
        "label": "Emissioni CO₂ cumulate",
        "unit": "MtonCO₂",
        "higher_is_better": False,
        "help": "Emissioni residenziali cumulate fino al 2050.",
    },
    "cantonal_spend": {
        "label": "Spesa cantonale cumulata",
        "unit": "Mio CHF",
        "higher_is_better": False,
        "help": "Somma 2025–2050 dei fondi cantonali per riscaldamento e "
                "risanamento, al netto dei fondi federali della tassa CO₂.",
    },
}
KPI_ORDER = list(KPI_SPEC.keys())

SCALAR_OUTPUTS = {
    "avg_cost": "Average electricity and heating and retrofit cost",
    "pv_production": "Total PV electricity production",
    "net_consumption": "Specific net final consumption",
    "co2_cum": "Cumulative CO2 emissions",
}
CANTONAL_FUNDS_VAR = "Annual cantonal funds needed"

GMD_SPEC = {
    "gmd_levy": {
        "value": "Average levy minus incentives archetype",
        "weight": "Cumulative archetype HH",
    },
    "gmd_tax": {
        "value": "Average tax minus incentives archetype",
        "weight": "Cumulative archetype HH",
    },
    "gmd_cost": {
        "value": "Electricity and heating and retrofit annual cost",
        "weight": "Annual archetypes",
    },
}
GMD_VARS = sorted({s["value"] for s in GMD_SPEC.values()}
                  | {s["weight"] for s in GMD_SPEC.values()})


def latin_hypercube(n_samples: int, n_dims: int, rng: np.random.Generator) -> np.ndarray:
    """Campione LHS in [0, 1]^n_dims (una cella per riga in ogni dimensione)."""
    u = np.empty((n_samples, n_dims), dtype=float)
    for j in range(n_dims):
        cut = (np.arange(n_samples, dtype=float) + rng.random(n_samples)) / n_samples
        rng.shuffle(cut)
        u[:, j] = cut
    return u


def build_uncertainty_samples(
    n_samples: int = N_SAMPLES, seed: int = SAMPLE_SEED,
) -> pd.DataFrame:
    """50 combinazioni fisse, una per riga, uniforme (LHS) su min–max."""
    rng = np.random.default_rng(seed)
    u = latin_hypercube(n_samples, len(UNCERTAINTY_ORDER), rng)
    data: dict[str, np.ndarray] = {"sample_id": np.arange(n_samples, dtype=int)}
    for j, name in enumerate(UNCERTAINTY_ORDER):
        lo, hi = UNCERTAINTY_BOUNDS[name]
        data[name] = lo + u[:, j] * (hi - lo)
    return pd.DataFrame(data)


def load_or_create_samples(path: Path | None = None) -> pd.DataFrame:
    """Carica il campione persistito, o lo crea una tantum."""
    path = path or SAMPLES_PATH
    if path.exists():
        df = pd.read_parquet(path)
        if len(df) == N_SAMPLES and all(c in df.columns for c in UNCERTAINTY_ORDER):
            return df
    path.parent.mkdir(parents=True, exist_ok=True)
    df = build_uncertainty_samples()
    df.to_parquet(path, index=False)
    return df


def all_policy_combos() -> list[dict[str, float]]:
    grids = [POLICY_GRID[name] for name in POLICY_ORDER]
    return [
        {name: float(val) for name, val in zip(POLICY_ORDER, combo)}
        for combo in itertools.product(*grids)
    ]


def policy_id_from_values(values: dict[str, float]) -> int:
    idx = 0
    stride = 1
    for name in reversed(POLICY_ORDER):
        opts = POLICY_GRID[name]
        pos = opts.index(float(values[name]))
        idx += pos * stride
        stride *= len(opts)
    return idx


def format_policy_value(name: str, value: float) -> str:
    meta = POLICY_META[name]
    if meta["kind"] == "binary":
        return "Sì" if float(value) >= 0.5 else "No"
    if meta["kind"] == "muken":
        return MUKEN_LABELS.get(float(value), f"{value:g}")
    unit = meta["unit"]
    text = f"{value:g}"
    return f"{text} {unit}" if unit and unit != "-" else text


def n_policy_mixes() -> int:
    n = 1
    for opts in POLICY_GRID.values():
        n *= len(opts)
    return n
