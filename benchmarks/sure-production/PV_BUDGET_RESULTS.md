# SURE v6 con budget condiviso delle adozioni PV

Revisione: `sure-v6-pv-budget-2`. Branch: `julia-production`.
Sorgente v6 di partenza: `9080f62`. Il sorgente originale è conservato.

## Verifiche concluse

- 318/318 scenari Python–Julia superati: 137 output e diagnostici,
  **1.995.907.920 valori**, tutti gli anni 2011–2050 e tutte le coordinate.
- 318/318 controlli fisici, energetici e degli avvisi superati per entrambi
  i motori. La v6 originale falliva i controlli fisici in 149 casi.
- Tolleranza di confronto invariata:
  `abs(J-P) <= 1e-10*max(1,S) + 1e-8*abs(P)`. Nessun dato escluso.
- Minimo degli stock di riscaldamento: circa `-7.11e-15`; minimo dei pesi
  Annual archetypes: circa `-1.53e-14`. Sono residui numerici entro i controlli
  originali; nessuno stock viene azzerato dopo l'integrazione.
- 22 test unitari superati. Superati anche i test mirati del traduttore:
  EXCEPT, indici, dati esterni, stati/ritardi, semantica e allocazione.
- Linux AMD64 e ARM64: simulazioni base/high/regressione e interfaccia
  Streamlit superate. Il codice Julia generato ha lo stesso checksum sulle
  due architetture. Nessuna immagine pubblicata.
- Isolamento superato: base → high → base identico, processi nuovi identici,
  confronto con la potatura applicativa identico, richieste concorrenti
  isolate e recupero esatto dopo l'arresto del worker. Nessuna compilazione
  dopo il riscaldamento.
- Piloti seriale/parallelo: 100/100 scenari identici nei valori e nei file
  Parquet. Totale seriale 1.281,98 s; totale parallelo 211,26 s, entrambi
  inclusivi di avvio e riscaldamento. A caldo, mediana per scenario 11,51 s
  in seriale (integrazione 8,67 s, estrazione 2,75 s) e 15,45 s con 32
  processi concorrenti. Sono carichi del batch, non misure della latenza web.

Il rapporto completo è `pv-budget-validation-20261014.json`; il riepilogo
delle architetture è `pv-budget-architecture-ci-20261014.json`. La traccia
`pv-budget-base-trace-20261014.json` riporta tutti i 40 input e tutti gli anni
per la cella originariamente problematica: con disponibilità zero dal 2038,
il flusso accettato e lo stock restano esattamente zero fino al 2050.
`pv-budget-pilot-20261014.json` conserva tempi, intervalli, memoria per
worker e identità delle prove di isolamento e della certificazione.

## Correzione e riproducibilità

`sure_julia/pv_budget.py` genera le due copie MDL corrette e il riferimento
Python. Le dieci clausole delle sei richieste originali restano identiche;
1.543 altri componenti Python restano invariati. Le 56 somme Julia delle
richieste mantengono gli stessi AST e criteri di riduzione verificati.

La prima revisione esponeva un fattore adimensionale con una convenzione
discontinua in 0/0. Nella high, 13 celle del solo fattore divergevano quando
una richiesta era zero in un motore e circa 1e-18–1e-24 nell'altro; budget,
flussi accettati e controlli fisici concordavano. La revisione 2 espone la
quantità accettata `MIN(disponibilità, richiesta totale)` e ripartisce tale
quantità proporzionalmente. La diagnosi originale è conservata in
`pv-budget-revision-1-diagnosis.json`. Non sono state allargate le tolleranze.

## Preparazione dei dati e arresto prima del rilascio

Esecuzione Elettra: `/ssd2/elettra/seneca-runs/pv-budget-003`.
Validazione, isolamento e piloti sono terminati. Sono in corso le 8.171
simulazioni distinte che coprono 8.179 configurazioni. Il container è
limitato a 32 core e 128 GiB. La stima dal pilota è 70–90 minuti per il batch,
seguiti dall'audit e dalla creazione del pacchetto nativo.

La procedura si arresta dopo l'audit dei dati e la preparazione del pacchetto
per il collega, con stato `awaiting-native-vensim-review`. **Nessuna release,
merge o deploy autorizzati prima della verifica nativa Vensim.** Il pin
applicativo dei dati resta `data-v1.0.0`. Le istruzioni del collega sono in
`PV_BUDGET_VENSIM.md`; l'equivalenza con il motore Vensim non è dichiarata.
