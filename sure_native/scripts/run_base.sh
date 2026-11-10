#!/bin/bash
# Traduce SURE.mdl, simula il Base 2011-2050 e confronta con il riferimento Vensim.
set -e
cd /c/Users/matteo.palucci/SEneCa-native-runs
SN=/c/Users/matteo.palucci/SEneCa-v8/sure_native
PY=/c/Users/matteo.palucci/SEneCa-v8/.venv/Scripts/python.exe
julia --startup-file=no --project=$SN $SN/scripts/translate.jl vensim/SURE.mdl SUREGenerated.jl
julia --startup-file=no --project=$SN $SN/scripts/compare_reference.jl SUREGenerated.jl vensim/inputs vensim/ref_base.ref vensim/calibration.out 2050 base_report.tsv julia_base.ref | grep -E "uscita|serie conf|compil|simulaz|senza corr|ERROR|allocazione"
$PY $SN/scripts/analyze_diff.py vensim/ref_base.ref julia_base.ref ${1:-1e-6} ${2:-40}
