"""Export the archived SURE VPMX with the recorded scenario inputs.

Missing variables and truncated time grids are recorded. Constant series are
not extended beyond the times the DLL returned.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["PYTHONPATH"] = str(ROOT)

from pv_batteries.vensim_runner import VensimModel, setval_name

SOURCE_VPMX = Path(r"C:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim\SURE.vpmx")
SOURCE_DATA = Path(r"C:\Users\matteo.palucci\OneDrive - SUPSI\Desktop\SEneCa\Vensim")
DATA_FILES = (
    "EVinput.vdfx",
    "HPinput.vdfx",
    "Input Hour Factors.vdfx",
    "Input2011.vdfx",
    "InputRenovation.vdfx",
    "PVinput.vdfx",
)
INPUTS = ROOT / "dist" / "sure-alignment" / "reference-17db1f4" / "source" / "Vensim_test_runs" / "inputs.json"
REFERENCE = ROOT / "dist" / "sure-alignment" / "reference-17db1f4" / "source" / "Vensim_test_runs" / "outputs.parquet"
OUT = ROOT / "dist" / "sure-alignment" / "original"
DLL = Path(r"C:\Windows\System32\vendll64.dll")
DIAGNOSTICS = (
    "Hourly demand and PHS",
    "Priority vector by supplier",
    "Marginal cost by supplier",
    "Hourly imported electricity",
    "PHS hourly supply",
    "Hour factor PHS consumption",
    "Seasonal PHS monthly demand",
    "Seasonal PHS monthly production",
    "Seasonal PHS hourly demand",
    "Seasonal PHS hourly production",
)
CONTROLS = ("ICE ban year", "Deflussi minimi LPAc", "Cambiamento climatico Hydro")


def prepare_model() -> Path:
    model_dir = OUT / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    destination = model_dir / "SURE.vpmx"
    if not destination.exists() or destination.stat().st_size != SOURCE_VPMX.stat().st_size:
        shutil.copyfile(SOURCE_VPMX, destination)
    for name in DATA_FILES:
        target = model_dir / name
        if not target.exists():
            shutil.copyfile(SOURCE_DATA / name, target)
    return destination


def split_name(full: str, base: str):
    if full == base:
        return ""
    if full.startswith(base + "[") and full.endswith("]"):
        return full[len(base) + 1:-1]
    raise ValueError(f"Unexpected name {full} for {base}")


def export_run(model: VensimModel, run_id: str, bases: list[str], commands: list[str]):
    rows_year = []
    rows_var = []
    rows_element = []
    rows_value = []
    constants = []
    missing = []
    for base in bases:
        try:
            names = model.expand_var(base)
        except Exception as exc:
            missing.append({"variable": base, "stage": "expand", "error": str(exc)})
            continue
        if names == [base]:
            # expand_var returns the bare name both for scalars and for a failed lookup.
            pass
        for full in names:
            try:
                times, values = model.get_series(run_id, full, maxn=64)
            except Exception as exc:
                missing.append({"variable": base, "name": full, "stage": "read", "error": str(exc)})
                continue
            element = split_name(full, base)
            raw_times = [float(t) for t in times]
            raw_values = [float(np.float32(v)) for v in values]
            record = {
                "run_id": run_id, "variable": base, "element": element,
                "times": raw_times, "n": len(raw_times),
            }
            if len(raw_times) != 40 or (base == "Hourly exported electricity" and element.endswith("Import")):
                constants.append({**record, "values": raw_values})
            for time, value in zip(raw_times, raw_values):
                rows_year.append(time)
                rows_var.append(base)
                rows_element.append(element)
                rows_value.append(value)
    return {
        "commands": commands,
        "rows": (rows_var, rows_element, rows_year, rows_value),
        "constants": constants,
        "missing": missing,
    }


def write_parquet(path: Path, frames: list[tuple[str, dict]]):
    variables = []
    elements = []
    years = []
    values = []
    run_ids = []
    for run_id, frame in frames:
        variables.extend(frame["rows"][0])
        elements.extend(frame["rows"][1])
        years.extend(frame["rows"][2])
        values.extend(frame["rows"][3])
        run_ids.extend([run_id] * len(frame["rows"][0]))
    table = pa.table({
        "run_id": pa.array(run_ids, type=pa.string()),
        "variable": pa.array(variables, type=pa.string()),
        "element": pa.array(elements, type=pa.string()),
        "year": pa.array(np.asarray(years, dtype=np.float32), type=pa.float32()),
        "value": pa.array(np.asarray(values, dtype=np.float32), type=pa.float32()),
    })
    pq.write_table(table, path)


def first_divergence(exported: Path):
    reference = pq.read_table(REFERENCE, filters=[("run_id", "=", "01_base")]).to_pandas()
    native = pq.read_table(exported, filters=[("run_id", "=", "01_base")]).to_pandas()
    reference["year"] = reference["year"].astype(np.float32)
    native["value"] = native["value"].astype(np.float32)
    reference["value"] = reference["value"].astype(np.float32)
    key = ["variable", "element", "year"]
    merged = reference.merge(native, on=key, how="outer", suffixes=("_ref", "_nat"), indicator=True)
    mismatch = merged[merged["_merge"] != "both"]
    both = merged[merged["_merge"] == "both"]
    differ = both[both["value_ref"].to_numpy() != both["value_nat"].to_numpy()]
    order = ["year", "variable", "element"]
    first = None
    if len(mismatch):
        row = mismatch.sort_values(order).iloc[0]
        first = {"kind": "coverage", "variable": row["variable"], "element": row["element"],
                 "year": float(row["year"]) if row["year"] == row["year"] else None,
                 "side": row["_merge"]}
    elif len(differ):
        row = differ.sort_values(order).iloc[0]
        first = {"kind": "value", "variable": row["variable"], "element": row["element"],
                 "year": float(row["year"]), "reference": float(row["value_ref"]),
                 "native": float(row["value_nat"])}
    return {
        "reference_rows": int(len(reference)),
        "native_rows": int(len(native)),
        "coverage_gaps": int(len(mismatch)),
        "value_mismatches": int(len(differ)),
        "first": first,
    }


def run_sequence(process_name: str, run_ids: list[str], spec: dict, bases: list[str]):
    work = OUT / process_name
    if work.exists():
        shutil.rmtree(work)
    model = VensimModel(prepare_model(), dll_path=DLL, work_dir=work)
    frames = []
    controls = []
    missing = []
    applied = []
    by_id = {item["id"]: item for item in spec["runs"]}
    for run_id in run_ids:
        inputs = by_id[run_id]["inputs"]
        commands = [
            "SIMULATE>SETVAL|INITIAL TIME=2011",
            "SIMULATE>SETVAL|FINAL TIME=2050",
            "SIMULATE>SETVAL|TIME STEP=1",
            f"SIMULATE>RUNNAME|{run_id}",
        ]
        model.set_time(2011, 2050, 1)
        saveper = "SIMULATE>SETVAL|SAVEPER=1"
        try:
            model.cmd(saveper)
            commands.append(saveper + " -> rc=1")
        except RuntimeError as exc:
            commands.append(saveper + " -> rejected: " + str(exc).splitlines()[-1])
        model.cmd(f"SIMULATE>RUNNAME|{run_id}")
        for name, value in inputs.items():
            command = f"SIMULATE>SETVAL|{setval_name(name)}={value}"
            commands.append(command)
            model.cmd(command)
        model.cmd("MENU>RUN|O")
        commands.append("MENU>RUN|O")
        control_values = {}
        for name in CONTROLS:
            times, values = model.get_series(run_id, name, maxn=64)
            control_values[name] = {"times": [float(t) for t in times], "values": [float(np.float32(v)) for v in values]}
        controls.append({"run_id": run_id, "controls": control_values, "commands": commands})
        frame = export_run(model, run_id, bases, commands)
        frames.append((run_id, frame))
        missing.extend(frame["missing"])
        applied.append({"run_id": run_id, "requested": inputs, "commands": commands, "controls": control_values})
    return frames, applied, missing


def main() -> None:
    spec = json.loads(INPUTS.read_text(encoding="utf-8"))
    outputs = list(spec["output_bases"])
    bases = outputs + [name for name in DIAGNOSTICS if name not in outputs]
    OUT.mkdir(parents=True, exist_ok=True)
    phase = sys.argv[1] if len(sys.argv) > 1 else "base"
    if phase == "base":
        frames, applied, missing = run_sequence("process-base", ["01_base"], spec, bases)
        output_names = set(outputs)
        diagnostic_names = set(DIAGNOSTICS)
        def keep(frame, names):
            chosen = [i for i, variable in enumerate(frame["rows"][0]) if variable in names]
            rows = tuple([frame["rows"][k][i] for i in chosen] for k in range(4))
            return {**frame, "rows": rows}
        outputs_path = OUT / "outputs-01-base.parquet"
        diagnostics_path = OUT / "diagnostics-01-base.parquet"
        write_parquet(outputs_path, [(run_id, keep(frame, output_names)) for run_id, frame in frames])
        write_parquet(diagnostics_path, [(run_id, keep(frame, diagnostic_names)) for run_id, frame in frames])
        (OUT / "constants-01-base.json").write_text(
            json.dumps([item for _, frame in frames for item in frame["constants"]], indent=2),
            encoding="utf-8")
        (OUT / "applied-01-base.json").write_text(json.dumps(applied, indent=2), encoding="utf-8")
        status = {"missing": missing, "diagnostics": sorted(diagnostic_names),
                  "comparison": first_divergence(outputs_path)}
        (OUT / "status-01-base.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        print(json.dumps(status["comparison"], indent=2))
    else:
        raise SystemExit(f"Unknown phase {phase}")


if __name__ == "__main__":
    main()
