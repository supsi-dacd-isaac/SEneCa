#!/bin/sh
# Run inside the pinned Elettra container. This script never publishes/deploys.
set -eu
run=${1:?Supply a new run identifier, e.g. pv-budget-001}
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
git -c safe.directory=/app rev-parse HEAD > "$root/source-commit"
if [ -d /app/sure_julia/generated ]; then
    mv /app/sure_julia/generated "$root/previous-generated"
fi
echo source-check > "$root/stage"
python -m sure_julia.pv_budget --check > "$root/source-check.log" 2>&1
echo unit > "$root/stage"
python -m unittest discover -s tests -p test_stock_limits.py -v > "$root/unit-stock.log" 2>&1
python -m unittest discover -s tests -p test_sure_production.py -v > "$root/unit-production.log" 2>&1
echo build > "$root/stage"
/opt/translator/bin/python -u -m sure_julia.build /app/sure_julia/generated > "$root/build.log" 2>&1
echo targeted > "$root/stage"
python -u -m sure_julia.targeted "$root/targeted" > "$root/targeted.log" 2>&1
echo smoke > "$root/stage"
python -u -m sure_julia.validation "$root/smoke" --workers 4 --cases base high regression_negative_stock sample_min_12 > "$root/smoke.log" 2>&1
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
echo awaiting-native-vensim-review > "$root/stage"
