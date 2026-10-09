# Riproducibilità SURE Python–Julia

Esperimento locale sul branch `codex/julia-reproducibility`, creato da `main`
al commit `086be42884d92cd945c0afae2f2985f01cf13495`. La webapp, il modello
originale e `.venv` rimangono invariati. Questo harness non aggiunge API alla webapp.

## Ambiente bloccato

Il riferimento esegue `sure_pysd.load_model(prune=True)` e `run_scenario`, con
costanti calibrate, correzione delle richieste negative, ottimizzazione xarray
e le stesse opzioni della webapp. Non usa la cache dei risultati Streamlit.
La diagnostica amplia gli output in un altro processo; deve riprodurre tutti
i 52 output del riferimento prima di essere usata per il confronto Julia.

| Componente | Versione |
|---|---|
| Sistema dell'esperimento | macOS arm64 |
| Python | 3.11.8, pacchetti in `python-reference.lock` |
| Riferimento PySD | 3.14.3 |
| Modello e dati | SURE v3, `constants_ref_v3.pkl`, `data-v1.0.0` |
| Julia | 1.10.12, archivio ufficiale verificato con SHA-256 |
| Traduttore PySD | `8991d119e139029d4dec712d257cf5fcc3549b8f` |
| PySD.jl | `abe4251fe91734f83776a9c782088d3a2f09dc57` |
| Dipendenze Julia | `Project.toml` + `Manifest.toml`, senza risoluzione automatica di nuove versioni |
| Calcolo | backend `ode`, Float64, un thread, Euler non adattivo, dt=1, 2011–2050 |
| Ordine del riferimento | `PYTHONHASHSEED=0`, ordine degli aggiornamenti registrato e verificato |

Il seed hash è parte del riferimento numerico: PySD costruisce l'elenco degli
stati del modello potato a partire da un set. In questo SURE un `DELAY FIXED`
legge direttamente uno `SMOOTH` annidato, quindi l'ordine di aggiornamento
influenza la simulazione. L'audit riproduce prima gli output Python e registra
le letture prima/dopo l'aggiornamento; Julia applica la stessa semantica.
Una prova separata con seed 2 ha prodotto risultati diversi da seed 0 anche
nel solo Python. Questo esperimento certifica il riferimento con seed 0;
non modifica il comportamento della webapp corrente.

Preparazione, dalla radice del repository:

```sh
.venv/bin/python -B scripts/setup_julia_repro.py
```

Lo script installa due virtualenv, Julia, il checkout e il depot Julia in
`dist/julia-repro/runtime`. Non modifica il virtualenv dell'applicazione né la
configurazione Git globale. Il lock Python riproduce l'ambiente locale originale,
compresi i pacchetti non direttamente utilizzati dal runner. Per usare un altro
sistema operativo occorre preparare e verificare esplicitamente un nuovo pin;
lo script non sceglie una distribuzione alternativa in modo implicito.

Fonti: [PySD](https://github.com/SDXorg/pysd/tree/8991d119e139029d4dec712d257cf5fcc3549b8f),
[PySD.jl](https://github.com/rogersamso/PySD.jl/tree/abe4251fe91734f83776a9c782088d3a2f09dc57),
[distribuzioni Julia](https://julialang.org/downloads/manual-downloads/).

## Esecuzione

Usare una nuova directory per ogni inventario. Nei comandi seguenti `run-id`
è un nome da scegliere; tutti i comandi successivi devono usare lo stesso nome.

```sh
.venv/bin/python -B scripts/benchmark_julia.py inventory --run-dir dist/julia-repro/run-id
.venv/bin/python -B scripts/benchmark_julia.py test --run-dir dist/julia-repro/run-id
.venv/bin/python -B scripts/benchmark_julia.py reference --run-dir dist/julia-repro/run-id --scenarios base low mid high
.venv/bin/python -B scripts/benchmark_julia.py translate --run-dir dist/julia-repro/run-id --scenarios base low mid high
```

Questo è il percorso pilota consigliato per individuare incompatibilità prima
di eseguire l'intera matrice. Un errore di traduzione produce un'uscita non zero,
avvisi, log e `REPORT.md`. I risultati Julia incompleti non vengono confrontati.

Quando la traduzione è supportata, omettere `--scenarios` per eseguire l'intera
suite congelata, incluse le leve agli estremi, tutti i valori categoriali e le
otto combinazioni aggiuntive con seme `20261009`:

```sh
.venv/bin/python -B scripts/benchmark_julia.py reference --run-dir dist/julia-repro/run-id
.venv/bin/python -B scripts/benchmark_julia.py translate --run-dir dist/julia-repro/run-id
.venv/bin/python -B scripts/benchmark_julia.py validate --run-dir dist/julia-repro/run-id
.venv/bin/python -B scripts/benchmark_julia.py benchmark --run-dir dist/julia-repro/run-id
dist/julia-repro/runtime/python-reference/bin/python -B scripts/verify_julia_benchmark_timing.py --run-dir dist/julia-repro/run-id
.venv/bin/python -B scripts/benchmark_julia.py report --run-dir dist/julia-repro/run-id
```

`all --run-dir dist/julia-repro/new-run-id` esegue tutte le fasi in ordine e si
ferma al primo fallimento. Su macOS, **dopo `benchmark` o `all` è obbligatorio
eseguire `verify_julia_benchmark_timing.py`** prima di accettare le prestazioni.
Il runner congelato non rileva la sospensione del computer: i tempi prodotti
dalla sua fase `benchmark` restano provvisori anche quando il confronto
numerico è superato. Eseguire poi `report --run-dir ...` per aggiornare il
rapporto senza simulare; questo comando non sostituisce la verifica temporale.
Le fasi già completate possono essere rilanciate esplicitamente;
l'inventario non viene sovrascritto. Una modifica a modello/dati/configurazioni
richiede un nuovo inventario. Una modifica al runner o alle patch richiede
nuovi test mirati, traduzione e validazione prima del benchmark.

`reference --resume` e `validate --resume` riutilizzano soltanto risultati
con provenienza verificata. Parametri, sorgenti, ambiente, coordinate e file
numerici devono ancora coincidere con i checksum registrati. La suite Python
prosegue sugli scenari rimanenti dopo un errore e registra ogni fallimento;
un riferimento fallito impedisce l'accettazione complessiva.

`validate --jobs 4` può eseguire quattro scenari indipendenti contemporaneamente,
ciascuno in un processo Julia con un solo thread e directory distinta. Questo
riguarda soltanto la validazione numerica: il benchmark rimane sequenziale e
va eseguito quando le altre simulazioni sono terminate.

La suite contiene 43 scenari distinti per parametri richiesti. I duplicati
esatti hanno un alias nell'inventario. Le quattro leve `Provvedimento 1.2`,
`1.3`, `1.4`, `1.7` sono già ignorate dalla webapp v3: il runner lo registra nei
parametri richiesti/applicati e conserva il comportamento corrente.

## Test e patch locali

Le patch sono nei moduli `*_patch.py` di `scripts/julia_repro/` e negli helper
Julia di questa directory.
Si applicano solo in memoria nei processi di traduzione sperimentali, senza
modificare i checkout delle dipendenze o i sorgenti della webapp.

- `EXCEPT` da 1 a 6 dimensioni: selezioni per etichette, unione esatta delle
  esclusioni, sottogruppi, definizioni per cella; copertura completa e nessuna
  sovrapposizione. Una definizione ambigua o incompleta interrompe la traduzione.
- Ordine delle assegnazioni: dipendenze dell'intera variabile e catene di
  autoriferimenti risolte per cella. Nessun accesso a celle ancora non assegnate.
  La fixture Python di autoriferimento riceve `fix_selfref_sure.py` sulla sola
  copia temporanea, come il modello già corretto usato dalla webapp.
- Inizializzazione: ordine degli stock coerente con `reshape` Julia; fixture
  con valori distintivi su ogni asse e confronto diretto con PySD 3.14.3.
  Gli ausiliari vengono valutati sulle dipendenze effettive delle condizioni
  iniziali, con cache distinta per ogni valutazione. Le inizializzazioni estese
  vengono compattate solo dopo verifica esatta dell'espansione di ogni cella.
- Espressioni: indici assegnati per etichette, somme con ambito proprio anche
  quando un asse compare nell'output, sottogruppi e matrici letterali complete.
  Nessun asse viene dedotto dalla sola lunghezza. `SMOOTH` annidati e `INITIAL`
  diventano stati espliciti; `ACTIVE INITIAL` mantiene il ramo iniziale.
- Arrotondamento delle somme: l'audit di SURE associa 353 contratti `SUM` alla
  posizione precisa nell'espressione Python e nell'albero Vensim. Registra
  l'ordine fisico degli assi e i blocchi contigui per riprodurre l'accumulo
  NumPy, verificando prima tutti gli output diagnostici contro il riferimento.
  Sei contratti distinguono il layout del 2011 da quello del 2012–2050:
  ogni anno deve essere osservato e il contratto deve coincidere fra base,
  high e lo scenario tradotto. Layout ambigui o variazioni ulteriori fermano
  la traduzione. I test dei kernel usano anche campioni reali e richiedono
  corrispondenza bit per bit.
- Otto normalizzazioni ottimizzate delle quote di mercato `HS`: Julia
  riproduce le funzioni già applicate dalla webapp, incluse le varianti senza
  gas, teleriscaldamento e incentivi. Le categorie escluse vengono azzerate
  prima della somma sequenziale sull'asse `HS`, poi si divide per il totale.
  L'ordine delle operazioni conserva gli arrotondamenti del percorso Python;
  tutte le etichette e le cinque dimensioni delle funzioni sono verificate.
- Funzioni numeriche e condizioni: semantica Python per soglie di divisione,
  potenze, impulsi, operatori logici e valutazione condizionale dei rami.
  `EXP` e le potenze generali chiamano direttamente `exp`/`pow` della
  libreria nativa Apple `libSystem`; le potenze NumPy mantengono inoltre i
  casi speciali per esponenti −1, 0, 0.5, 1 e 2. Il traduttore distingue
  `POWER`, potenze scalari Python e potenze su array. La compatibilità è
  circoscritta a NumPy 2.4.6 sul macOS arm64 congelato: versione di macOS e
  versioni delle librerie native sono registrate e controllate al caricamento.
  Julia esegue questi calcoli senza richiamare un interprete Python.
- Ritardi `0.01`, `0.1`, `1`, `2`, `4`: simulazioni con Euler annuale confrontate
  con l'oracolo Python. I ritardi subannuali conservano la semantica Python.
  Le celle ritardate vengono copiate direttamente dopo Euler, evitando gli
  arrotondamenti introdotti dalla forma `u + (input - u)`. L'audit verifica
  anche la lettura dello `SMOOTH` già aggiornato nel ritardo dell'importazione.
- Allocazione: profilo rettangolare 1 usato da SURE, richieste negative
  troncate a zero come nell'app, disponibilità scarsa, priorità sovrapposte e
  conservazione. Gli altri profili sono rifiutati esplicitamente.
  Il risolutore riproduce il percorso scalare `dogbox` di SciPy, incluse
  differenze finite e condizioni di arresto: una soluzione analitica della
  stessa equazione non riproduce necessariamente gli arrotondamenti Python.
  I residui di conservazione del riferimento negli stress test estremi sono
  registrati separatamente; l'equivalenza numerica non li corregge.
- CSV: interpolazione e valori ai confini, confronto con l'oracolo Python;
  serializzazione JSON di tipi NumPy e clamp ai valori estremi.
  Il gate include tutti i 70 lettori reali SURE e ogni coordinata nel periodo
  2011–2050. I NaN previsti dagli input RAW fuori dai loro anni vengono
  confrontati esplicitamente; gli output della simulazione devono essere finiti.
- `WITH LOOKUP` e tabelle scalari nominate: l'interpolazione riproduce
  `np.interp` della build congelata, con pendenza arrotondata e operazione
  moltiplicazione-somma fusa (`fma`). Conserva i valori ai nodi e il clamp
  ai confini; i test comprendono anche estrapolazione e `hold_backward`.
  L'estrapolazione conserva invece le operazioni separate del riferimento.
  I lettori `DATA` e gli input multidimensionali mantengono il percorso
  xarray/SciPy verificato separatamente.
- Rimozione delle protezioni upstream che leggono zero fuori dai limiti o
  sostituiscono con zero ausiliari iniziali mancanti. Queste situazioni devono
  fallire, non produrre una simulazione apparentemente valida.
- Smoke test del runner Julia: formato binario, ordinamento delle coordinate,
  due esecuzioni dello stesso modulo e ripristino dello stato.

Gli avvisi vengono conservati. Solo gli avvisi di interpolazione di dati
mancanti già presenti nel riferimento Python, corrispondenti per variabile,
nome del CSV e cella, sono classificati come comportamento esistente.
Gli avvisi di costrutti ignorati, approssimati o non supportati sono bloccanti.

Le incompatibilità upstream individuate su stati annidati, equazioni ordinarie
marcate `DATA`, lettori multidimensionali, indici e inizializzazione sono coperte
da patch locali e regressioni contro Python. Questo non certifica ogni costrutto
di Vensim: il criterio finale resta il confronto dell'intero SURE e dei suoi
scenari, riportato negli artefatti del run.

L'audit `allocation-stress` comprende 1.575 casi sintetici: 1, 3, 9, 17 o 129
fornitori, richieste di scala da `1e-10` a `1e8`, disponibilità fra zero e il
110% delle richieste positive, profili rettangolari separati, contigui,
sovrapposti, annidati o con priorità prossime a `1e6`. Nel riferimento Python,
551 casi superano la soglia originale di conservazione: 299 allocano troppo e
252 troppo poco. Il massimo residuo assoluto è `589606929.6968584`, con 129
fornitori, scala `1e8`, priorità circa `1e6` e larghezza `0.0002`: sono allocati
`5896069296.968588` a fronte di `5306462367.271729` disponibili, un eccesso
dell'11,1111%. Il limite riguarda anche scale grandi e non è un semplice
arrotondamento trascurabile.

Julia riproduce tutti i 1.575 casi entro la tolleranza originale per singola
cella, con differenza assoluta massima da Python `2.9802322387695312e-8` e
nessuna differenza nelle maschere delle allocazioni positive. Questo PASS
certifica l'equivalenza numerica, non l'identità bit per bit né la conservazione
fisica degli stress estremi. Le 23 fixture semplici verificano separatamente
richieste negative troncate, domanda nulla, disponibilità nulla, insufficiente
o eccedente e priorità sovrapposte, includendo la conservazione. Nelle
simulazioni SURE la conservazione resta un controllo bloccante con le soglie
originali; la tolleranza aggiornata del confronto Julia–Python non ammette
questi eccessi fisici.

## Dimensioni e confronto

`packing.py` definisce la corrispondenza per etichette:

```
District × HS × Performance × Type × PVpanel × Battery
                 ↕
Archetipo(District, Performance, Type) × HS × Configurazione(PVpanel, Battery)
8 × 11 × 5 × 3 × 2 × 2 = 120 × 11 × 4 = 5.280 celle
```

Le coordinate composte sono salvate nell'inventario. Non si usa un `reshape`
implicito per convertire gli indici. I test verificano la ricostruzione esatta,
selezioni/esclusioni, somme, normalizzazioni e transizioni sintetiche.

Un audit indipendente applica inoltre le operazioni agli snapshot diagnostici
certificati, senza simulare nuovamente il modello:

```sh
dist/julia-repro/runtime/python-reference/bin/python -B scripts/validate_sure_packing.py --run-dir dist/julia-repro/run-id
```

L'audit copre i 14 componenti raggiungibili in tutti i 43 scenari: 602 coppie
componente/scenario, ciascuna sui 40 anni. Verifica ricostruzione, tre selezioni
per etichette, unione delle esclusioni, somme parziali su `HS`, `PVpanel × Battery`
e `District × Performance`, oltre a due trasferimenti fra categorie
(`Oil → Gas` e `PVno → PVyes`). Le somme e i trasferimenti mantengono lo stesso
ordine aritmetico esplicito nelle due rappresentazioni: il cambio di indici
non autorizza a cambiare l'ordine di accumulo.

L'audit del run `20261009-reproducibility` ha superato tutti i 43 scenari, con
592.103.120 confronti bit per bit. `debug/packing-operations/` conserva il
rapporto, la mappa e gli esiti per scenario, con checksum propri dello script,
della mappa, del manifest e degli snapshot. Questa è una verifica indipendente
sui dati salvati, esclusa dalle misure del benchmark. L'esperimento conserva
tutti gli stati e non esegue un modello dinamico riscritto a tre dimensioni.

Per il confronto Julia–Python, ogni serie elementare usa la soglia aggiornata
autorizzata dall'utente il 9 ottobre 2026 e registrata in `acceptance.json`:

```
abs(Julia - Python) <= 1e-10 * max(1, max_t(abs(Python))) + 1e-8 * abs(Python)
```

Ogni confronto conserva anche l'esito diagnostico con la soglia originale
`1e-12 * max(1, S) + 1e-9 * abs(Python)`, con `S` massimo assoluto della stessa
serie nel tempo. Il riferimento, i pin originali e i file numerici congelati
rimangono invariati. La nuova soglia ammette piccole differenze di arrotondamento
nel candidato; non modifica i controlli di conservazione, le prove esatte di
ripetibilità o i test dei kernel che richiedono identità bit per bit.

Output, dimensioni, etichette e anni devono coincidere. Le leve categoriali
applicate sono estratte anche nella diagnostica e confrontate esattamente.
Nonfiniti, anni mancanti, colonne duplicate o checksum non validi falliscono.
I controlli aggregati non sostituiscono i confronti delle singole celle.
`checks/julia_*.json` conserva errori massimi e prima divergenza di ogni
variabile; `summary.json` ordina le divergenze nel tempo e indica le dipendenze
osservate anch'esse divergenti. La prima differenza osservata non viene
automaticamente dichiarata causa primaria: la diagnosi può richiedere
ulteriori ausiliari e una nuova esecuzione.

## Prestazioni e artefatti

Il benchmark richiede l'equivalenza numerica di tutti i 43 scenari SURE, i test
mirati correnti, la diagnostica e i controlli di determinismo. Richiede inoltre
la conservazione dell'allocazione per ogni anno, mese e ora, sia in Python sia
in Julia, e i limiti per ogni fornitore. Verifica anche i checksum degli
artefatti della validazione. Un PASS del solo pilota non lo abilita.
I residui del riferimento negli stress sintetici estremi dell'allocazione
restano un limite separato: l'accettazione di SURE non certifica la
conservazione fisica per quegli input, anche quando Julia li riproduce.

La verifica temporale finale è separata dal codice congelato dei motori.
Nel macOS dell'esperimento, il timer Python usa `mach_absolute_time`, che
esclude la sospensione, mentre il timer Julia tramite libuv usa
`mach_continuous_time`, che la include. Una sospensione può quindi rendere
incompatibili durata del processo e fasi interne, pur lasciando identici
i risultati numerici. `verify_julia_benchmark_timing.py` impedisce la
sospensione per inattività con `caffeinate -i` e controlla entrambi gli
orologi durante processo, serializzazione e durata complessiva. Accetta
soltanto intervalli per cui il limite superiore della sospensione certificata
è inferiore a 0,01 secondi; verifica anche che la somma delle fasi non superi
il tempo esterno. Un controllo fallito invalida il tentativo.

Lo script conserva `debug/clock-audit/benchmark-original.json` e salva ogni
nuovo tentativo in `benchmark-clock-verified/<attempt>/`. Verifica provenienza
e risultati esatti di tutte le 27 esecuzioni Python originali, conservandone
le 24 misure: i loro timer escludono già la sospensione. Ripete tutte le
27 esecuzioni Julia senza cambiare modello, equazioni o riferimento Python.
Il risultato finale deve avere `pass`, `timing_valid` e `numerical_pass`
uguali a `true`, con il checksum di `timing_audit` ancora valido. Un PASS
della sola fase congelata `benchmark` non soddisfa questo requisito.

Per base/mid/high: tre processi nuovi e cinque ripetizioni nello stesso
processo dopo una prima esecuzione scartata. Ogni scenario Julia ha un modulo
distinto; le ripetizioni ricalcolano gli stati iniziali, inclusi quelli dei
ritardi. La sequenza base → high → base riutilizza il modulo base per rilevare
eventuali contaminazioni. I risultati numerici non sono riutilizzati da cache.

I tempi salvati sono osservabili nel percorso reale:

- Python: caricamento/potatura, inizializzazione/configurazione, passi Euler,
  estrazione/cattura e serializzazione. I wrapper misurano i metodi esistenti
  senza cambiare equazioni o cache interne. Il caricamento comprende anche
  l'inizializzazione iniziale effettuata da `load_model`.
- Julia: caricamento del modulo (comprende la costruzione iniziale di `u0`),
  ricostruzione dello stato iniziale, solve ed estrazione. I contatori Julia 1.10.12
  misurano separatamente la compilazione *inclusa* in ciascuna fase: questi
  tempi non vanno sommati una seconda volta ai tempi di parete. La prima
  costruzione di `u0` è registrata anche come sottofase del caricamento.
- Per ciascun gruppo: valori singoli, mediana, minimo/massimo e memoria
  massima del processo. La memoria delle ripetizioni a caldo è il massimo
  cumulativo del processo, non un picco indipendente di ogni ripetizione.
  Il picco Python comprende la serializzazione NPZ; quello Julia riguarda
  solo il processo Julia e non la conversione NPZ nell'orchestratore Python.
  Questi valori non misurano quindi lo stesso perimetro di memoria complessiva.

Il confronto principale usa il totale di simulazione e cattura dei risultati,
con la serializzazione riportata anche separatamente. I tempi dei processi
nuovi comprendono per entrambi i motori lo snapshot numerico compresso. Le
singole fasi hanno confini diversi: in PySD la cattura calcola ausiliari e
popola cache riutilizzate da Euler. Il solo rapporto tra i tempi di integrazione
non misura quindi l'accelerazione dell'intera simulazione.

La preparazione di un nuovo scenario è registrata in `translation.json` e
rimane distinta dalla ripetizione dello stesso scenario compilato. Questa
misura non stima la latenza di un futuro servizio persistente.

`dist/julia-repro/<run-id>` contiene inventario, risultati numerici compressi,
coordinate, parametri applicati, checksum, traduzioni, avvisi, log,
`summary.json` e `REPORT.md`. È già esclusa da Git. Versionare solo runner,
test, patch, lock e documentazione. L'esito dell'esperimento è riassunto
in `RESULTS.md`.
