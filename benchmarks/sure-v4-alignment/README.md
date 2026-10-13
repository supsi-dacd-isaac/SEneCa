# Allineamento SURE v4 con Vensim — 13 ottobre 2026

## Verifica dell'archivio nativo del 13 ottobre

Verificato `native-results-20261013.zip`, SHA256
`2b587916c3d99cec015c2c7d1f18364c99b49f238d521a766c5539d365eb97c6`.
Il sorgente e i quattro file della prova coincidono con quelli locali; le
differenze di checksum dei file generati dipendono esclusivamente dai fine
riga Windows. Anche il checksum del generatore coincide convertendo LF in CRLF.
Rapporto e script nativi del collega sono nel commit `58d0d75` del branch
`vensim-native-alignment`. Lo ZIP resta fuori da Git.

- Il nuovo base Vensim riproduce tutte le **848.048 celle Float32** dell'archivio.
- Le serie grezze del test dei ritardi confermano la politica sincrona locale:
  per 0.01, 0.1, 1, 2 e 4 anni l'errore è esattamente zero. La lettura dopo
  l'aggiornamento sequenziale dello SMOOTH anticipa la serie di un passo e
  sbaglia di 5 nel test. «SMOOTH salvato spostato di un passo» nel rapporto
  nativo non significa leggere il nuovo stato durante l'assegnazione Euler.
- Rieseguito il base Python e Julia con i nove diagnostici aggiuntivi mancanti:
  **119 variabili, 5.477.880 valori**, confronto superato. I 110 output
  condivisi con l'esperimento precedente sono identici nei rispettivi motori.
- Rigiocati in Python e Julia i **11.520 vettori orari nativi**, con offerta,
  domanda e priorità esportate da Vensim. I due allocatori locali coincidono
  esattamente, anche nei 50 casi sintetici: **104.130 celle** confrontate.

Il replay isola una differenza reale dell'allocazione nativa, indipendente
dalla successiva retroazione del modello. Su 399 vettori orari il bilancio
Vensim supera persino il limite conservativo dovuto alla quantizzazione di
tutti gli ingressi e le uscite Float32. Lo scarto massimo è **0.01151854 GWh**,
e gli errori di bilancio hanno entrambi i segni.

In **53 punti anno/mese/ora** Vensim assegna zero a Import mentre il replay
assegna una quantità positiva. Tutti i 53 casi restano distinti considerando
l'incertezza degli ingressi esportati. Il primo è **2012, M6, H15**:
domanda residua 0.001918072 GWh, Import Vensim zero, incertezza conservativa
degli ingressi circa 0.000000505 GWh. Applicando l'equazione del prezzo SURE
alle due allocazioni si passa da **10 a 135.3812 CHF/MWh**. Sono prezzi orari
ricostruiti con l'equazione, non il prezzo annuo all'utente.

Il massimo scarto di bilancio è **2027, M10, H17**: Import nativo
0.011670238 GWh contro 0.000151696 GWh nel replay. Non è giustificato un taglio
fisso a 0.01: l'errore può essere in eccesso o in difetto, e Vensim salva anche
allocazioni positive dell'ordine di 1e-7.

I nuovi diagnostici mostrano anche piccoli scarti negli ingressi già nel 2011
e nei costi marginali: l'allocatore non è necessariamente l'unica causa di
ogni differenza numerica. Le quattro serie stagionali sono tutte zero sul
base; questo archivio non certifica il comportamento con PECC attivi.
Il replay usa ingressi esportati Float32, non gli ingressi interni del motore.

L'equivalenza completa con Vensim resta **non raggiunta**. Il passo successivo
è eseguire il candidato BY PRIORITY sui dieci scenari come prova diagnostica,
anche se il test statico stretto fallisce, seguendo [NATIVE_TEST.md](NATIVE_TEST.md).
Nessuna soglia è stata allargata e nessuna modifica è stata applicata alla webapp.

Il riepilogo versionato è [native-review-summary.json](native-review-summary.json).
Risultati completi: `dist/sure-alignment/20261013-native-review/review.json`,
con ingressi, log e checksum in `evidence.json`. Riproduzione in una nuova cartella:

```sh
dist/julia-repro/runtime/python-reference/bin/python -B -m scripts.sure_v4.review_native all \
  --archive /percorso/native-results-20261013.zip \
  --run-dir dist/sure-alignment/new-native-review
```

Le fasi `prepare`, `simulate`, `analyze` sono eseguibili separatamente. Il comando
richiede il riferimento v4 e l'esperimento sincrono già congelati; i relativi
percorsi sono impostabili tramite `--baseline`, `--synchronous` e `--probe`.

## Esperimento precedente del 12 ottobre

La politica esplicita di aggiornamento dei ritardi riproduce il rapporto del
collega sul base e mantiene Python e Julia concordi nei dieci scenari nativi.
L'equivalenza con Vensim **non è ancora raggiunta**. Sono disponibili una prova
isolata dei due allocatori e una modifica candidata del sorgente Vensim.
Webapp, v3, v4 originale e ambienti installati restano invariati.

## Causa accertata: ordine di aggiornamento

In PySD 3.14.3 `DelayFixed.update()` valuta il suo ingresso durante l'assegnazione
sequenziale degli stati. Per
`DELAY FIXED(SMOOTH(Electricity dispatched[Month,Hour,Import], 2), 0.1, 0)`
lo SMOOTH annidato può quindi essere letto prima o dopo il proprio aggiornamento.
L'ordine degli stati selezionati dipende anche da insiemi Python. Nel precedente
riferimento, con hash seed 0, veniva letto lo SMOOTH già aggiornato.

L'esperimento congela gli ingressi di **tutti** i DELAY FIXED prima del passo
Euler. Il metodo è installato sulla sola istanza sperimentale. Julia usa la stessa
politica; una migrazione vincolata al checksum del modello generato rimuove
l'unica lettura successiva all'aggiornamento, già documentata nell'esperimento v4.
Non cambiano passo, inizializzazione, calibrazione, scenari o allocatore.

Sul base lo scarto massimo di `PHS hourly demand`, diviso per il picco Vensim
dell'intera variabile, passa dal **14,4623% allo 0,743883%**. Lo scarto massimo
del prezzo passa da **0,289506 a 0,206499 Rp/kWh**. I nuovi massimi di pompaggio,
dispacciamento e prezzo coincidono con quelli del CSV del collega (entro circa
1e-16 per il pompaggio). Non è una prova della semantica interna di Vensim per
ogni ritardo: è un esperimento causale sull'ordine Python che riconcilia i report.

## Risultati e limiti

Run: `dist/sure-alignment/20261012-synchronous`, derivato dal riferimento
`dist/sure-v4/20261012-alignment`, sorgenti main `17db1f4`.

- Dieci scenari, 110 variabili, tutte le coordinate e gli anni 2011–2050:
  Python–Julia supera la tolleranza già approvata, senza campionamento.
- Base, hydro_on e mixed: invertire l'ordine relativo DELAY/SMOOTH non cambia
  più alcun bit; il percorso app con 52 output coincide con quello diagnostico.
- Base ripetuto dopo tutti i dieci scenari: identità bit a bit in entrambi i motori.
- Un solo modulo Julia, 20 parametri riutilizzabili; nessuna compilazione dopo
  il primo scenario. Conservazione dell'energia verificata in entrambi i motori.
- Nessun avviso nuovo non classificato. Cinque test unitari verificano anche
  ritardi 0.01, 0.1, 1, 2 e 4, reinizializzazione, copie degli array e ripristino
  dei callback in caso di eccezione.

La tolleranza resta `1e-10 * max(1,S) + 1e-8 * abs(Python)` per serie elementare.
Il confronto nativo aggiunge esclusivamente il limite di quantizzazione Float32
del formato esportato. Le 288 serie Import costanti incomplete usano la
ricostruzione separata già dichiarata; gli archivi originali non sono modificati.

| Scenario nativo | Scarto PHS / picco, prima | Dopo | Max scarto prezzo dopo, Rp/kWh |
|---|---:|---:|---:|
| 01_base | 14,4623% | 0,743883% | 0,206499 |
| 09_hydro_on | 76,0599% | 54,5872% | 0,295890 |
| 10_mixed | 71,9409% | 42,8499% | 0,458670 |

Questi sono tre dei dieci run condivisi, **non** i quattro scenari del CSV.
Gli errori orari con i provvedimenti attivi restano importanti. Non si può
concludere che basti allargare le tolleranze numeriche.

## Come leggere il rapporto del collega

`coherence_report_v4.csv`, estratto da main `17db1f4`, contiene effettivamente
230 esiti pratici positivi su 240. Il criterio pratico accetta un errore massimo
entro l'1% del picco **oppure** un errore aggregato annuo entro il 5%.
Per `PHS hourly demand` mid e high passano grazie al totale annuo, anche se gli
scarti orari massimi raggiungono il 46,2943% e il 71,2512% del picco.
La corrispondenza del pompaggio **stagionale mensile** citata dal collega non
certifica la distribuzione oraria del pompaggio totale.

La spiegazione dell'allocatore è plausibile e coerente con le discontinuità del
prezzo: basta accendere Import con una quantità piccola perché il prezzo passi
al costo di quel fornitore. L'import entra inoltre in SMOOTH e DELAY FIXED,
modifica l'offerta PHS e, attraverso un'inversione e una normalizzazione,
la distribuzione oraria del pompaggio. Le differenze possono quindi amplificarsi.
Non abbiamo verificato direttamente una soglia interna Vensim di 0.01 GWh/h.
L'archivio manca degli ingressi nativi completi dell'allocatore, in particolare
`Hourly demand and PHS` e `Priority vector by supplier`.

## Prova Vensim pronta

[NATIVE_TEST.md](NATIVE_TEST.md) descrive l'esecuzione e le condizioni per accettare
la modifica. Il generatore produce un modello statico con 50 casi sintetici:
confini tra fornitori, quantità appena sopra/sotto tali confini, priorità
negative e traslate, pareggi, sovrapposizioni, disponibilità nulla o abbondante.
Gli stessi ingressi alimentano ALLOCATE AVAILABLE e ALLOCATE BY PRIORITY.

La traduzione Python della nuova equazione coincide esattamente con il wrapper
v4 in tutti i 50 casi. Questo verifica formulazione e cablaggio locale;
**non verifica l'implementazione nativa Vensim**. È anche disponibile il sorgente
SURE candidato che cambia solo l'equazione di allocazione e rende esplicito il
taglio delle richieste negative già applicato da v4.

Documentazione primaria:
[ALLOCATE AVAILABLE](https://www.vensim.com/documentation/fn_allocate_available.html),
[ALLOCATE BY PRIORITY](https://www.vensim.com/documentation/fn_allocate_by_priority.html).
La seconda funzione espone una larghezza comune e gestisce anche priorità uguali
o sovrapposte. Non presupponiamo che la sua implementazione nativa sia esatta:
è ciò che misura la prova preparata.

## Riproduzione locale

Usare gli ambienti isolati già bloccati in `benchmarks/julia-repro`, senza
aggiornare l'ambiente della webapp. Rigenerare prima il riferimento completo
con `scripts/verify_sure_v4.py` se non è disponibile.

```sh
dist/julia-repro/runtime/python-reference/bin/python -B -m scripts.sure_v4.align_delays all \
  --baseline dist/sure-v4/20261012-alignment \
  --run-dir dist/sure-alignment/new-run
dist/julia-repro/runtime/python-reference/bin/python -B -m scripts.sure_v4.report_alignment \
  --baseline dist/sure-v4/20261012-alignment \
  --run-dir dist/sure-alignment/new-run
dist/julia-repro/runtime/python-reference/bin/python -B -m unittest discover -s tests -p 'test_sure_alignment.py'
```

Le fasi separate sono `prepare`, `reference`, `order`, `app`, `julia`, `validate`.
`prepare` richiede una cartella nuova; le simulazioni rifiutano risultati già
presenti. I worker fissano hash seed e thread prima dell'avvio. `validation.json`
conserva gli errori per variabile; `evidence.json` lega codice e artefatti ai
checksum. `results-summary.json` è la copia compatta versionata del risultato.
I tempi raccolti durante questi controlli non costituiscono un benchmark.
