# Sorgente del build nativo

- `SURE.mdl`: il modello Vensim (sha256 `4ec941ec…`) da cui è tradotto
  `sure_native/generated` e su cui la traduzione è validata con Vensim DSS
  (76 scenari), con la calibrazione dell'11 novembre 2026 (`calibration.out`).
- `Vensim/SURE.mdl` resta la sorgente della traduzione PySD v8 (release `v0.6.0`).

Le impronte di entrambi i file sono in `sure_native/generated/build.json` (`sources`).
