"""Config UI Esplora PySD: sezioni allineate alle pagine Risultati + mapping → PySD.

Dopo la ritraduzione da SURE.mdl, tutte le leve Risultati esistono come costanti
omonime in SURE_pysd.py e si applicano direttamente via params.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pv_batteries import elettricita_config as elec_cfg  # noqa: E402
from pv_batteries import pv_batteries_config as pv_cfg  # noqa: E402
from pv_batteries import risanamento_config as ris_cfg  # noqa: E402
from pv_batteries import veicoli_config as vei_cfg  # noqa: E402


@dataclass(frozen=True)
class ExploreInput:
    """Un controllo sidebar."""
    name: str  # chiave UI (= nome Vensim / Risultati)
    label: str
    unit: str
    values: list[float]
    default: float
    supported: bool
    pysd_name: str | None = None
    binary: bool = False
    choice_labels: dict[float, str] | None = None
    note: str = ""


def _meta(cfg, name: str) -> tuple[str, str]:
    m = cfg.INPUT_META.get(name, {})
    return m.get("label", name), m.get("unit", "")


def _default(cfg, name: str) -> float:
    return float(cfg.BASE_SCENARIO[name])


def _inp(cfg, name: str, *, binary: bool = False, choice_labels=None,
         note: str = "") -> ExploreInput:
    lbl, unit = _meta(cfg, name)
    return ExploreInput(
        name, lbl, unit,
        list(cfg.INPUT_GRID[name]),
        _default(cfg, name),
        supported=True,
        pysd_name=name,
        binary=binary,
        choice_labels=choice_labels,
        note=note,
    )


def _build_sections() -> list[tuple[str, list[ExploreInput]]]:
    pv_inputs = [
        _inp(pv_cfg, "PV rebate cantonal"),
        _inp(pv_cfg, "FiT"),
        _inp(pv_cfg, "Battery Rebate"),
        _inp(pv_cfg, "PV rebate federal"),
        _inp(pv_cfg, "PV reg scenario", binary=True),
        _inp(pv_cfg, "Energy Community scenario", binary=True),
    ]

    ris_inputs = []
    for name in ris_cfg.INPUT_ORDER:
        if name == "MuKEn scenario":
            ris_inputs.append(_inp(
                ris_cfg, name,
                choice_labels=dict(ris_cfg.MUKEN_LABELS),
            ))
        else:
            ris_inputs.append(_inp(ris_cfg, name))

    vei_inputs = [_inp(vei_cfg, name) for name in vei_cfg.INPUT_ORDER]

    elec_inputs = []
    for name in elec_cfg.INPUT_ORDER:
        if name in ("PV rebate cantonal", "FiT", "PV rebate federal"):
            continue  # già in sezione PV
        elec_inputs.append(_inp(elec_cfg, name))

    return [
        ("1. PV e Batterie", pv_inputs),
        ("2. Riscaldamento e Risanamento", ris_inputs),
        ("3. Veicoli", vei_inputs),
        ("4. Elettricità", elec_inputs),
    ]


SECTIONS = _build_sections()

ALL_INPUTS: list[ExploreInput] = [inp for _, inps in SECTIONS for inp in inps]
INPUT_BY_NAME: dict[str, ExploreInput] = {i.name: i for i in ALL_INPUTS}


def base_ui_values() -> dict[str, float]:
    """Valori UI dello scenario base (come pagine Risultati)."""
    return {i.name: float(i.default) for i in ALL_INPUTS}


def ui_to_pysd_params(ui: dict[str, float]) -> dict[str, float]:
    """Converte i valori sidebar nei params PySD (nomi Vensim 1:1)."""
    params: dict[str, float] = {}
    for inp in ALL_INPUTS:
        if not inp.supported or inp.pysd_name is None:
            continue
        params[inp.pysd_name] = float(ui.get(inp.name, inp.default))
    return params


def format_ui_summary(ui: dict[str, float]) -> str:
    parts = []
    for inp in ALL_INPUTS:
        if not inp.supported:
            continue
        v = float(ui.get(inp.name, inp.default))
        if inp.choice_labels and v in inp.choice_labels:
            parts.append(f"{inp.label}={inp.choice_labels[v]}")
        else:
            parts.append(f"{inp.label}={v:g}")
    return " | ".join(parts)
