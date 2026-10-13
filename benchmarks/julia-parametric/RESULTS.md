# SURE parametrico e controlli — 9 ottobre 2026

**La parametrizzazione funziona:** un solo modulo Julia esegue scenari diversi
passando 20 valori `Float64`, senza rigenerare il sorgente né ricompilare a ogni
cambio. I quattro provvedimenti ignorati dall'app funzionano quando i loro
nomi vengono risolti correttamente. La rigenerazione dal Vensim originale
conferma che le relative equazioni erano già presenti nella traduzione attuale.

Esperimento locale sul branch `codex/julia-reproducibility`, a partire dal
motore certificato nel commit `a5057f2`. Nessuna modifica alla webapp o ai
file originali. Ambiente, dati, calibrazione, sei dimensioni e politiche
numeriche sono quelli della [certificazione precedente](../julia-repro/RESULTS.md).
I comandi sono in [README.md](README.md).

## Codice compilato e isolamento degli scenari

La struttura immutabile `SUREParameters` contiene le 20 leve della UI.
Il modello, i dati esterni e il codice compilato vengono caricati una volta;
stock iniziali, cache e memoria dei ritardi vengono ricreati a ogni richiesta.
Non è una cache dei risultati. Tutte le simulazioni coprono 2011–2050,
Float64, un thread, Euler non adattivo con passo annuale.

| Prova | Risultato |
|---|---|
| Comportamento attuale dell'app | 43/43 scenari superati, 102 variabili confrontate integralmente |
| Sequenza aggiuntiva base → high → base | Tutti e tre i confronti superati; base finale esatto |
| JIT nei successivi 45 cambi/ripetizioni | 0 secondi registrati |
| Base in due processi Julia indipendenti | Tutte le 102 variabili esatte |
| Conservazione nei 46 casi Julia | 46/46 superati con la soglia originale |
| Test del runner e dei nomi | 7/7 Python |
| Contratto dei parametri Julia | 20/20: tipo stabile, ordine indipendente, valori e nomi invalidi rifiutati |

Per riprodurre il comportamento storico, nei 43 scenari i quattro
provvedimenti rimangono a zero: questo è il valore effettivamente utilizzato
dall'app attuale. La prova successiva verifica separatamente la loro attivazione.
Le firme conservano anche la versione originale del runner che ha eseguito
la suite; i successivi controlli aggiunti al runner non hanno modificato
generatore, worker o modello numerico.

## Perché i quattro provvedimenti non avevano effetto

I nomi UI sono `Provvedimento 1.2`, `Provvedimento 1.3`, `Provvedimento 1.4`
e `Provvedimento 1.7`. Nel namespace PySD i nomi includono le virgolette
Vensim, per esempio `"Provvedimento 1.2"`. `sure_pysd.build_params` usa una
ricerca che non elimina queste virgolette e omette i quattro parametri.

La prova ha rigenerato una copia da **`Vensim/SURE.mdl`**, riapplicando
l'adattamento CSV, PySD 3.14.3 e i postprocessori attuali:

- Equazioni adattate identiche a SURE v3 corrente; differenze solo nello sketch.
- Sei CSV equivalenti dopo normalizzazione delle terminazioni di riga.
- Nessuna differenza nei corpi delle funzioni Python generate.
- Scenario base rigenerato identico, valore per valore, al riferimento attuale.
- Nomi ancora quotati dopo la rigenerazione: serve correggere la loro risoluzione.

La correzione è verificata nell'adattatore sperimentale: prima il nome esatto,
poi la corrispondenza senza virgolette se univoca; gli errori non vengono
ignorati. Il modulo Julia riceve tutti e 20 i parametri esplicitamente.

| Provvedimento singolo attivato | Output modificati oltre la tolleranza | Primo anno |
|---|---:|---:|
| 1.2 | 51/52 | 2027 |
| 1.3 | 51/52 | 2027 |
| 1.4 | 51/52 | 2027 |
| 1.7 | 51/52 | 2027 |

Base, quattro provvedimenti singoli, tutti insieme, mid e high costituiscono
**otto configurazioni**, seguite da una ripetizione del base. Julia supera
**9/9 confronti** con il Python rigenerato: tutti i 52 output dell'app più
`Hourly demand and PHS`. La conservazione è superata in 9/9 casi per ciascun
motore; il ritorno al base è esatto in entrambi. Dopo la prima richiesta,
anche queste otto esecuzioni Julia registrano **zero JIT**.

Gli altri 49 ausiliari esportati da Julia sono conservati a fini diagnostici,
ma non sono dichiarati confrontati nei casi con provvedimenti attivi.
La matrice completa dei 43 scenari è certificata per il comportamento
storico; per il comportamento corretto la copertura è quella degli otto
casi appena elencati.

## Scarti numerici

Non è stato necessario cambiare ulteriormente le tolleranze autorizzate:
`1e-10 × max(1,S) + 1e-8 × |Python|`, con S massimo assoluto della stessa
serie elementare. Etichette, coordinate, anni e valori discreti restano esatti.

La suite storica conserva gli stessi errori della certificazione precedente:
massimo rapporto errore/tolleranza 0,19476; 45/46 esecuzioni superano anche la
soglia originale, con l'eccezione già nota `lever_00_00`.

Per i controlli corretti, il massimo rapporto errore/tolleranza è **0,43702**.
Cinque delle nove esecuzioni superano anche la soglia originale. Le altre
quattro hanno 41 valori complessivi oltre quella soglia, nelle variabili
di elettricità allocata, consumata o esportata; gli scarti nelle variabili
interessate non superano `8,75835e-11`. Il primo superamento è nel 2038.
Il massimo errore assoluto su tutte le variabili è `5,96046e-8`, come nella
suite precedente, su grandezze con scala molto maggiore.

Tutti gli avvisi sono conservati. Gli 82 avvisi di ogni esecuzione Python
sono messaggi già presenti nel riferimento: sostituzioni esplicite di
parametri ed estrapolazioni dei medesimi dati. Anche le interpolazioni al
caricamento e i metadati misti della traduzione sono verificati rispetto al
riferimento. Nessun nuovo avviso o costrutto ignorato è stato accettato.

## Prestazioni del riuso

Un processo nuovo carica un solo modulo, riscalda base, mid e high, poi
esegue cinque cicli base → mid → high. I provvedimenti sono applicati
correttamente anche in questo benchmark. Tutte le **18 simulazioni**,
compresi i riscaldamenti, superano il confronto dei 52 output con Python.
La verifica dei due orologi passa; nessuna sospensione ha alterato i tempi.

| Scenario | Mediana simulazione + estrazione | Min–max, 5 ripetizioni | JIT dopo il primo avvio |
|---|---:|---:|---:|
| Base | **4,742 s** | 4,707–5,030 s | 0 s |
| Mid | **4,766 s** | 4,744–5,095 s | 0 s |
| High | **4,766 s** | 4,678–5,059 s | 0 s |

Tempi singoli in secondi, nello stesso ordine dei cinque cicli:

- Base: 4,741646; 5,030492; 4,706829; 4,745683; 4,712484.
- Mid: 4,751013; 4,782819; 4,743728; 4,766142; 5,095441.
- High: 4,678224; 4,765930; 5,058852; 4,759431; 4,786756.

| Mediana per fase | Base | Mid | High |
|---|---:|---:|---:|
| Lettura/configurazione dei parametri | 0,0277 ms | 0,0318 ms | 0,0263 ms |
| Inizializzazione | 13,546 ms | 13,680 ms | 13,459 ms |
| Integrazione | 4,073 s | 4,085 s | 4,094 s |
| Estrazione dei 52 output | 0,652 s | 0,655 s | 0,655 s |

Le mediane delle fasi sono calcolate separatamente; la loro somma non deve
coincidere con la mediana del totale. Il picco RSS dell'intero processo è
**1.822.425.088 byte (circa 1,70 GiB)**, cumulativo sulle richieste.

Nel singolo campione di avvio di questa prova, il caricamento richiede
37,362 s e la prima simulazione/estrazione 32,180 s, dei quali 26,944 s
registrati dal contatore JIT. I 1,414 s di JIT durante il caricamento sono
già compresi nel suo tempo. Questi costi si pagano una volta per processo;
**tutte le successive 17 richieste registrano zero JIT**, anche al primo
passaggio a mid o high. Non è un nuovo benchmark statistico a freddo.

La misura dimostra il cambio di scenario sullo stesso codice compilato.
Non aggiunge un confronto Python con i provvedimenti corretti: i vecchi tempi
Python di mid/high descrivevano i controlli ignorati e non vanno utilizzati
per calcolare un'accelerazione di queste nuove configurazioni.

## Artefatti e limiti

Directory locale: `dist/julia-parametric/20261009`. Contiene copie rigenerate,
parametri applicati, output completi, avvisi, tempi, confronti e checksum.
I tentativi di preparazione interrotti sono conservati in directory distinte;
i rapporti finali PASS non li includono come simulazioni superate.

| Artefatto | SHA-256 |
|---|---|
| Modello parametrico | `a80f302afd90c5faf1bb6f9dccc94499e00d57804ee68d46470f3c4c5d15fb87` |
| `validate/report.json` | `3dc3b9210e522b1f5cb59e486c80acac6301bbd8d7787c7bd30302abcc54827f` |
| `controls/report.json` Python | `b16cc52b57835b996eeb861cd4ed3ae6bcf56616519fba62a1946dc1557dde33` |
| `controls-run/report.json` Julia | `6b6288b853799e03ca8edf6d65ea78315c013ee19a61b6ab5e10bad30962e0a8` |
| `benchmark/report.json` | `2cc8eeb00cc9a2a46a3a4b20e1bae267ec841d461b8c0dfb9edd710a106144e5` |
| `cross-process.json` | `672d2d627c60ba395b12d9849f5eff7a3fc6ef82501e6e6d00d5fa1e5c0272ad` |

Il riuso richiede un processo Julia persistente. Un riavvio paga nuovamente
caricamento e compilazione. Il prototipo offre le funzioni parametrizzate
e un worker che esegue richieste consecutive; non certifica ancora la latenza
di un servizio web, il trasporto dei risultati o richieste simultanee.

Restano applicabili i limiti del riferimento già documentati: seed hash
Python fissato a zero, ordine degli aggiornamenti specifico del modello
potato, ambiente macOS arm64 e comportamento dell'allocazione ereditato da
Python. Le verifiche di conservazione sui casi SURE passano; ciò non risolve
i controesempi sintetici dell'allocatore descritti nel rapporto precedente.
