# SURE v8: validazione e rigenerazione del 4–5 novembre 2026

La revisione `sure-v8-nr-calendar-2` è stata tradotta in Julia 1.10.12 e
confrontata con PySD 3.14.3. Il dataset `data-v3.0.0` contiene tutti i risultati
v8 delle pagine ordinarie e dell'analisi di incertezza. Input e 53 assegnazioni
di calibrazione ricevuti il 30 ottobre sono invariati.

La correzione comune a Vensim, Python e Julia considera zero numerico gli
stock FV minori o uguali a `1e-10` nei due test di `PV removal fraction`.
Le tolleranze di confronto restano `atol_scale=1e-10`, `rtol=1e-8`; anni,
etichette e valori categorici devono coincidere esattamente.

| Controllo | Esito |
| --- | --- |
| Accettazione Python–Julia, 150 output e 40 parametri | 427/427 casi; 2.816.252.880 celle; nessun superamento della tolleranza |
| Sezioni ordinarie, confronto indipendente Python–Julia | 1.771 scenari, 1.779 configurazioni; 436.584.840 celle; nessun superamento |
| Store finali rispetto agli store Python corretti | 43.226.703 celle, incluse tutte le serie orarie; nessun superamento |
| Pilot seriale/parallelo | 100/100 casi: valori e file Parquet identici |
| Rigenerazione Julia completa | 14.571 simulazioni distinte, 14.579 configurazioni; nessun caso fallito |
| Incertezza e policy mix | 128 mix × gli stessi 100 campioni LHS della v7 = 12.800 nuovi risultati v8 |
| Controlli fisici | Stock e trasferimenti residenziali, calendario e FV non residenziale, bilancio energetico delle batterie superati |
| Isolamento | Baseline ripetuta, processi nuovi, concorrenza e recupero dopo crash superati |
| Test software e API Julia | 128 test Python e 20 controlli dei parametri superati |
| Curve di calibrazione | 150 output identici alla baseline Python validata; confronto Julia superato |

Il massimo rapporto errore/tolleranza nei confronti delle sezioni è
0,001176, cioè circa lo 0,118% del limite ammesso. Il batch Julia con 32
processi ha impiegato 7.917 secondi; il confronto indipendente delle sezioni
5.456 secondi. Il picco di memoria campionato del batch è 39,4 GiB.
Non è avvenuta compilazione JIT dopo il riscaldamento. Il controllo GMD
registra piccoli pesi negativi di arrotondamento in 5.348 scenari, con minimo
`-1.38e-14`; nessun peso negativo sostanziale è stato escluso.

## Confronto con lo ZIP ricevuto

L'anteprima del 2 novembre contiene sezioni ordinarie Python v8 anteriori alla
correzione dello zero numerico e risultati esplorativi Julia v7. Non è un
dataset uniforme v8 né un riferimento esportato dal motore Vensim nativo.

Nello store PV/batterie, 474 delle 1.244.160 celle superano la stretta
tolleranza se confrontate con l'anteprima precedente alla correzione.
Gli altri cinque store confrontati, compresi gli indici GMD e tutti i dati
orari dell'elettricità, restano entro tolleranza rispetto all'anteprima.
Il nuovo Python corretto e Julia coincidono entro tolleranza in ogni cella
pubblicata: le differenze dall'anteprima non sono state usate per allentare
il criterio di accettazione. Il rapporto delle sezioni riporta massimi per
variabile e checksum dei tre insiemi di dati.

I risultati dell'incertezza sono interamente ricalcolati; non vengono
conservati esiti v7. Sono conservati i campioni: 17 parametri, marginali
uniformi, seed 20261004, SHA-256
`d27dcf0c7e8d60b619f5a566ad6ea955eeba296344cc9f35b4f159519f543677`.

## Evidenze e limiti

- [Sorgenti e input ricevuti](v8-inputs.json).
- [Suite di accettazione e certificato](v8-validation-20261104.json).
- [Pilot seriale/parallelo](v8-pilot-20261104.json).
- [Confronto completo delle sezioni e dell'anteprima](v8-section-audit-20261105.json).
- [Copertura, checksum e audit dei dati](v8-data-audit-20261105.json).

La release dati incorpora la provenienza dei 14.571 scenari, il certificato
numerico, l'identità del modello, le curve di calibrazione verificate e
l'attestazione delle sezioni. Il codice numerico usato per la rigenerazione
è il commit `2b7b8677973ecea2c47e7e5f2dab255793dcb300`; i commit successivi
aggiungono audit, evidenze e preparazione della release senza cambiare le
equazioni o gli input.

Queste prove certificano l'accordo Python–Julia e i controlli fisici indicati.
Non certificano l'equivalenza con il motore Vensim nativo e non costituiscono
una nuova calibrazione scientifica. La build applicativa verifica inoltre
runtime, interfaccia e avvio HTTP separatamente su AMD64 e ARM64 prima della
pubblicazione dell'immagine.
