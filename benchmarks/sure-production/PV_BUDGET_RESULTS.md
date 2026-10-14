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

## Dati candidati completati e arresto prima del rilascio

Esecuzione Elettra: `/ssd2/elettra/seneca-runs/pv-budget-003`.
Le **8.171 simulazioni distinte**, che coprono **8.179 configurazioni**, sono
terminate senza errori. Il batch, inclusi avvio, riscaldamento e
consolidamento, ha impiegato **4.367,69 s (72 minuti e 48 secondi)** con 32
worker. Il picco campionato di memoria del container è stato **43,21 GiB**,
entro il limite di 128 GiB. Nessuna compilazione dopo il riscaldamento.

L'audit finale è superato: nove Parquet applicativi, provenienza di tutti gli
8.171 scenari, parametri completi, anni, schemi, Float64, assenza di valori
mancanti/non finiti e checksum verificati. La copertura comprende 324
configurazioni FV/batterie, 1.215 risanamento, 144 veicoli, 96 elettricità e
6.400 esplorative. I 50 campioni d'incertezza originali sono invariati.

Tutti gli scenari superano i controlli fisici. Nessun peso GMD finale è negativo
oltre l'errore numerico: il minimo al 2050 è circa `-1,62e-14`; 2.436 scenari
presentano soltanto residui di arrotondamento. La definizione GMD preesistente
esclude quei pesi negativi e li registra nell'audit; i valori grezzi della
simulazione non vengono modificati. Il rapporto con tempi e checksum è
`pv-budget-data-audit-20261014.json`.
`pv-budget-full-physical-20261014.json` riporta gli estremi dei 18 controlli
sull'intero batch e gli identificativi degli scenari corrispondenti. Su tutti
gli anni, i minimi sono `-7,11e-15` per Heating Solution e `-3,23e-14` per
Annual archetypes; tutti i controlli rimangono entro le tolleranze originali.

I dati candidati si trovano su Elettra in
`/ssd2/elettra/seneca-runs/pv-budget-003/full/release/`. Il nome della
directory è quello di staging del generatore: non è una release pubblicata.

La procedura è terminata con codice 0 e stato `awaiting-native-vensim-review`.
Il pacchetto del collega è
`/ssd2/elettra/seneca-runs/pv-budget-003/native-handoff.zip` (136.953.160 byte),
SHA256 `c67f8bc4e6d543840efaa8f016a064e2729acf04a6d2f2736d7aea4ac858c287`.
Contiene sorgente corretto, input completi, calibrazione, schema degli output,
rapporti e riferimenti numerici per le prove iniziali. I file esterni nativi
della v6 rimangono quelli in possesso del collega.
La copia locale in `dist/julia-production/pv-budget/native-handoff.zip` ha
lo stesso checksum; verificati tutti i 659 file elencati nel manifest.
L'esito è conservato in `pv-budget-handoff-20261014.json`.

La preparazione si era fermata prima di release, merge e deploy. Il
2026-10-14 il responsabile ha riferito primi test Vensim senza problemi e ha
autorizzato la pubblicazione di `data-v1.1.0`, `v0.2.0` e il deploy anche in
produzione su Elettra. Non sono ancora disponibili rapporti nativi completi:
l'equivalenza con il motore Vensim non è dichiarata. Le istruzioni per
proseguire il confronto sono in `PV_BUDGET_VENSIM.md`.
