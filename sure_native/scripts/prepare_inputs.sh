#!/bin/bash
# Estrae gli input Float64 dai .vdfx e completa le serie ambigue (riferimento: corsa Base).
set -e
cd /c/Users/matteo.palucci/SEneCa-native-runs
RUN=${RUN:-vensim}           # cartella della corsa Vensim (modello, input, riferimento)
GEN=${GEN:-SUREGenerated.jl}  # modulo Julia generato
OUT=${OUT:-.}                 # cartella per l'uscita Julia e il rapporto
SN=/c/Users/matteo.palucci/SEneCa-v8/sure_native
PY=/c/Users/matteo.palucci/SEneCa-v8/.venv/Scripts/python.exe
$PY $SN/reference/vdfx_reference.py "$RUN/ref_base.vdfx" "$RUN/ref_base.tab" "$RUN/ref_base.ref" > /dev/null
for f in PVinput HPinput EVinput InputRenovation Input2011 "Input Hour Factors"; do
  $PY $SN/reference/vdfx_reference.py "$RUN/$f.vdfx" "$RUN/$f.tab" "$RUN/inputs/$f" > /dev/null
done
julia --startup-file=no --project=$SN $SN/scripts/translate.jl $RUN/SURE.mdl $GEN
julia --startup-file=no --project=$SN $SN/scripts/patch_inputs.jl $GEN $RUN/inputs $RUN/ref_base.ref $RUN/SURE.mdl
julia --startup-file=no --project=$SN $SN/scripts/resolve_ambiguous.jl $GEN $RUN/inputs $RUN/ref_base.ref $RUN/calibration.out 2050
