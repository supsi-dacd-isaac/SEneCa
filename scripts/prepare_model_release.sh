#!/bin/sh
# Validate and regenerate canonical v8 in the pinned runtime.
set -eu
run=${1:?Supply a new run identifier}
case "$run" in *[!a-zA-Z0-9_-]*) echo 'Invalid run identifier' >&2; exit 1;; esac
root=/runs/$run
mkdir "$root"
export PYTHONPATH=/app SURE_VARIANT=v8 PYTHONHASHSEED=0
monitor=
finish() {
    code=$?
    trap - EXIT
    echo "$code" > "$root/exit"
    if [ -n "$monitor" ]; then kill "$monitor" 2>/dev/null || true; fi
    exit "$code"
}
trap finish EXIT
echo setup > "$root/stage"
python -u - "$root" <<'PY' > "$root/monitor.log" 2>&1 &
import datetime, json, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
group = pathlib.Path('/sys/fs/cgroup')
with (root/'resources.jsonl').open('w', buffering=1) as out:
    while not (root/'exit').exists():
        row = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'phase': (root/'stage').read_text().strip(),
               'memory_current': int((group/'memory.current').read_text()),
               'memory_max': (group/'memory.max').read_text().strip(),
               'cpu_set': (group/'cpuset.cpus.effective').read_text().strip()}
        out.write(json.dumps(row)+'\n')
        time.sleep(5)
PY
monitor=$!
printf '%s\n' "${SURE_SOURCE_COMMIT:?Pass the host checkout commit}" > "$root/source-commit"
# Inputs must be staged explicitly: fetching the pinned previous release here
# would overwrite the new model's native inputs before its data release exists.
echo samples > "$root/stage"
python - "$root" <<'PY'
import shutil, sys
import pandas as pd
from pathlib import Path
from pv_batteries import exploratory_config as cfg
from sure_julia.common import digest, dump, read
root=Path(sys.argv[1])
shutil.copy2(cfg.SAMPLES_PATH, root/'previous-uncertainty-samples.parquet')
samples=pd.read_parquet(cfg.SAMPLES_PATH)
cfg.validate_samples(samples)
pd.testing.assert_frame_equal(samples, cfg.build_uncertainty_samples(), check_exact=True)
inputs = [cfg.ROOT/'Vensim'/f'{name}.vdfx' for name in
          ('EVinput', 'HPinput', 'Input Hour Factors', 'Input2011', 'InputRenovation', 'PVinput')]
if any(not p.is_file() or not p.stat().st_size for p in inputs):
    raise ValueError('Stage all six native v8 input files before running')
native = {p.name:digest(p) for p in inputs}
expected = read(cfg.ROOT/'docs/validation/v8-inputs.json')
if native != expected['native_inputs'] or digest(cfg.SAMPLES_PATH) != expected['uncertainty_samples_sha256']:
    raise ValueError('Native inputs or uncertainty draws differ from reviewed v8 inputs')
dump(root/'native-inputs.json', native)
dump(root/'sampling.json', {'n_samples':cfg.N_SAMPLES,'seed':cfg.SAMPLE_SEED,
    'method':'Latin hypercube with uniform marginals', 'same_draws_for_every_policy':True,
    'previous_sample_sha256':digest(root/'previous-uncertainty-samples.parquet'),
    'sample_sha256':digest(cfg.SAMPLES_PATH), 'parameters':cfg.UNCERTAINTY_BOUNDS,
    'workbook_sha256':digest(cfg.ROOT/'Input and Output Streamlit.xlsx')})
PY
echo unit > "$root/stage"
python -m unittest discover -s tests -p 'test_exploratory*.py' -v > "$root/unit-exploratory.log" 2>&1
python -m unittest discover -s tests -p test_sure_production.py -v > "$root/unit-production.log" 2>&1
python -m unittest discover -s tests -p test_stock_limits.py -v > "$root/unit-physical.log" 2>&1
echo source-check > "$root/stage"
python -m sure_julia.pv_budget --check > "$root/source-check.log" 2>&1
python scripts/import_calibration.py --check > "$root/calibration-check.log" 2>&1
echo build > "$root/stage"
/opt/translator/bin/python -u -m sure_julia.build /app/sure_julia/generated > "$root/build.log" 2>&1
julia --startup-file=no --project=sure_julia/julia tests/parametric_api.jl sure_julia/generated > "$root/parameter-api.log" 2>&1
echo targeted > "$root/stage"
python -u -m sure_julia.targeted "$root/targeted" > "$root/targeted.log" 2>&1
echo full-validation > "$root/stage"
python -u -m sure_julia.validation "$root/validation" --workers 32 --targeted "$root/targeted" > "$root/validation.log" 2>&1
echo state-isolation > "$root/stage"
python -u -m sure_julia.validation "$root/validation" --repeats > "$root/repeats.log" 2>&1
echo certification > "$root/stage"
python -m sure_julia.validation "$root/validation" --certify --targeted "$root/targeted" > "$root/certification.log" 2>&1
echo calibration-curves > "$root/stage"
python scripts/export_calibration_plot.py content/system_dynamics/plots_data/calibration_sim_adoptions_v8.csv --baseline "$root/validation/base" > "$root/calibration-curves.log" 2>&1
python -m unittest discover -s tests -v > "$root/unit-full.log" 2>&1
echo pilot-parallel > "$root/stage"
python -u -m sure_julia.batch "$root/pilot-parallel" --pilot --workers 32 --validation "$root/validation" > "$root/pilot-parallel.log" 2>&1
echo pilot-serial > "$root/stage"
python -u -m sure_julia.batch "$root/pilot-serial" --pilot --workers 1 --validation "$root/validation" > "$root/pilot-serial.log" 2>&1
echo pilot-comparison > "$root/stage"
python - "$root" <<'PY'
import sys
from sure_julia.batch import compare_pilots
from pathlib import Path
r = Path(sys.argv[1])
compare_pilots(r/'pilot-serial', r/'pilot-parallel', r/'pilot-comparison.json')
PY
echo full-regeneration > "$root/stage"
python -u -m sure_julia.batch "$root/full" --workers 32 --validation "$root/validation" > "$root/full.log" 2>&1
echo section-equivalence > "$root/stage"
python -u -m sure_julia.python_batch "$root/section-equivalence" --workers 32 --verify-julia > "$root/section-equivalence.log" 2>&1
echo section-audit > "$root/stage"
python scripts/audit_v8_sections.py precomputed "$root/section-equivalence" "$root/full" "$root/section-audit.json" > "$root/section-audit.log" 2>&1
echo native-input-staging > "$root/stage"
python - "$root" <<'PY'
from pathlib import Path
import shutil, sys
from sure_julia.common import ROOT, digest, read
destination=Path(sys.argv[1])/'full/release/Vensim'
destination.mkdir(parents=True, exist_ok=True)
for name, expected in read(ROOT/'docs/validation/v8-inputs.json')['native_inputs'].items():
    source=ROOT/'Vensim'/name
    if digest(source) != expected:
        raise ValueError('Native source changed during generation')
    shutil.copy2(source, destination/name)
    if digest(destination/name) != expected:
        raise ValueError('Native input staging failed')
PY
echo final-audit > "$root/stage"
python scripts/verify_production_data.py "$root/full" "$root/data-audit.json" --resources "$root/resources.jsonl" > "$root/data-audit.log" 2>&1
echo ready-for-release > "$root/stage"
