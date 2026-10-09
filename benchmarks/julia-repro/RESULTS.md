# Esito del pilota locale — 9 ottobre 2026

**La riproducibilità completa Python–Julia non è ancora dimostrata.** Il runner,
gli ambienti separati, i lock, le patch locali e i controlli sono implementati;
la traduzione SURE completa si arresta su cinque incompatibilità upstream.
Non sono stati eseguiti benchmark comparativi e non viene dichiarato uno speedup.

Branch: `codex/julia-reproducibility`, da
`086be42884d92cd945c0afae2f2985f01cf13495`.
Webapp, modello originale, dati e `.venv` sono rimasti invariati.

Artefatti riproducibili: `dist/julia-repro/20261009-reproducibility/`.
Il relativo `REPORT.md` e `summary.json` contengono lo stato aggiornato delle
fasi; l'inventario ha SHA-256
`cb4d58bd3db2c173379b232d540d182a700b7535bf36f906d51fe0c8f73b303f`.

## Controlli superati

| Controllo | Risultato |
|---|---|
| Test unitari Python del runner | 16 superati |
| Test della release dati già presenti nel progetto | 6 superati |
| Test Julia mirati | 15 gruppi superati, con confronto all'oracolo Python |
| Allocazione | 23 casi, comprese richieste negative e priorità sovrapposte |
| Esportazione Julia e ripristino dello stato | 2 esecuzioni identiche della fixture a sei dimensioni |
| Webapp Python vs percorso diagnostico, base/low/mid/high | 52 output, tutte le celle e tutti i 40 anni; errore massimo 0 |
| Valori confrontati fra i due percorsi Python | 1.727.840 |
| Ricostruzione esatta 6D → 3D → 6D sugli stati reali | 11.827.200 valori, 14 componenti, quattro scenari e tutti gli anni |
| Base in due processi nuovi e sequenza base → high → base | Identità bit per bit dei risultati base, errore massimo 0 |
| Blocco della validazione e del benchmark | Verificato: uscita non zero e nessun artefatto prestazionale |

La suite congelata contiene **43 scenari** e **102 variabili diagnostiche**,
incluse le tre leve categoriali applicate. Sono stati eseguiti i quattro scenari
principali; gli altri 39 rimangono da eseguire dopo la risoluzione dei blocchi.
Questo pilota non viene dichiarato come superamento dell'intera suite.

Le quattro leve `Provvedimento 1.2`, `1.3`, `1.4`, `1.7` non sono applicate
dalla webapp v3 corrente. La condizione è registrata esplicitamente; non è
stata modificata durante l'esperimento.

## Perché la traduzione completa si ferma

Sono registrati 223 avvisi: 218 corrispondono alle interpolazioni di input
mancanti già eseguite dal riferimento Python, cinque sono bloccanti.

| Variabile/costrutto | Incompatibilità osservata |
|---|---|
| `Hourly imported electricity` | `SMOOTH` annidato dentro `DELAY FIXED`: il visitatore upstream propone un valore sostitutivo zero |
| `PV annual production 2024` | Dichiarazione `DATA` con equazione ordinaria; meccanismo di override non supportato |
| `Res buildings i` | Lettura esterna di forma `(15, 5, 8, 3, 2)` non gestita |
| `Initial Heating Solution` | Lettura esterna di forma `(15, 8, 11, 5, 3, 2)` non gestita |
| `Buildings Construction` | Lettura esterna di forma `(15, 3, 8, 5)` non gestita |

Il primo asse delle letture esterne rappresenta il tempo. Il runner rifiuta
queste traduzioni prima della simulazione: nessun sostituto zero entra in un
confronto dichiarato valido. Non esiste quindi ancora un errore massimo
Python–Julia per il modello completo, né una prima divergenza numerica da
attribuire. Questi cinque blocchi sono quelli osservati, non una garanzia
che non ne emergano altri dopo la loro correzione.

Le correzioni già implementate riguardano `EXCEPT` fino a sei dimensioni,
sottogruppi, autoriferimenti, ordinamento degli stati iniziali, dipendenze tra
assegnazioni, profilo di allocazione SURE, serializzazione degli input e
comportamento ai confini temporali. Ogni modifica è confinata al runner e
alle copie sperimentali; nessuna dipendenza dell'app è stata modificata.

## Conclusione sulle dimensioni

La forma `120 × 11 × 4` conserva esattamente tutte le **5.280 celle** di
`8 × 11 × 5 × 3 × 2 × 2`. La mappa è esplicita per etichette e reversibile,
con coordinate composte salvate nell'inventario. Sono superati anche i test
sintetici di selezioni, esclusioni, somme, normalizzazioni e trasferimenti.

Questo giustifica una riorganizzazione degli indici, non un'aggregazione degli
stati. Non è stata riscritta la dinamica completa a tre dimensioni e non è
dimostrato un vantaggio prestazionale di tale rappresentazione. Ridurre il
numero di indici, da solo, non risolve lo `SMOOTH` annidato o la lettura
multidimensionale degli input.

Per riprodurre o proseguire usare [README.md](README.md). Conservare le
soglie numeriche, rieseguire i test mirati dopo ogni patch, quindi traduzione
e confronto completo. Il benchmark rimane subordinato al PASS dell'intera
suite e dei controlli di determinismo, con gli stessi checksum e lo stesso
codice verificato.
