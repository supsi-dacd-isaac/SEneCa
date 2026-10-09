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
```

`all --run-dir dist/julia-repro/new-run-id` esegue tutte le fasi in ordine e si
ferma al primo fallimento. `report --run-dir ...` rigenera il rapporto senza
simulare. Le fasi già completate possono essere rilanciate esplicitamente;
l'inventario non viene sovrascritto. Una modifica a modello/dati/configurazioni
richiede un nuovo inventario. Una modifica al runner o alle patch richiede
nuovi test mirati, traduzione e validazione prima del benchmark.

La suite contiene 43 scenari distinti per parametri richiesti. I duplicati
esatti hanno un alias nell'inventario. Le quattro leve `Provvedimento 1.2`,
`1.3`, `1.4`, `1.7` sono già ignorate dalla webapp v3: il runner lo registra nei
parametri richiesti/applicati e conserva il comportamento corrente.

## Test e patch locali

Le patch sono in `scripts/julia_repro/builder_patch.py` e `allocation.jl`.
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
- Ritardi `0.01`, `0.1`, `1`, `2`, `4`: simulazioni con Euler annuale confrontate
  con l'oracolo Python. I ritardi subannuali conservano la semantica Python.
- Allocazione: profilo rettangolare 1 usato da SURE, richieste negative
  troncate a zero come nell'app, disponibilità scarsa, priorità sovrapposte e
  conservazione. Gli altri profili sono rifiutati esplicitamente.
- CSV: interpolazione e valori ai confini, confronto con l'oracolo Python;
  serializzazione JSON di tipi NumPy e clamp ai valori estremi.
- Rimozione delle protezioni upstream che leggono zero fuori dai limiti o
  sostituiscono con zero ausiliari iniziali mancanti. Queste situazioni devono
  fallire, non produrre una simulazione apparentemente valida.
- Smoke test del runner Julia: formato binario, ordinamento delle coordinate,
  due esecuzioni dello stesso modulo e ripristino dello stato.

Gli avvisi vengono conservati. Solo gli avvisi di interpolazione di dati
mancanti già presenti nel riferimento Python, corrispondenti per variabile,
nome del CSV e cella, sono classificati come comportamento esistente.
Gli avvisi di costrutti ignorati, approssimati o non supportati sono bloccanti.

La prima esecuzione ha individuato ulteriori incompatibilità upstream:
`SMOOTH` annidato, una variabile `DATA` con equazione ordinaria e tre input CSV
di rango superiore a quello gestito dal lettore Julia. Questi casi non sono
mascherati dalle patch e impediscono attualmente la simulazione completa.

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
selezioni/esclusioni, somme, normalizzazioni e transizioni sintetiche, oltre
alla ricostruzione di tutte le celle reali dei 14 componenti raggiungibili.
L'esperimento non aggrega stati e non riscrive le equazioni SURE a tre indici.

Ogni serie elementare usa la soglia richiesta:

```
abs(Julia - Python) <= 1e-12 * max(1, max_t(abs(Python))) + 1e-9 * abs(Python)
```

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

Il benchmark richiede il PASS di tutti gli scenari, dei test mirati correnti,
della diagnostica e dei controlli di determinismo. Verifica anche i checksum
degli artefatti della validazione. Un PASS del solo pilota non lo abilita.

Per base/mid/high: tre processi nuovi e cinque ripetizioni nello stesso
processo dopo una prima esecuzione scartata. Ogni scenario Julia ha un modulo
distinto; le ripetizioni ricopiano gli stati iniziali, inclusi quelli dei
ritardi. La sequenza base → high → base riutilizza il modulo base per rilevare
eventuali contaminazioni. I risultati numerici non sono riutilizzati da cache.

I tempi salvati sono osservabili nel percorso reale:

- Python: caricamento/potatura, inizializzazione/configurazione, passi Euler,
  estrazione/cattura e serializzazione. I wrapper misurano i metodi esistenti
  senza cambiare equazioni o cache interne. Il caricamento comprende anche
  l'inizializzazione iniziale effettuata da `load_model`.
- Julia: caricamento del modulo (comprende la costruzione iniziale di `u0`),
  copia dello stato iniziale, solve ed estrazione. I contatori Julia 1.10.12
  misurano separatamente la compilazione *inclusa* in ciascuna fase: questi
  tempi non vanno sommati una seconda volta ai tempi di parete.
- Per ciascun gruppo: valori singoli, mediana, minimo/massimo e memoria
  massima del processo. La memoria delle ripetizioni a caldo è il massimo
  cumulativo del processo, non un picco indipendente di ogni ripetizione.

La preparazione di un nuovo scenario è registrata in `translation.json` e
rimane distinta dalla ripetizione dello stesso scenario compilato. Questa
misura non stima la latenza di un futuro servizio persistente.

`dist/julia-repro/<run-id>` contiene inventario, risultati numerici compressi,
coordinate, parametri applicati, checksum, traduzioni, avvisi, log,
`summary.json` e `REPORT.md`. È già esclusa da Git. Versionare solo runner,
test, patch, lock e documentazione. Il rapporto del primo pilota è riassunto
in `RESULTS.md`.
