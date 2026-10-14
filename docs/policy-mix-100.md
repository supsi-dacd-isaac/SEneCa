# Policy mix e incertezza: 100 campioni e 9 KPI

La specifica è il foglio `Exploratory analysis` di
`Input and Output Streamlit.xlsx`: sette leve binarie (righe 2–8), 17 parametri
incerti (righe 13–29), 100 campioni (H7), nove indicatori (righe 32–40).
I test confrontano questi input con la configurazione del runner.

Ogni policy mix usa gli stessi 100 campioni Latin hypercube, con marginali
uniformi negli intervalli del foglio e seme `20261004`. Il nuovo disegno a 100
righe sostituisce quello a 50 di `data-v1.1.0`; non lo estende conservando
campioni che non formerebbero più un LHS di 100 punti. I valori effettivi e il
checksum sono salvati nella release. Un campione diverso o incompleto viene
rifiutato, senza rigenerarlo silenziosamente.

Il nono KPI, **Domanda coperta dal FV autoconsumato**, è calcolato al 2050:

```text
Total PV electricity SC [GWh]
──────────────────────────────────────────────────────────
SUM(Total annual demand Districts [kWh]) / 1,000,000
```

Il dato è salvato come frazione e mostrato in percentuale. Il denominatore
comprende tutti gli otto distretti, sommati prima della divisione. Non si
calcola la media delle percentuali distrettuali né il rapporto tra
autoconsumo e produzione FV. Le due energie aggregate sono conservate nel
Parquet per verificare il calcolo. Domanda nulla, dati non finiti o copertura
oltre il limite fisico interrompono la generazione.

Gli altri otto indicatori conservano la definizione precedente: tre GMD,
costo medio per abitazione, produzione FV, consumo netto specifico,
emissioni cumulate e spesa cantonale cumulata 2025–2050. La pagina mostra
tutti e nove nei boxplot, nel radar e nella classifica pesata; include anche
mediana, P10–P90 e valori medi nella classifica scaricabile.

## Rigenerazione e verifiche

Usare un checkout dedicato sul branch `policy-mix-100`, dal commit main
`fc2ff42ab9ffd7736dbe4ebc40b5711f36b6d359`, con il runtime Julia bloccato.
Il runner richiede 32 core fisici e un limite di memoria di 128 GiB:

```sh
sh scripts/prepare_policy_mix.sh policy-mix-100-001
```

Passare `SURE_SOURCE_COMMIT` con il commit del checkout e montare `/app`,
`/runtime` e `/runs` come descritto in `julia-production.md`. Il processo va
avviato in un container distaccato. La webapp in produzione usa un'immagine
indipendente e continua a servire i dati già rilasciati.

Il runner verifica che equazioni, calibrazione e coordinate siano identiche
a `data-v1.1.0`, poi esegue test mirati e 418 confronti Python–Julia, inclusi
tutti i 100 campioni con politiche minime e massime. Confronta anche i nove
KPI derivati, verifica isolamento degli stati e un lotto di 100 scenari
eseguito in serie e con 32 processi.

La rigenerazione comprende 12.800 scenari esplorativi e tutte le altre
sezioni: 14.579 configurazioni, 14.571 simulazioni dopo la deduplicazione.
La copertura completa, l'identità dei parametri, i valori finiti, i vincoli
fisici e l'assenza di compilazioni dopo il riscaldamento sono condizioni
necessarie per pubblicare. I risultati e i log rimangono sotto
`/ssd2/elettra/seneca-runs/<run-id>`.

Il run `policy-mix-100-002`, dal commit `bef0f55`, ha completato tutte le
14.571 simulazioni e l'audit il 14 ottobre 2026. I 418 confronti e il confronto
esatto seriale/parallelo sono passati. I sette Parquet delle altre sezioni
sono byte-identici a `data-v1.1.0`; equazioni, input e calibrazione restano
invariati. Tempi, checksum e copertura sono nel
[rapporto completo](../benchmarks/sure-production/POLICY_MIX_RESULTS.md).

Le versioni sono `data-v1.2.0` e `v0.3.0`. Prima del deploy, le immagini AMD64 e
ARM64 devono superare i confronti numerici, i test della pagina e una
simulazione reale. Conservare l'immagine `v0.2.0` per il rollback.

La stessa release anticipa la compilazione Julia all'avvio del server.
`streamlit run server.py` esegue una simulazione completa prima di accettare
sessioni e richieste di salute. La pagina live usa la stessa risorsa globale,
con richieste serializzate e reset degli stati per ciascuno scenario. I test
verificano un unico worker per sessioni concorrenti, chiusura e propagazione
degli errori, avvio senza browser e riuso del processo senza compilazione alla
prima simulazione dell'utente, su entrambe le architetture delle immagini.

La pagina live mostra inoltre l'avanzamento per fasi effettive: preparazione,
simulazione, estrazione e verifica. Nella fase di estrazione segnala l'anno
elaborato; non stima il tempo rimanente e non indica l'avanzamento annuale del
solutore. I messaggi sono opzionali e non modificano modello, stati o risultati.
Il batch a 32 processi continua sul proprio checkout congelato.
