"""Native DELAY FIXED(SMOOTH) experiment. Raw series are kept; hypotheses are not selected in advance."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["PYTHONPATH"] = str(ROOT)

from pv_batteries.vensim_runner import VensimModel
from scripts.vensim_native.publish_mdl import publish

OUT = Path(r"C:\Users\matteo.palucci.inst\AppData\Local\Temp\sure-delay-fixed")
ARCHIVE = ROOT / "dist" / "sure-alignment" / "delay-fixed"
DLL = Path(r"C:\Windows\System32\vendll64.dll")
DELAYS = (("001", 0.01), ("01", 0.1), ("1", 1.0), ("2", 2.0), ("4", 4.0))
NAMES = ["Input", "Smoothed"] + [
    f"{kind}_delay_{label}" for label, _ in DELAYS for kind in ("Named", "Nested")
]


def write_model(path: Path) -> None:
    lines = [
        "{UTF-8}",
        "Input=STEP(10, 1) ~~|",
        "Smoothed=SMOOTH(Input, 2) ~~|",
    ]
    for label, delay in DELAYS:
        lines.append(f"Named_delay_{label}=DELAY FIXED(Smoothed, {delay}, 0) ~~|")
        lines.append(
            f"Nested_delay_{label}=DELAY FIXED(SMOOTH(Input, 2), {delay}, 0) ~~|"
        )
    lines += [
        "INITIAL TIME=0 ~ Year ~|",
        "FINAL TIME=8 ~ Year ~|",
        "TIME STEP=1 ~ Year ~|",
        "SAVEPER=1 ~ Year ~|",
    ]
    path.write_text("\n\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def euler_smooth(inputs, use_next_input: bool):
    series = np.zeros(len(inputs), dtype=float)
    for n in range(len(inputs) - 1):
        sample = inputs[n + 1] if use_next_input else inputs[n]
        series[n + 1] = series[n] + (sample - series[n]) / 2
    return series


def collect(model: VensimModel, run_name: str) -> dict:
    captured = {}
    for name in NAMES:
        times, values = model.get_series(run_name, name, maxn=32)
        captured[name] = {
            "times": times,
            "values": values,
        }
    return captured


def distance(left, right) -> float:
    return float(np.max(np.abs(np.asarray(left) - np.asarray(right))))


def lag(series, steps: int):
    out = np.zeros(len(series), dtype=float)
    if steps <= 0:
        return np.asarray(series, dtype=float)
    if steps < len(series):
        out[steps:] = np.asarray(series[:-steps], dtype=float)
    return out


def fresh_process() -> None:
    vpmx = OUT / "delay_fixed_smooth.vpmx"
    model = VensimModel(vpmx, dll_path=DLL, work_dir=OUT / "new-process")
    model.set_time(initial=0, final=8, step=1)
    model.cmd("SIMULATE>SETVAL|SAVEPER=1")
    model.run("run-full-new", {})
    (OUT / "new-process.json").write_text(
        json.dumps({"runs": {"full-new-process": collect(model, "run-full-new")}}),
        encoding="utf-8",
    )


def analyze() -> None:
    same = json.loads((OUT / "native-same-process.json").read_text(encoding="utf-8"))
    fresh = json.loads((OUT / "new-process.json").read_text(encoding="utf-8"))
    full = same["runs"]["full-1"]
    times = full["Input"]["times"]
    inputs = np.asarray(full["Input"]["values"], dtype=float)
    smoothed = np.asarray(full["Smoothed"]["values"], dtype=float)
    report = {
        "times": times,
        "input": inputs.tolist(),
        "smoothed": smoothed.tolist(),
        "euler_using_input_at_n": euler_smooth(inputs, False).tolist(),
        "euler_using_input_at_n_plus_1": euler_smooth(inputs, True).tolist(),
        "smooth_vs_euler_input_n": distance(smoothed, euler_smooth(inputs, False)),
        "smooth_vs_euler_input_n_plus_1": distance(smoothed, euler_smooth(inputs, True)),
        "delays": {},
        "repeat": {},
    }
    for label, delay in DELAYS:
        named = np.asarray(full[f"Named_delay_{label}"]["values"], dtype=float)
        nested = np.asarray(full[f"Nested_delay_{label}"]["values"], dtype=float)
        shifts = {}
        for steps in sorted({0, int(np.floor(delay)), int(np.ceil(delay)), int(round(delay))}):
            shifts[f"saved_smooth_lag_{steps}"] = distance(named, lag(smoothed, steps))
            # Value before the smooth update equals the previously saved state.
            shifts[f"pre_update_smooth_lag_{steps}"] = distance(named, lag(lag(smoothed, 1), steps))
        report["delays"][str(delay)] = {
            "named_vs_nested": distance(named, nested),
            "named": named.tolist(),
            "nested": nested.tolist(),
            "distances": shifts,
        }
    for key in ("full-2-after-short", "full-3-same-process"):
        report["repeat"][key] = {
            name: distance(full[name]["values"], same["runs"][key][name]["values"])
            for name in NAMES
        }
    new = fresh["runs"]["full-new-process"]
    report["repeat"]["full-new-process"] = {
        name: distance(full[name]["values"], new[name]["values"]) for name in NAMES
    }
    (OUT / "delay-analysis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "smooth_vs_euler_input_n": report["smooth_vs_euler_input_n"],
        "smooth_vs_euler_input_n_plus_1": report["smooth_vs_euler_input_n_plus_1"],
        "delays": {k: {"named_vs_nested": v["named_vs_nested"], "distances": v["distances"]}
                   for k, v in report["delays"].items()},
        "repeat_max": {k: max(v.values()) for k, v in report["repeat"].items()},
    }, indent=2))


def main() -> None:
    if "--fresh" in sys.argv:
        fresh_process()
        return
    OUT.mkdir(parents=True, exist_ok=True)
    mdl = OUT / "delay_fixed_smooth.mdl"
    vpmx = OUT / "delay_fixed_smooth.vpmx"
    write_model(mdl)
    log = publish(mdl, vpmx, OUT / "publish-vensimdp.err")
    (OUT / "publish-log.txt").write_text(log, encoding="utf-8")

    work = OUT / "same-process"
    model = VensimModel(vpmx, dll_path=DLL, work_dir=work)

    def execute(tag: str, final: float):
        model.set_time(initial=0, final=final, step=1)
        model.cmd("SIMULATE>SETVAL|SAVEPER=1")
        model.run(tag, {})
        return collect(model, tag)

    payload = {
        "runs": {
            "full-1": execute("run-full-1", 8),
            "short-final-4": execute("run-short", 4),
            "full-2-after-short": execute("run-full-2", 8),
            "full-3-same-process": execute("run-full-3", 8),
        }
    }
    (OUT / "native-same-process.json").write_text(json.dumps(payload), encoding="utf-8")
    fresh = OUT / "new-process.json"
    if fresh.exists():
        fresh.unlink()
    subprocess.check_call(
        [sys.executable, str(Path(__file__)), "--fresh"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    analyze()
    if ARCHIVE.exists():
        shutil.rmtree(ARCHIVE)
    shutil.copytree(OUT, ARCHIVE)
    print("same-process and fresh-process runs stored", ARCHIVE)


if __name__ == "__main__":
    main()
