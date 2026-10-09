# SURE Julia parametrico e verifica dei provvedimenti

Esperimento locale sul branch `codex/julia-reproducibility`. Usa il modello,
le patch e gli ambienti certificati in [julia-repro](../julia-repro/README.md),
senza modificare la webapp, il modello originale o il suo ambiente Python.
I risultati sono descritti in [RESULTS.md](RESULTS.md).

## Un modello compilato, più scenari

`scripts/julia_parametric/model.py` deriva un modulo parametrico dalla
traduzione Julia dello scenario base già certificata. Le 20 leve della UI
diventano campi `Float64` della struttura immutabile `SUREParameters`.
Le costanti calibrate, le equazioni, le coordinate e le politiche numeriche
restano quelle del riferimento. La trasformazione verifica le forme del
codice sorgente attese e si interrompe se non le trova.

Il worker carica il modulo **una sola volta**, poi passa una nuova struttura
di parametri a ogni richiesta. Cambiare i valori non cambia il tipo Julia.
Ogni esecuzione ricrea stock iniziali, cache, problema ODE e memoria dei
ritardi; non riusa risultati numerici. `run_model` copia anche l'eventuale
stato iniziale fornito dal chiamante. Il worker verifica che non sia mutato.

L'interfaccia del modulo generato è:

```julia
session = Module(:SURESession)
Base.include(session, abspath("SURE_parametric.jl")) # una volta per processo

# values contiene tutti e soli i 20 nomi indicati in model.json.
parameters = session.parameters_from_dict(values)
initial = session.initial_state(parameters)
solution = session.run_model(parameters; u0=initial)
outputs = session.observe(solution.u[end], solution.t[end], names;
                          parameters=parameters)
```

Usare gli stessi parametri anche nell'estrazione degli ausiliari. Sono
rifiutati nomi mancanti/sconosciuti, valori non finiti e valori diversi da
0/1 per i quattro provvedimenti. Le altre leve conservano i valori numerici
passati dal chiamante; la griglia UI è registrata nel manifest originale.
Le chiamate effettuate da una funzione che carica dinamicamente il modulo
usano `Base.invokelatest`, come nel worker, per rispettare il world age Julia.

La prima esecuzione compila il modello. Le successive cambiano scenario
nello stesso processo. Un processo nuovo paga nuovamente avvio e JIT;
modifiche a equazioni, struttura degli array o tipi richiedono nuova
generazione/compilazione. Il worker dimostra il riuso con una sequenza di
richieste; non aggiunge un servizio HTTP o un'integrazione Streamlit.

## Prova di rigenerazione e controlli ignorati

`scripts/julia_parametric/probe_controls.py` parte dal file originale
`Vensim/SURE.mdl`, copia i CSV e usa la pipeline attuale di adattamento,
PySD 3.14.3 e i tre postprocessori Python in una directory sperimentale.
Verifica le equazioni adattate, i sei CSV e i corpi delle funzioni generate
prima di eseguire il modello potato con le costanti calibrate.

I quattro nomi UI `Provvedimento 1.2`, `1.3`, `1.4`, `1.7` sono conservati da
PySD con le virgolette Vensim esterne, ad esempio `"Provvedimento 1.2"`.
La selezione corrente dei parametri non li riconosce senza virgolette.
La rigenerazione mantiene questi nomi: da sola non corregge il problema.
L'adattatore sperimentale risolve prima il nome esatto, poi un nome senza
virgolette solo se univoco; un parametro sconosciuto o ambiguo provoca errore.

La validazione distingue due contratti:

- `validate`: tutti i 43 scenari storici, con i quattro controlli a zero per
  riprodurre il comportamento effettivo dell'app corrente. Confronta tutte
  le 102 variabili del riferimento certificato.
- `controls`: base, quattro provvedimenti singoli, tutti insieme, mid e high,
  applicando tutte le 20 leve. Il riferimento è il Python appena rigenerato
  con risoluzione esplicita dei nomi. Confronta i 52 output dell'app e
  `Hourly demand and PHS`, necessario al controllo di conservazione.

Entrambi includono la ripetizione del base dopo altri scenari. Julia esporta
102 variabili anche nella prova dei controlli; le altre 49 sono diagnostiche,
non vengono dichiarate confrontate con il nuovo riferimento Python.
Restano in uso le tolleranze autorizzate in `julia-repro/acceptance.json`;
la conservazione mantiene la soglia originale. Gli avvisi di traduzione,
caricamento ed esecuzione Python sono registrati e confrontati con il
riferimento congelato. Un avviso nuovo o non classificato blocca la prova.

## Riproduzione

Prerequisito: completare la certificazione `julia-repro`, con gli ambienti
bloccati e i suoi artefatti locali. I percorsi predefiniti sono
`dist/julia-repro/20261009-reproducibility` per il riferimento e
`dist/julia-parametric/20261009` per questo esperimento. Per una nuova prova
usare una nuova directory e specificarla in tutte le fasi. Dalla radice:

```sh
dist/julia-repro/runtime/python-reference/bin/python -B scripts/benchmark_julia_parametric.py build --run-dir dist/julia-parametric/new-run

PYTHONHASHSEED=0 SURE_VARIANT=v3 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 dist/julia-repro/runtime/python-reference/bin/python -B -u -m scripts.julia_parametric.probe_controls --run-dir dist/julia-parametric/new-run/controls

dist/julia-repro/runtime/python-reference/bin/python -B scripts/benchmark_julia_parametric.py validate --run-dir dist/julia-parametric/new-run
dist/julia-repro/runtime/python-reference/bin/python -B scripts/benchmark_julia_parametric.py controls --run-dir dist/julia-parametric/new-run
dist/julia-repro/runtime/python-reference/bin/python -B scripts/benchmark_julia_parametric.py benchmark --run-dir dist/julia-parametric/new-run

dist/julia-repro/runtime/python-reference/bin/python -B -m unittest discover -s tests -p test_parametric_sure.py -v
JULIA_DEPOT_PATH="$PWD/dist/julia-repro/runtime/julia-depot" JULIA_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 dist/julia-repro/runtime/julia-1.10.12/bin/julia --startup-file=no --project=benchmarks/julia-repro tests/parametric_api.jl dist/julia-parametric/new-run/model
```

`--reference` permette di indicare un altro esperimento originale certificato.
`pilot` è una prova facoltativa base → high → base prima della suite completa.
Il runner rifiuta di sovrascrivere i risultati raw di una fase già eseguita.
Il riferimento Python richiede una directory `regenerated` nuova.

`benchmark` richiede entrambe le validazioni e tutti i checksum. Esegue tre
riscaldamenti (base, mid, high), quindi cinque cicli base → mid → high nello
stesso processo. Misura configurazione, inizializzazione, integrazione,
estrazione, JIT e picco RSS; ogni risultato viene confrontato con Python.
Il JIT è una porzione dei tempi di fase, non un tempo da sommare. Il benchmark
usa solo i 52 output dell'app e applica anche i provvedimenti corretti.
Non eseguire altri benchmark contemporaneamente.

Il timer macOS usa `mach_absolute_time`, come Python; un secondo orologio
rileva sospensioni e `caffeinate` impedisce lo sleep inattivo durante Julia.
Un intervallo sospeso invalida le prestazioni. Il picco RSS è cumulativo per
il processo: non è la memoria marginale di ogni richiesta.

Ogni rapporto conserva l'identità esatta del codice eseguito, modello, dati,
parametri, riferimento e artefatti. Il gate può riusare una certificazione
numerica dopo sole modifiche al runner/test, ma richiede identità del
generatore, worker, timer e motore/comparatori congelati. Le firme originali
non vengono riscritte. Tutti gli artefatti voluminosi restano sotto `dist/`,
esclusa da Git.
