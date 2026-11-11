#!/bin/bash
# Traduce SURE.mdl, simula il Base 2011-2050 e confronta con il riferimento Vensim.
set -e
cd /c/Users/matteo.palucci/SEneCa-native-runs
RUN=${RUN:-vensim}           # cartella della corsa Vensim (modello, input, riferimento)
GEN=${GEN:-SUREGenerated.jl}  # modulo Julia generato
OUT=${OUT:-.}                 # cartella per l'uscita Julia e il rapporto
SN=/c/Users/matteo.palucci/SEneCa-v8/sure_native
PY=/c/Users/matteo.palucci/SEneCa-v8/.venv/Scripts/python.exe
julia --startup-file=no --project=$SN $SN/scripts/translate.jl $RUN/SURE.mdl $GEN
julia --startup-file=no --project=$SN $SN/scripts/compare_reference.jl $GEN $RUN/inputs $RUN/ref_base.ref $RUN/calibration.out 2050 $OUT/base_report.tsv $OUT/julia_base.ref | grep -E "uscita|serie conf|compil|simulaz|senza corr|ERROR|allocazione"
$PY $SN/scripts/analyze_diff.py $RUN/ref_base.ref $OUT/julia_base.ref ${1:-1e-6} ${2:-40}
