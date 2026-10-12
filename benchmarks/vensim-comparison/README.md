# Confronto SURE Julia–Vensim

Confronto diretto con gli archivi nativi della release `data-v1.0.0`, sul
branch `julia-reproducibility`. Usa il modulo Julia parametrico già validato
contro Python, senza cambiare modello, dati, webapp o implementazioni
certificate. Esito e limiti sono in [RESULTS.md](RESULTS.md).

## Riferimenti e parametri

Gli archivi delle quattro sezioni sono stati generati tramite la DLL Vensim
e il modello pubblicato `Vensim/SURE.vpmx`. Il codice di precomputazione
imposta soltanto gli input della rispettiva sezione: gli altri mantengono i
default del modello pubblicato. Gli archivi **non registrano tutti i 20
parametri**, né versione/precisione interna della DLL e metodo di integrazione.
Il codice prescrive 2011–2050 e passo 1; questa configurazione non costituisce
da sola un certificato dell'esecuzione storica.

Il runner applica tutti i 20 parametri a Julia. Per quelli non presenti
nella sezione usa, come ipotesi esplicita, i valori letterali del sorgente
MDL tradotto in Python. Aggiunge quattro controprove dei casi base con i
default UI. Il profilo che si avvicina di più a Vensim **non viene scelto
automaticamente come verità**. Il file delle costanti calibrate non risolve
questo limite: l'estrattore esclude gli input di scenario e conserva soltanto
le differenze maggiori delle proprie soglie.

L'inventario verifica tutti gli scenari degli archivi, nomi, coordinate,
anni, celle, valori non finiti e precisione di esportazione. La suite
`targeted` seleziona base/low/mid/high, ogni valore di ogni leva con le altre
al base della sezione, e otto combinazioni casuali per sezione (seme
`20261012`). Elimina i duplicati e salva parametri e alias espliciti. Il
seme riguarda questo nuovo confronto con gli archivi; non modifica la suite
Python–Julia già congelata. `pilot` limita la scelta ai quattro profili;
`full` esegue l'intera griglia, con un costo maggiore.

## Confronti e dati mancanti

Si confrontano tutte le celle e tutti gli anni degli output presenti nella
sezione selezionata. Sono 50 variabili distinte, a fronte dei 52 output
dell'app: gli archivi di queste sezioni non contengono `Power by Type` e
`Annual CO2 emissions`. Non si dichiara copertura nativa di questi due output.

Il riferimento esportato è esattamente rappresentabile in Float32: il
wrapper usa `ctypes.c_float`, coerentemente con la firma ufficiale di
[`vensim_get_data`](https://vensim.com/documentation/vensim_get_data.html).
Questo **non dimostra la precisione interna** del motore storico; si veda
anche la [documentazione sulla doppia precisione](https://vensim.com/documentation/24350.html).
Documentazione consultata il 12 ottobre 2026.

Per ogni serie elementare si conserva il criterio vicino all'errore numerico:

```
errore <= 1e-10 * max(1, massimo assoluto della serie Vensim)
          + 1e-8 * abs(Vensim) + metà ULP Float32 del valore esportato
```

La metà ULP considera il maggiore dei due intervalli adiacenti. Serve solo
a rappresentare la quantizzazione esplicita dell'export. Sono registrati
anche i superamenti della soglia senza questo contributo. I valori discreti
richiedono uguaglianza esatta. Coordinate, anni e forme devono essere esatti.
Un dato mancante o non finito impedisce il superamento del confronto.

La diagnostica aggiuntiva `errore > 1e-4 * picco della variabile + 1% * abs(Vensim)`
**non è una nuova soglia di accettazione**. Le percentuali rispetto al picco
di una variabile differiscono dalle percentuali rispetto alla singola cella.
`max_relative_significant` considera le celle con modulo almeno pari all'1%
del picco della variabile; tutte le altre restano comunque nel confronto
numerico principale. I totali annuali orari sono somme su mese/ora moltiplicate
per `365/12`, come nell'app. `annual-by-supplier.csv` mantiene i fornitori
distinti, evitando che l'offerta convenzionale Import domini le scale altrui.

Negli archivi elettrici mancano i valori 2012–2050 di
`Hourly exported electricity[Month,Hour,Import]`. Il valore iniziale è zero
e l'equazione MDL è costante a zero. Si conservano:

- snapshot grezzi con i valori mancanti e confronti esplicitamente incompleti;
- snapshot ricostruiti **separati**, con certificato del modello sorgente,
  coordinate e celle ricostruite, e confronti distinti.

La ricostruzione è ammessa solo per questo esatto schema di assenze, dopo
aver verificato equazione e valori iniziali. Nessun altro buco viene riempito.
Non converte una serie assente in una misura nativa. Gli originali Parquet
non vengono modificati.

## Riproduzione

Prerequisiti: dati verificati con `python scripts/data_release.py verify`,
ambiente e artefatti completati di [julia-repro](../julia-repro/README.md) e
[julia-parametric](../julia-parametric/README.md). I percorsi predefiniti di
questi due riferimenti possono essere cambiati con `--reference` e
`--parametric` in ogni comando. Usare una nuova directory per una nuova
simulazione; i runner rifiutano di sovrascrivere gli esiti grezzi.

```sh
dist/julia-repro/runtime/python-reference/bin/python -B -m unittest tests.test_vensim_comparison tests.test_vensim_report -v

dist/julia-repro/runtime/python-reference/bin/python -B -u scripts/compare_vensim.py inventory --suite targeted --run-dir dist/vensim-comparison/new-run
dist/julia-repro/runtime/python-reference/bin/python -B -u scripts/compare_vensim.py run --run-dir dist/vensim-comparison/new-run

PYTHONHASHSEED=0 SURE_VARIANT=v3 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 dist/julia-repro/runtime/python-reference/bin/python -B -u scripts/compare_vensim.py python --run-dir dist/vensim-comparison/new-run
dist/julia-repro/runtime/python-reference/bin/python -B scripts/compare_vensim.py triangulate --run-dir dist/vensim-comparison/new-run
dist/julia-repro/runtime/python-reference/bin/python -B scripts/report_vensim.py --run-dir dist/vensim-comparison/new-run --oracle-dir dist/vensim-comparison/new-run
```

`python` esegue i tre vettori di parametri distinti dei quattro casi base,
con tutte le 50 variabili; base PV ed elettricità coincidono. Usa il percorso
Python attuale con nomi dei parametri risolti esplicitamente, inclusi i
provvedimenti. Registra e confronta gli avvisi con quelli già classificati
del riferimento, usando `PYTHONHASHSEED=0`. Non è una nuova simulazione Vensim.
Per ampliare un confronto già eseguito, `report_vensim.py --oracle-dir` può
riusare l'oracolo del pilot se modello, parametri e checksum coincidono;
verifica inoltre la ripetizione esatta degli scenari Julia comuni.
Per diagnosticare altri scenari, `python --python-job <id>` seleziona un
job dell'inventario; l'opzione è ripetibile. Usare `--oracle-name python-extremes`
per mantenere un oracolo aggiuntivo distinto, e lo stesso nome in `triangulate`.
L'analisi lo include con `--extra-oracle-name python-extremes`.

Il worker Julia carica un solo modulo e ricrea stati/ritardi a ogni scenario.
Le dipendenze, le patch e il modello restano quelli della certificazione
precedente. Gli avvisi Julia non classificati interrompono l'esecuzione.
`compare` rigenera soltanto l'analisi di un'esecuzione congelata e verificata;
registra separatamente i checksum del codice di analisi e di esecuzione.
`report_vensim.py` verifica i checksum prima di produrre CSV per variabile,
totali per fornitore, confronto degli effetti dei quattro provvedimenti e
diagnostica della normalizzazione del pompaggio.

Gli artefatti voluminosi rimangono in `dist/vensim-comparison/<run-id>`, fuori
da Git: `inventory.json`, parametri, audit completo degli archivi, snapshot
Vensim/Python/Julia, file binari Julia, ricostruzioni documentate, log,
confronti e rapporto. Sono legati a checksum dei dati, sorgenti, costanti,
modulo compilato, snapshot e script. Questa prova non è un benchmark e non
estende la certificazione macOS arm64 a un'altra piattaforma.
