# sure_native: traduzione diretta Vensim → Julia

Traduttore del modello SURE da `.mdl` a un modulo Julia, senza PySD. L'unico
riferimento di validazione è Vensim DSS. Il piano è nella pagina Notion
"Piano di traduzione Vensim → Julia senza PySD".

## Componenti

| File | Ruolo |
|---|---|
| `src/parser.jl` | lettura del `.mdl`: blocchi, subscript, `:EXCEPT:`, dati, lookup, espressioni |
| `src/model.jl` | rappresentazione intermedia: dimensioni, domini delle definizioni, legami dei subscript, ordinamento |
| `src/codegen.jl` | generazione del modulo Julia (un ciclo esplicito per definizione) |
| `src/runtime.jl` | funzioni con la semantica di Vensim (`ZIDZ`, lookup, dati, `ALLOCATE BY PRIORITY`) |
| `src/simulate.jl` | esecuzione: dati, modifiche da file `.out`/`.cin`, ciclo di Eulero |
| `reference/vdfx_reference.py` | riferimento Vensim in Float64 da `.vdfx` + export `.tab` |
| `scripts/translate.jl` | `.mdl` → modulo Julia |
| `scripts/compare_reference.jl` | simulazione e confronto con il riferimento |

## Semantica verificata sul riferimento Vensim

- Vensim memorizza in **Float32** tutti gli ingressi numerici (costanti, numeri
  nelle equazioni, punti dei lookup, dati letti dai `.vdfx`, valori dei file di
  calibrazione) e calcola in Float64. Il codice generato fa lo stesso.
- `DELAY FIXED` con ritardo inferiore al passo vale un passo (`max(1, round(ritardo/dt))`).
- `SMOOTH`: livello con valore iniziale pari all'ingresso, tasso `(ingresso - livello)/tempo`.
- Dati `:RAW:` fuori dai punti disponibili: `:NA:`. Altri dati: interpolazione e
  valore costante fuori dall'intervallo.
- `ALLOCATE BY PRIORITY`: Julia calcola la soluzione esatta; Vensim usa un
  metodo iterativo che lascia un residuo sul bilancio (fino a 2,5e-6 relativo
  all'offerta oraria nel Base).

## Riferimento Vensim

La DLL di Vensim su questo PC risponde -6 a ogni comando (errore 977 nel log), e
gli export testuali di Vensim scrivono 6 cifre significative. Le corse si fanno
quindi con uno script di comandi (`vendss64.exe base.cmd`), e
`vdfx_reference.py` legge i valori Float64 direttamente dai blocchi del `.vdfx`.
Accetta un blocco solo se tutti i suoi valori, scritti con 6 cifre, coincidono
con l'export di Vensim. Le serie senza un blocco univoco restano a 6 cifre e
sono confrontate con la tolleranza larga.

## Webapp e release

1. Build per la webapp (worker JSON-lines compatibile con `sure_julia.runtime`):
   `python -m sure_native.build_webapp RUN_DIR GENERATED.jl` scrive
   `sure_native/generated`, che è versionato byte per byte (`-text`).
2. Certificato: `sure_native/validation/webapp_check.py` (scenari attraverso il
   backend della webapp contro i riferimenti Vensim) e
   `sure_native/validation/webapp_certificate.py` (determinismo, isolamento,
   ripresa dopo crash, nessuna compilazione dopo il warm-up).
3. Scenari: `PYTHONUTF8=1 python -m sure_julia.batch RUN_DIR --workers 4
   --validation VALIDATION_DIR`, poi `python scripts/verify_production_data.py
   RUN_DIR audit.json`.
4. Release dati: `python scripts/data_release.py pack --tag data-vX.Y.Z
   --source-commit SHA --root CARTELLA` con `precomputed/`, `provenance/` di
   `RUN_DIR/release` e i sei `Vensim/*.vdfx`; vedi
   [docs/data-releases.md](../docs/data-releases.md).

L'immagine di produzione (`Dockerfile`) usa questo build; durante la build
`scripts/verify_julia_release.py` rifiuta dati generati da un altro build.
