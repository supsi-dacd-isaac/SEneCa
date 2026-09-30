"""Harness di esecuzione del modello SURE tradotto in pysd.

- carica una sola volta Vensim/SURE_pysd.py (gia' tradotto + fix self-ref);
- pota il modello con select_submodel alla chiusura delle dipendenze degli OUTPUT
  (tiene solo gli stateful necessari -> velocita');
- inietta le costanti calibrate (constants_ref.pkl, estratte da SURE.vpmx) e gli
  input scenario come params (dict arbitrario di costanti scalari);
- run 2011-2050 riusando il modello caricato.

    Uso:
    from sure_pysd import load_model, run_scenario, OUTPUTS
    run_scenario(model, scenario_inputs={"PV rebate cantonal": 0.1, "FiT": 0.0, ...})
"""
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import xarray as xr

warnings.filterwarnings("ignore")
sys.setrecursionlimit(1_000_000)


@contextmanager
def _arithmetic_join_override():
    """Forza xarray a saltare l'allineamento coordinate nelle operazioni binarie.

    Il collo di bottiglia della singola run e' l'align di xarray, richiamato ad ogni
    operazione tra DataArray durante l'integrazione (~76% del tempo in alignment.py).
    Nel modello SURE gli operandi hanno gia' coord identiche e ordinate (PySD lo
    garantisce), quindi 'override' -- che usa le coord del primo operando senza
    confronto ne' reindex -- produce output bit-identici eliminando ~30% di CPU.

    'override' e' valido per xr.align/reindex ma il validatore di set_options non lo
    espone: OPTIONS e' un dict, si assegna direttamente e si ripristina in finally.
    """
    from xarray.core.options import OPTIONS
    old = OPTIONS["arithmetic_join"]
    OPTIONS["arithmetic_join"] = "override"
    try:
        yield
    finally:
        OPTIONS["arithmetic_join"] = old

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sure_paths as paths  # noqa: E402

MODEL_DIR = paths.VENSIM


def __getattr__(name):
    """PY / CONST_PKL risolti alla variante corrente (SURE_VARIANT) all'accesso.

    Cosi' `import sure_pysd` prima di `sure_paths.set_variant(...)` resta valido.
    """
    if name == "PY":
        return paths.pysd_py()
    if name == "CONST_PKL":
        return paths.const_pkl()
    raise AttributeError(name)


def _collect_results_output_bases() -> list[str]:
    """Unione OUTPUT_BASES delle pagine Risultati (PV / Risanamento / Veicoli / Elettricità)."""
    pvbat = ROOT / "pv_batteries"
    if str(pvbat) not in sys.path:
        sys.path.insert(0, str(pvbat))
    from elettricita_config import OUTPUT_BASES as elec_bases
    from pv_batteries_config import OUTPUT_BASES as pv_bases
    from risanamento_config import OUTPUT_BASES as ris_bases
    from veicoli_config import OUTPUT_BASES as vei_bases

    # Extra storici Esplora (tabella delta) se non già nei Results
    extras = [
        "Power by Type",
        "Annual CO2 emissions",
    ]
    out: list[str] = []
    for name in (
        list(pv_bases) + list(ris_bases) + list(vei_bases)
        + list(elec_bases) + extras
    ):
        if name not in out:
            out.append(name)
    return out


# Output di interesse = chart Risultati annuali + extra Esplora
OUTPUTS = _collect_results_output_bases()

# Leve scenario allineate alle pagine Risultati (esclusi da constants_ref)
SCENARIO_INPUTS = [
    "PV rebate cantonal",
    "FiT",
    "Battery Rebate",
    "PV rebate federal",
    "PV reg scenario",
    "Energy Community scenario",
    "Grant share HP",
    "Grant share PelletBoiler",
    "Grant share DH",
    "Retrofit incentive input",
    "CO2 tax",
    "MuKEn scenario",
    "EV charger incentive input",
    "CO2 coefficient ICE",
    "ICE ban year",
    "EV annual cost reduction input",
    "ICE fuel price input",
    "Seasonal PHS annual production 2050",
    "Additional annual inflow for Ticino",
]


def _output_closure_vars(model):
    """Chiusura non-stateful completa delle dipendenze degli OUTPUT (py names).

    select_submodel tiene poi solo gli stateful raggiungibili da questi.
    """
    from pysd.py_backend.utils import (
        get_key_and_value_by_insensitive_key_or_value as getkv)
    deps = model.dependencies
    ns = model._namespace

    def is_special(k):
        return k == "time" or k.startswith("__")

    seen, stack = set(), [getkv(o, ns)[1] for o in OUTPUTS]
    while stack:
        e = stack.pop()
        if e is None or e in seen:
            continue
        seen.add(e)
        d = deps.get(e)
        if not d:
            continue
        if isinstance(d, dict) and ("step" in d or "initial" in d):
            nxt = list(d.get("step", {})) + list(d.get("initial", {}))
        else:
            nxt = list(d)
        stack.extend(k for k in nxt if not is_special(k))
    return [e for e in seen if not e.startswith("_")]


def load_model(prune=True):
    import pysd
    py = paths.pysd_py()
    print(f"Caricamento modello {py.name} ...")
    model = pysd.load(str(py))
    if prune:
        n_before = len(model._dynamicstateful_elements)
        cvars = _output_closure_vars(model)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model.select_submodel(vars=cvars)
        for wm in caught:
            if "necessary but not given" in str(wm.message):
                raise RuntimeError(
                    "select_submodel richiede componenti esogeni (chiusura OUTPUT "
                    "incompleta):\n" + str(wm.message))
        n_after = len(model._dynamicstateful_elements)
        print(f"Model potato: {len(cvars)} vars, {n_after}/{n_before} stateful dinamici.")
    return model


def _in_ns(model, name):
    from pysd.py_backend.utils import (
        get_key_and_value_by_insensitive_key_or_value as getkv)
    return getkv(name, model._namespace)[1] is not None


def build_constant_params(model):
    """Costanti calibrate da constants_ref.pkl (fisse tra scenari)."""
    params = {}
    const_pkl = paths.const_pkl()
    if not const_pkl.is_file():
        return params
    import pickle
    with open(const_pkl, "rb") as f:
        consts = pickle.load(f)
    for real_name, spec in consts.items():
        if not _in_ns(model, real_name):
            continue
        if not spec["dims"]:
            params[real_name] = float(spec["values"])
        else:
            params[real_name] = xr.DataArray(
                spec["values"], coords=spec["coords"], dims=spec["dims"])
    return params


def build_params(model, pv=0.0, fit=0.0, ec=0.0, const_params=None,
                 scenario_inputs=None):
    """Unisce costanti calibrate + input scenario.

    scenario_inputs: dict nome_reale -> float (preferito).
    Altrimenti usa i 3 input storici pv/fit/ec.
    """
    if const_params is None:
        const_params = build_constant_params(model)
    if scenario_inputs is None:
        scenario_inputs = {
            "PV rebate cantonal": float(pv),
            "FiT": float(fit),
            "Energy Community scenario": float(ec),
        }
    scen = {}
    for name, val in scenario_inputs.items():
        if _in_ns(model, name):
            scen[name] = float(val)
    return {**const_params, **scen}


def model_output_columns(model, cols):
    """Tiene solo gli output presenti nella traduzione PySD caricata.

    Le pagine Risultati girano su Vensim e possono chiedere variabili aggiunte
    al modello dopo l'ultima traduzione: senza questo filtro `model.run` alza
    KeyError e si perdono anche tutti gli altri output.
    """
    from pysd.py_backend.utils import (
        get_key_and_value_by_insensitive_key_or_value as getkv)

    ns = model._namespace
    keep = [c for c in cols if getkv(c, ns)[1] is not None]
    if missing := [c for c in cols if c not in keep]:
        warnings.warn(
            f"Output assenti da {paths.pysd_py().name} ed esclusi dalla run: "
            + ", ".join(missing),
            stacklevel=2,
        )
    return keep


def run_scenario(model, pv=0.0, fit=0.0, ec=0.0, const_params=None,
                 timestamps=None, flatten=True, fast_align=True,
                 scenario_inputs=None, return_columns=None):
    """Esegue una run 2011-2050 (o timestamps custom).

    Compatibile con le chiamate esistenti:
        run_scenario(model, pv, fit, ec, const_params=...)
    Oppure con un dict arbitrario di costanti:
        run_scenario(model, scenario_inputs={...}, const_params=...)

    return_columns: subset di OUTPUTS (default = tutti). Deve stare nella
    chiusura del modello potato.
    """
    params = build_params(
        model, pv=pv, fit=fit, ec=ec, const_params=const_params,
        scenario_inputs=scenario_inputs,
    )
    cols = model_output_columns(
        model, list(OUTPUTS if return_columns is None else return_columns),
    )
    kwargs = dict(params=params, return_columns=cols, flatten_output=flatten)
    if timestamps is not None:
        kwargs["return_timestamps"] = list(timestamps)
    if fast_align:
        with _arithmetic_join_override():
            df = model.run(**kwargs)
    else:
        df = model.run(**kwargs)
    df.index = np.asarray(df.index, dtype=float)
    return df


if __name__ == "__main__":
    import time

    t0 = time.perf_counter()
    model = load_model(prune=True)
    print(f"load+prune: {time.perf_counter() - t0:.1f}s")

    const = build_constant_params(model)
    print(f"costanti calibrate iniettate: {len(const)}")

    for hz in (2012, 2015):
        t = time.perf_counter()
        df = run_scenario(model, 0.0, 0.0, 0.0, const,
                          timestamps=range(2011, hz + 1))
        dt = time.perf_counter() - t
        print(f"run 2011-{hz} ({hz-2011} step): {dt:.1f}s")
    print("\nUltima riga:")
    print(df.tail(1).T)
