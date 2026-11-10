#!/bin/bash
# Estrae gli input Float64 dai .vdfx e completa le serie ambigue (riferimento: corsa Base).
set -e
cd /c/Users/matteo.palucci/SEneCa-native-runs
SN=/c/Users/matteo.palucci/SEneCa-v8/sure_native
PY=/c/Users/matteo.palucci/SEneCa-v8/.venv/Scripts/python.exe
for f in PVinput HPinput EVinput InputRenovation Input2011 "Input Hour Factors"; do
  $PY $SN/reference/vdfx_reference.py "vensim/$f.vdfx" "vensim/$f.tab" "vensim/inputs/$f" > /dev/null
done
julia --startup-file=no --project=$SN $SN/scripts/translate.jl vensim/SURE.mdl SUREGenerated.jl
julia --startup-file=no --project=$SN $SN/scripts/patch_inputs.jl SUREGenerated.jl vensim/inputs vensim/ref_base.ref vensim/SURE.mdl
julia --startup-file=no --project=$SN $SN/scripts/resolve_ambiguous.jl SUREGenerated.jl vensim/inputs vensim/ref_base.ref vensim/calibration.out 2050
