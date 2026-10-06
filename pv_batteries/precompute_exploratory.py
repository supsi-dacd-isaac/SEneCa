"""Pre-calcolo delle 6400 simulazioni policy × incertezza.

128 policy mix × 50 campioni LHS dei 17 parametri incerti. Per ogni run
salva solo i KPI richiesti (tre GMD al 2050 + 5 indicatori scalari).

Esempi:
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_exploratory.py --probe
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_exploratory.py --limit 2
    .\\.venv\\Scripts\\python.exe pv_batteries\\precompute_exploratory.py --workers 4
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from exploratory_config import (  # noqa: E402
    CANTONAL_FUNDS_VAR, CANTONAL_SPEND_START, CONSOLIDATED_KPIS,
    EXPLORATORY_SWITCH, FINAL_YEAR, GMD_SPEC, GMD_VARS, KPI_ORDER, N_SAMPLES,
    POLICY_ORDER, RUN_NAME, SAMPLES_PATH, SCALAR_OUTPUTS, STORE_DIR, VPMX,
    YEARS, all_policy_combos, load_or_create_samples, n_policy_mixes,
)
from gmd import compute_gmd_from_spec  # noqa: E402
from vensim_runner import VensimModel  # noqa: E402

RELAUNCH_CODE = 75
MAXN = 5000
YEAR_LIST = list(YEARS)
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def _combo_key(policy_id: int, sample_id: int) -> str:
    return f"{policy_id:03d}_{sample_id:02d}"


def _parts_dir() -> Path:
    return STORE_DIR / "parts"


def _part_path(worker_id: int) -> Path:
    return _parts_dir() / f"w{worker_id}.parquet"


def _progress_path() -> Path:
    return STORE_DIR / "_progress.json"


def _load_part(worker_id: int) -> pd.DataFrame:
    path = _part_path(worker_id)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _done_keys(df: pd.DataFrame) -> set[tuple[int, int]]:
    if df.empty:
        return set()
    return {(int(p), int(s)) for p, s in zip(df["policy_id"], df["sample_id"])}


def _all_done_keys() -> set[tuple[int, int]]:
    done: set[tuple[int, int]] = set()
    if not _parts_dir().exists():
        return done
    for fp in _parts_dir().glob("w*.parquet"):
        done |= _done_keys(pd.read_parquet(fp))
    return done


def _save_part(worker_id: int, df: pd.DataFrame) -> None:
    _parts_dir().mkdir(parents=True, exist_ok=True)
    tmp = _part_path(worker_id).with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(_part_path(worker_id))


def _build_expand_cache(model: VensimModel) -> dict[str, list[str]]:
    cache: dict[str, list[str]] = {}
    for base in list(SCALAR_OUTPUTS.values()) + [CANTONAL_FUNDS_VAR] + list(GMD_VARS):
        cache[base] = model.expand_var(base)
    return cache


def _sub_of(full: str, base: str) -> str:
    if full == base:
        return ""
    return full[len(base) + 1:-1] if full.startswith(base + "[") else full


def _sanitize(value: float) -> float:
    if not np.isfinite(value) or abs(value) > 1e20:
        return float("nan")
    return float(value)


def _read_val(model: VensimModel, varname: str) -> float:
    """Legge il 2050 dal VDF della run (get_val della DLL non e' affidabile)."""
    try:
        return _sanitize(model.get_year(RUN_NAME, varname, FINAL_YEAR, maxn=MAXN))
    except RuntimeError:
        return float("nan")


def _series_year_map(model: VensimModel, varname: str) -> dict[int, float]:
    t, v = model.get_series(RUN_NAME, varname, maxn=MAXN)
    ta = np.asarray(t, dtype=float)
    va = np.asarray(v, dtype=float)
    out: dict[int, float] = {}
    for yr in YEAR_LIST:
        idx = np.where(np.isclose(ta, yr))[0]
        if len(idx):
            out[yr] = float(va[idx[0]])
    return out


def _read_gmd_map(model: VensimModel, base: str, fulls: list[str]) -> dict[str, float]:
    return {_sub_of(full, base): _read_val(model, full) for full in fulls}


def _extract_kpis(model: VensimModel, expand_cache: dict[str, list[str]]) -> dict[str, float]:
    # Pesi prima: si saltano gli archetipi a peso nullo nella lettura dei valori.
    values_2050: dict[str, dict[str, float]] = {}
    active_subs: set[str] | None = None
    weight_bases = sorted({spec["weight"] for spec in GMD_SPEC.values()})
    value_bases = sorted({spec["value"] for spec in GMD_SPEC.values()})
    for base in weight_bases:
        wmap = _read_gmd_map(model, base, expand_cache[base])
        values_2050[base] = wmap
        live = {sub for sub, val in wmap.items() if val and np.isfinite(val)}
        active_subs = live if active_subs is None else (active_subs | live)
    for base in value_bases:
        fulls = expand_cache[base]
        if active_subs is None:
            values_2050[base] = _read_gmd_map(model, base, fulls)
            continue
        per: dict[str, float] = {}
        for full in fulls:
            sub = _sub_of(full, base)
            if sub in active_subs:
                per[sub] = _read_val(model, full)
        values_2050[base] = per
    gmd = compute_gmd_from_spec(values_2050, GMD_SPEC)

    scalars: dict[str, float] = {}
    for kpi, base in SCALAR_OUTPUTS.items():
        fulls = expand_cache[base]
        if len(fulls) == 1:
            scalars[kpi] = _read_val(model, fulls[0])
        else:
            scalars[kpi] = float(np.nansum([_read_val(model, f) for f in fulls]))

    funds_name = expand_cache[CANTONAL_FUNDS_VAR][0]
    funds = _series_year_map(model, funds_name)
    years = [yr for yr in range(CANTONAL_SPEND_START, FINAL_YEAR + 1) if yr in funds]
    if not years or FINAL_YEAR not in funds:
        scalars["cantonal_spend"] = float("nan")
        completed = False
    else:
        scalars["cantonal_spend"] = float(sum(funds[yr] for yr in years))
        completed = True

    out = {**gmd, **scalars, "completed": float(completed)}
    return out


def _scenario_inputs(policy: dict[str, float], sample: dict[str, float]) -> dict[str, float]:
    inputs = {EXPLORATORY_SWITCH: 1.0}
    inputs.update(policy)
    inputs.update(sample)
    return inputs


def _write_progress(done: int, total: int, current: str, processed: int, t0: float) -> None:
    elapsed = time.perf_counter() - t0
    rate = processed / elapsed if elapsed else 0
    eta = (total - done) / rate if rate else 0
    payload = {
        "done": done,
        "total": total,
        "current": current,
        "elapsed_min": round(elapsed / 60, 2),
        "eta_min": round(eta / 60, 2),
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    _progress_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"[{done}/{total}] {current} | elapsed {elapsed/60:.1f} min | "
        f"ETA {eta/60:.1f} min",
        flush=True,
    )


def _all_jobs() -> list[tuple[int, int, dict[str, float], dict[str, float]]]:
    policies = all_policy_combos()
    samples = load_or_create_samples()
    jobs = []
    for pid, policy in enumerate(policies):
        for _, row in samples.iterrows():
            sid = int(row["sample_id"])
            sample = {name: float(row[name]) for name in samples.columns
                      if name != "sample_id"}
            jobs.append((pid, sid, policy, sample))
    return jobs


def consolidate() -> pd.DataFrame:
    files = sorted(_parts_dir().glob("w*.parquet"))
    if not files:
        raise SystemExit("Nessuna riga da consolidare in " + str(_parts_dir()))
    frames = [pd.read_parquet(fp) for fp in files]
    allrows = pd.concat(frames, ignore_index=True)
    allrows = allrows.drop_duplicates(["policy_id", "sample_id"], keep="last")
    CONSOLIDATED_KPIS.parent.mkdir(parents=True, exist_ok=True)
    allrows.to_parquet(CONSOLIDATED_KPIS, index=False)
    print(
        f"Consolidate {len(files)} part -> {CONSOLIDATED_KPIS} "
        f"({len(allrows):,} righe)",
        flush=True,
    )
    return allrows


def probe() -> None:
    print("Probe: 1 run + lettura KPI", flush=True)
    samples = load_or_create_samples()
    policy = all_policy_combos()[0]
    sample = {name: float(samples.iloc[0][name]) for name in samples.columns
              if name != "sample_id"}
    work = STORE_DIR / "_runs_probe"
    work.mkdir(parents=True, exist_ok=True)
    model = VensimModel(VPMX, work_dir=work)
    model.set_time(initial=YEAR_LIST[0], final=YEAR_LIST[-1], step=1)
    expand = _build_expand_cache(model)
    print("get_val:", getattr(model, "_has_get_val", False), flush=True)
    print("GMD elementi:", {b: len(expand[b]) for b in GMD_VARS}, flush=True)
    inputs = _scenario_inputs(policy, sample)
    t0 = time.perf_counter()
    model.run(RUN_NAME, inputs)
    t_run = time.perf_counter() - t0
    t1 = time.perf_counter()
    kpis = _extract_kpis(model, expand)
    t_ext = time.perf_counter() - t1
    print(f"run {t_run:.1f}s | extract {t_ext:.1f}s", flush=True)
    for k in KPI_ORDER + ["completed"]:
        print(f"  {k}: {kpis.get(k)}", flush=True)


def run_worker(args: argparse.Namespace) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    _parts_dir().mkdir(parents=True, exist_ok=True)
    load_or_create_samples()

    jobs = _all_jobs()
    if args.worker_count > 1:
        jobs = jobs[args.worker_id::args.worker_count]
    done_df = _load_part(args.worker_id)
    done = _all_done_keys()
    pending = [j for j in jobs if (j[0], j[1]) not in done]
    if args.limit:
        pending = pending[:args.limit]
    already = sum(1 for j in jobs if (j[0], j[1]) in done)
    total_here = len(jobs)

    print(
        f"[exploratory w{args.worker_id}/{args.worker_count}] "
        f"job worker: {len(jobs)} | gia' fatte: {already} | "
        f"da calcolare: {len(pending)}",
        flush=True,
    )
    if not pending:
        print("Niente da calcolare per questo worker.", flush=True)
        if args.worker_count == 1 and not args.no_consolidate:
            consolidate()
        return

    work = Path(tempfile.gettempdir()) / f"seneca_expl_w{args.worker_id}"
    work.mkdir(parents=True, exist_ok=True)
    model = VensimModel(VPMX, work_dir=work)
    model.set_time(initial=YEAR_LIST[0], final=YEAR_LIST[-1], step=1)
    expand = _build_expand_cache(model)
    lst = work / "expl_save.lst"
    lst.write_text(
        "\n".join(list(SCALAR_OUTPUTS.values()) + [CANTONAL_FUNDS_VAR] + list(GMD_VARS))
        + "\n",
        encoding="ascii",
    )
    try:
        model.cmd(f"SIMULATE>SAVELIST|{lst}")
    except RuntimeError as e:
        print(f"SAVELIST non applicato: {e}", flush=True)
    print(
        "GMD elementi:", {b: len(expand[b]) for b in GMD_VARS},
        "| get_val:", getattr(model, "_has_get_val", False),
        flush=True,
    )

    t0 = time.perf_counter()
    n_pending = len(pending)
    for i, (pid, sid, policy, sample) in enumerate(pending, start=1):
        key = _combo_key(pid, sid)
        inputs = _scenario_inputs(policy, sample)
        try:
            model.run(RUN_NAME, inputs)
            kpis = _extract_kpis(model, expand)
        except OSError as e:
            print(f"OSError su {key}: {e} -> rilancio", flush=True)
            try:
                model.clear_runs()
            except Exception:
                pass
            sys.exit(RELAUNCH_CODE)

        row = {
            "policy_id": pid,
            "sample_id": sid,
            **policy,
            **{k: kpis.get(k, float("nan")) for k in KPI_ORDER},
            "completed": kpis.get("completed", 0.0),
        }
        done_df = pd.concat([done_df, pd.DataFrame([row])], ignore_index=True)
        if i % 5 == 0 or i == n_pending:
            _save_part(args.worker_id, done_df)
        _write_progress(already + i, total_here, key, i, t0)
        model.clear_runs()
        if i % 10 == 0:
            gc.collect()
        if args.restart_every and i >= args.restart_every and i < n_pending:
            _save_part(args.worker_id, done_df)
            print(f"Restart preventivo dopo {i} run", flush=True)
            sys.exit(RELAUNCH_CODE)

    print(f"Worker {args.worker_id} completato in {(time.perf_counter()-t0)/60:.1f} min",
          flush=True)
    if args.worker_count == 1 and not args.no_consolidate:
        consolidate()


def _inner_cmd(args: argparse.Namespace) -> list[str]:
    cmd = [
        str(PY if PY.exists() else sys.executable), "-u",
        str(Path(__file__).resolve()),
        "--inner",
        "--worker-id", str(args.worker_id),
        "--worker-count", str(args.worker_count),
        "--restart-every", str(args.restart_every),
    ]
    if args.limit:
        cmd += ["--limit", str(args.limit)]
    if args.no_consolidate:
        cmd.append("--no-consolidate")
    return cmd


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(HERE), env.get("PYTHONPATH", "")])
    return env


def run_with_restarts(args: argparse.Namespace) -> None:
    restarts = 0
    cmd = _inner_cmd(args)
    while True:
        print(f"=== exploratory w{args.worker_id} restart#{restarts} ===", flush=True)
        rc = subprocess.call(cmd, cwd=str(ROOT), env=_env())
        if rc == 0:
            return
        if rc == RELAUNCH_CODE:
            restarts += 1
            continue
        raise SystemExit(rc)


def spawn_workers(n_workers: int, extra: list[str]) -> None:
    load_or_create_samples()
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    _parts_dir().mkdir(parents=True, exist_ok=True)
    procs = []
    for wid in range(n_workers):
        cmd = [
            str(PY if PY.exists() else sys.executable), "-u",
            str(Path(__file__).resolve()),
            "--worker-id", str(wid),
            "--worker-count", str(n_workers),
            *extra,
        ]
        print("Avvio", " ".join(cmd), flush=True)
        procs.append(subprocess.Popen(cmd, cwd=str(ROOT), env=_env()))
    codes = [p.wait() for p in procs]
    if any(c != 0 for c in codes):
        raise SystemExit(f"Worker falliti: {codes}")
    consolidate()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--restart-every", type=int, default=80)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--worker-id", type=int, default=0)
    ap.add_argument("--worker-count", type=int, default=1)
    ap.add_argument("--inner", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--consolidate-only", action="store_true")
    ap.add_argument("--no-consolidate", action="store_true")
    args = ap.parse_args()

    STORE_DIR.mkdir(parents=True, exist_ok=True)
    if args.consolidate_only:
        consolidate()
        return
    if args.probe:
        probe()
        return
    if args.inner:
        run_worker(args)
        return
    if args.workers > 1:
        extra = []
        if args.limit:
            extra += ["--limit", str(args.limit)]
        extra += ["--restart-every", str(args.restart_every), "--no-consolidate"]
        spawn_workers(args.workers, extra)
        return
    run_with_restarts(args)


if __name__ == "__main__":
    main()
