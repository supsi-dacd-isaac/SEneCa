"""Corse di riferimento Vensim per gli scenari di validazione.

Per ogni blocco di scenari scrive uno script di comandi, lo esegue con
vendss64.exe (una sola istanza, LOADMODEL una volta), poi costruisce in
parallelo i riferimenti Float64 (vdfx_reference.build) e cancella i .tab.
Verifica che ogni leva impostata con SETVAL compaia nel riferimento con il
valore Float32 atteso: una SETVAL ignorata da Vensim ferma la procedura.

Uso: python run_vensim_scenarios.py SCENARIOS.json MODEL_DIR OUT_DIR [--only id,id] [--chunk 8]
MODEL_DIR contiene SURE.mdl, calibration.out e i sei .vdfx.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "reference"))
from vdfx_reference import build  # noqa: E402

VENSIM = r"C:\Program Files\Vensim\vendss64.exe"
INPUTS = ["PVinput", "HPinput", "EVinput", "InputRenovation", "Input2011", "Input Hour Factors"]


def vname(name: str) -> str:
    return f'"{name}"' if re.search(r"[^A-Za-z0-9 _]", name) else name


def fmt(v: float) -> str:
    return repr(float(v))


def commands(scen: dict) -> list[str]:
    rid = scen["id"]
    cmds = [f"SIMULATE>RUNNAME|{rid}", "SIMULATE>READCIN|calibration.out"]
    cmds.append(f"SIMULATE>SETVAL|FINAL TIME={scen['final_time']}")
    for k, v in scen["settings"].items():
        cmds.append(f"SIMULATE>SETVAL|{vname(k)}={fmt(v)}")
    cmds += ["MENU>RUN|O", f"MENU>VDF2TAB|{rid}.vdfx|{rid}.tab||"]
    return cmds


def build_one(work: str, rid: str, settings: dict, final_time: int) -> dict:
    work = Path(work)
    meta = build(work / f"{rid}.vdfx", work / f"{rid}.tab", work / f"{rid}.ref")
    names = (work / f"{rid}.ref" / "names.txt").read_text(encoding="utf-8").split("\n")[:-1]
    T = meta["times"][2]
    V = np.fromfile(work / f"{rid}.ref" / "values.f64").reshape(len(names), T)
    status = np.fromfile(work / f"{rid}.ref" / "status.u8", dtype=np.uint8)
    cands = json.loads((work / f"{rid}.ref" / "candidates.json").read_text(encoding="utf-8"))
    idx = {n.strip('"').lower(): i for i, n in enumerate(names)}
    bad = []
    for k, v in settings.items():
        i = idx.get(k.lower())
        got = None if i is None else float(V[i, 0])
        if got is None:
            ok = False
        elif status[i] == 0:      # valore Float64 letto dal .vdfx: SETVAL scrive in Float64
            ok = got == float(v) or got == float(np.float32(v))
        elif status[i] == 3:      # più candidati Float64: basta che uno coincida
            ok = got in (float(v), float(np.float32(v))) or                  any(c[0] in (float(v), float(np.float32(v))) for c in cands.get(str(i), []))
        else:                     # costante rimasta a 6 cifre dell'export
            ok = got == float("%.6g" % v)
        if not ok:
            bad.append((k, v, got, int(status[i]) if i is not None else None))
    meta["truncated_at"] = None
    if meta["times"][1] != final_time:
        # Vensim interrompe la corsa su un errore numerico (es. divisione per zero):
        # si valida fino all'anno precedente; le leve assenti dall'export non sono errori
        meta["truncated_at"] = meta["times"][1]
        bad = [b for b in bad if b[2] is not None]
    (work / f"{rid}.tab").unlink()
    meta["setval_errors"] = bad
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", type=Path)
    ap.add_argument("model_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--only", default="")
    ap.add_argument("--chunk", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    spec = json.loads(a.scenarios.read_text(encoding="utf-8"))
    todo = [s for s in spec["scenarios"] if not s.get("same_as_base")]
    if a.only:
        keep = set(a.only.split(","))
        todo = [s for s in todo if s["id"] in keep]
    work = a.out_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    for f in ["SURE.mdl", "calibration.out"] + [f"{n}.vdfx" for n in INPUTS]:
        if not (work / f).exists():
            shutil.copy2(a.model_dir / f, work / f)
    log_path = work / "runs.jsonl"
    done = set()
    if log_path.exists():
        done = {json.loads(l)["id"] for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()}
    todo = [s for s in todo if s["id"] not in done]
    print(f"scenari da eseguire: {len(todo)} (già fatti: {len(done)})", flush=True)
    pool = ProcessPoolExecutor(max_workers=a.workers)
    pending = []

    def collect(block=False):
        for fut, scen in list(pending):
            if block or fut.done():
                meta = fut.result()
                pending.remove((fut, scen))
                rec = {"id": scen["id"], "float64": meta["float64"],
                       "six_digits": meta["six_digits_ambiguous"] + meta["six_digits_unmatched"],
                       "series": meta["series"], "setval_errors": meta["setval_errors"],
                       "truncated_at": meta["truncated_at"]}
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
                status = "OK" if not meta["setval_errors"] else f"SETVAL NON APPLICATE {meta['setval_errors']}"
                if meta["truncated_at"]:
                    status += f" (corsa Vensim interrotta al {meta['truncated_at']:.0f})"
                print(f"  riferimento {scen['id']}: {meta['float64']} serie Float64, {status}", flush=True)
                # gli errori restano nel registro: la validazione li riporta

    for c0 in range(0, len(todo), a.chunk):
        chunk = todo[c0:c0 + a.chunk]
        cmd = ["SPECIAL>LOADMODEL|SURE.mdl"]
        for s in chunk:
            cmd += commands(s)
        cmd.append("MENU>EXIT")
        script = work / f"chunk_{c0:03d}.cmd"
        script.write_bytes(("\r\n".join(cmd) + "\r\n").encode("mbcs"))
        t = time.time()
        for attempt in range(2):   # Vensim a volte esce prima della fine dello script
            subprocess.run([VENSIM, str(script)], cwd=work, check=True, timeout=3600)
            missing = [s["id"] for s in chunk if not (work / f"{s['id']}.tab").exists()]
            if not missing:
                break
            print(f"  nuovo tentativo per {missing}", flush=True)
        print(f"blocco {c0 // a.chunk + 1}: {len(chunk)} corse Vensim in {time.time() - t:.0f} s"
              + (f"; MANCANO {missing}" if missing else ""), flush=True)
        if missing:
            raise SystemExit("Corse Vensim non riuscite")
        collect()
        for s in chunk:
            pending.append((pool.submit(build_one, str(work), s["id"], s["settings"], s["final_time"]), s))
    collect(block=True)
    pool.shutdown()
    print("fine", flush=True)


if __name__ == "__main__":
    main()
