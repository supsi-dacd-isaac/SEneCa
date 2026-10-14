#!/bin/sh
# Run in the pinned runtime on Elettra. Publication remains a separate step.
set -eu
run=${1:?Supply a new run identifier}
case "$run" in *[!a-zA-Z0-9_-]*) echo 'Invalid run identifier' >&2; exit 1;; esac
root=/runs/$run
mkdir "$root"
export PYTHONPATH=/app SURE_VARIANT=v6 PYTHONHASHSEED=0
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
python scripts/data_release.py fetch > "$root/data-fetch.log" 2>&1
python scripts/data_release.py verify >> "$root/data-fetch.log" 2>&1
echo samples > "$root/stage"
python - "$root" <<'PY'
import shutil, sys
from pathlib import Path
from pv_batteries import exploratory_config as cfg
from sure_julia.common import digest, dump
root=Path(sys.argv[1])
shutil.copy2(cfg.SAMPLES_PATH, root/'previous-uncertainty-samples.parquet')
samples=cfg.build_uncertainty_samples()
cfg.validate_samples(samples)
temporary=cfg.SAMPLES_PATH.with_suffix('.tmp.parquet')
samples.to_parquet(temporary,index=False)
temporary.replace(cfg.SAMPLES_PATH)
dump(root/'sampling.json', {'n_samples':cfg.N_SAMPLES,'seed':cfg.SAMPLE_SEED,
    'method':'Latin hypercube with uniform marginals', 'same_draws_for_every_policy':True,
    'previous_sample_sha256':digest(root/'previous-uncertainty-samples.parquet'),
    'sample_sha256':digest(cfg.SAMPLES_PATH), 'parameters':cfg.UNCERTAINTY_BOUNDS,
    'workbook_sha256':digest(cfg.ROOT/'Input and Output Streamlit.xlsx')})
PY
echo unit > "$root/stage"
python -m unittest discover -s tests -p 'test_exploratory*.py' -v > "$root/unit-exploratory.log" 2>&1
python -m unittest discover -s tests -p test_sure_production.py -v > "$root/unit-production.log" 2>&1
echo source-check > "$root/stage"
python -m sure_julia.pv_budget --check > "$root/source-check.log" 2>&1
echo build > "$root/stage"
/opt/translator/bin/python -u -m sure_julia.build /app/sure_julia/generated > "$root/build.log" 2>&1
python - "$root" <<'PY'
from pathlib import Path
import sys
from sure_julia.common import read, dump
previous=read('/app/provenance/build.json')['model']
current=read('/app/sure_julia/generated/build.json')
keys=['artifacts','sources','defaults','parameters','years','float','delay_policy','model_revision']
checks={key:previous[key]==current[key] for key in keys}
dump(Path(sys.argv[1])/'model-identity.json', {'pass':all(checks.values()),'checks':checks,
    'reference':'data-v1.1.0; equations, calibration and exported coordinates unchanged'})
if not all(checks.values()):
    raise ValueError('The policy-mix update unexpectedly changed the numerical model')
PY
echo targeted > "$root/stage"
python -u -m sure_julia.targeted "$root/targeted" > "$root/targeted.log" 2>&1
echo full-validation > "$root/stage"
python -u -m sure_julia.validation "$root/validation" --workers 32 --targeted "$root/targeted" > "$root/validation.log" 2>&1
echo state-isolation > "$root/stage"
python -u -m sure_julia.validation "$root/validation" --repeats > "$root/repeats.log" 2>&1
echo certification > "$root/stage"
python -m sure_julia.validation "$root/validation" --certify --targeted "$root/targeted" > "$root/certification.log" 2>&1
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
echo final-audit > "$root/stage"
python scripts/verify_production_data.py "$root/full" "$root/data-audit.json" --resources "$root/resources.jsonl" > "$root/data-audit.log" 2>&1
echo ready-for-release > "$root/stage"
