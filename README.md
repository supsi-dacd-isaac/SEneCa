# SEneCa — modello SURE per la transizione energetica in Ticino

Webapp Streamlit costruita sul modello di system dynamics **SURE**, che simula la
transizione energetica del Canton Ticino dal 2011 al 2050: adozione del
fotovoltaico e delle batterie residenziali, risanamento degli edifici e
sostituzione dei sistemi di riscaldamento, elettrificazione della mobilita',
bilancio orario del sistema elettrico e ricadute sul prezzo dell'elettricita'.

Il modello è sviluppato in Vensim e tradotto con
[PySD](https://pysd.readthedocs.io/). La webapp serve scenari precalcolati e
simulazioni live di SURE v6 con Julia; il backend Python resta selezionabile.
La release `v0.3.0` usa il modello corretto `sure-v6-pv-budget-2` e i dati
`data-v1.2.0`: 14.571 simulazioni distinte coprono 14.579 configurazioni,
incluse 12.800 combinazioni di policy mix e incertezza con nove KPI.
Il limite condiviso delle adozioni FV impedisce di prelevare edifici oltre
la disponibilità della categoria di origine. Validazione e provenienza sono
descritte nel [rapporto del modello corretto](docs/validation/PV_BUDGET_RESULTS.md)
e nel [rapporto dei 100 campioni](docs/validation/POLICY_MIX_RESULTS.md).

## Riconoscimenti

Il modello SEneCa e questa applicazione sono stati sviluppati da SUPSI
nell'ambito del [caso di studio del Canton Ticino](https://sweet-sure.ch/case-studies/)
del progetto [SWEET SURE – Sustainable and Resilient Energy for Switzerland](https://sweet-sure.ch/).
SURE è coordinato dal Paul Scherrer Institut e sostenuto dall'Ufficio federale
dell'energia (UFE) attraverso il programma SWEET.

## Licenza

Questo repository è distribuito con licenza MIT; vedi [LICENSE](LICENSE).

## Requisiti

- Docker per l'ambiente completo, con Python 3.11.8 e Julia 1.10.12 bloccati
- Python 3.11.8 per l'esecuzione da sorgenti con il backend Python
- I dati binari sono distribuiti nella [release dati pinata](data-release.json),
  non nel checkout Git corrente; Git LFS non serve per i nuovi cloni
- Vensim DSS con `vendll64.dll` serve solo per i confronti con il motore
  Vensim e la relativa estrazione delle costanti; il batch Julia non lo richiede

## Installazione

```bash
git clone https://github.com/supsi-dacd-isaac/SEneCa.git
cd SEneCa

python scripts/data_release.py fetch
python scripts/data_release.py verify
python -m venv .venv
.venv\Scripts\activate        # su Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Avvio della webapp

```bash
SURE_BACKEND=python streamlit run server.py
```

Questo comando usa l'ambiente Python installato sopra. Per Julia usare
l'immagine Docker, che contiene già runtime, dipendenze e modello tradotto.
`SURE_BACKEND=julia` è il default nell'immagine; `SURE_BACKEND=python` seleziona
esplicitamente l'altro motore. Errori Julia non provocano un cambio automatico
di backend. Preparazione, validazione e batch sono descritti nella
[guida Julia](docs/julia-production.md).

La cartella di progetto deve essere sul `PYTHONPATH`; da Windows PowerShell:

```powershell
$env:PYTHONPATH = $PWD
$env:SURE_BACKEND = "python"
.venv\Scripts\python.exe -m streamlit run server.py
```

Se il download dei dati fallisce o un checksum non corrisponde, l'avvio va
interrotto: non utilizzare vecchi file LFS come alternativa. Per versioni e
aggiornamenti dei dati vedi [la guida alle release dati](docs/data-releases.md).

## Docker

Per provare le modifiche dell'interfaccia con il runtime Julia e i dati della
release `v0.3.1`, senza ricompilare il modello:

```bash
docker compose -f docker-compose.local.yml up -d
```

L'app è disponibile su `http://localhost:8502` (solo sul computer locale).
`SENECA_LOCAL_PORT` cambia la porta. Il container `seneca-streamlit-local`
legge le pagine, i renderer e i contenuti dal checkout corrente, in sola
lettura; le equazioni, il modello Julia compilato e i dati restano quelli
dell'immagine. Questa modalità serve per modifiche all'interfaccia: per
cambiamenti alle equazioni o alle dipendenze usare la build completa sotto.

Le pagine live e precalcolate condividono KPI e radar; gli indici di equità
live usano gli stessi limiti di riferimento dei precalcolati. I grafici
compatibili permettono di scegliere valori annui/cumulati e mostrare i dati
storici. Per la potenza FV, il punto annuo `t` rappresenta l'incremento da
`t` a `t+1`: il 2050 resta senza incremento perché manca il punto 2051.
I cumulati di flussi sommano gli anni visibili, incluso quello indicato;
non sostituiscono gli stock del modello né i KPI esistenti. Le adozioni
storiche in numero di edifici hanno un confronto dedicato, separato dai MW.

Per lo sviluppo locale, dopo `python scripts/data_release.py fetch`, il Compose
principale costruisce l'immagine dal codice corrente:

```bash
docker compose up --build -d
```

Per la produzione, il Compose dedicato usa l'immagine pubblica su GHCR e non
richiede i dati nel checkout locale. Il tag predefinito è `latest`:

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Una nuova release non aggiorna da sola il container in esecuzione: l'operatore
esegue questi comandi quando decide di distribuire la versione. Per fissare
una versione o fare rollback, impostare `SENECA_IMAGE_TAG=v0.3.0` (o un altro
tag pubblicato) prima dei comandi. Per ripristinare `v0.1.1` impostare anche
`SURE_VARIANT=v3` e `SURE_BACKEND=python`; v0.2.0 e v0.3.0 usano v6.
`SENECA_PORT` cambia la porta host, che di
default è 8501. Entrambi i Compose leggono la chiave CARTO solo a runtime.

### Controlli PR e pubblicazione

Le PR eseguono i test unitari e dell'interfaccia con Python e dati bloccati,
senza costruire le immagini o compilare Julia. Un nuovo push annulla il
controllo della versione precedente della stessa PR.

Le release codice costruiscono e verificano le immagini AMD64 e ARM64 una sola
volta, inclusi confronto numerico Python–Julia, invarianti fisici, interfaccia
e avvio reale del server. Vengono pubblicate esattamente le immagini verificate.
Per modifiche a modello, runtime, dipendenze o Docker, eseguire anche il workflow
`Build and publish SEneCa image` manualmente sul branch prima del merge:

```bash
gh workflow run docker-release.yml --ref NOME_BRANCH
```

Questo controllo manuale non pubblica immagini. La cache delle dipendenze e del
modello è condivisa su GHCR per architettura; soltanto release e controlli su
`main` possono aggiornarla. Il primo ciclo deve popolarla; i successivi la
riutilizzano. Le pagine dell'app vengono copiate dopo la traduzione, così una
modifica a una pagina non invalida la costruzione del modello.

### Mappa CARTO

La mappa nella pagina "Approccio System Dynamics" usa una chiave CARTO
Basemaps. Copia `.env.example` in `.env` nella cartella del progetto e inserisci
la tua `CARTO_API_KEY`, oppure imposta la stessa variabile nell'ambiente prima
di avviare Streamlit. `.env` è escluso da Git. La chiave viene aggiunta alle
richieste delle tile effettuate dal browser, quindi resta visibile a chi usa la
pagina: limita il suo utilizzo nel pannello CARTO.

## Struttura

| Percorso | Contenuto |
| --- | --- |
| `app.py`, `pages/` | Router multipagina e le sette pagine Streamlit |
| `pv_batteries/` | Renderer, configurazioni e lettura degli store |
| `precomputed/` | Store Parquet installati dalla release dati pinata |
| `sure_julia/` | Traduttore SURE, runtime persistente, validazione e batch |
| `Vensim/` | Modello corretto, sorgenti upstream necessari alla verifica e input |
| `model_checks/`, `tests/` | Casi sintetici e test del modello e dell’app attuali |
| `docs/validation/` | Prove della correzione FV e della generazione dei dati |
| `content/system_dynamics/` | Testi, immagini e dati della pagina divulgativa |

## Le pagine

Le quattro pagine di risultati (`PV e Batterie`, `Riscaldamento e Risanamento`,
`Veicoli`, `Elettricita'`) servono all'istante combinazioni gia' simulate: si
scelgono le leve di policy con gli slider e il confronto con lo scenario Base e'
immediato. `Simulazione in tempo reale` lancia invece una simulazione live su
tutte le leve disponibili. All'avvio del server Julia esegue una simulazione
di riscaldamento, prima che l'app accetti connessioni. Lo stesso processo
rimane disponibile alle sessioni degli utenti e riusa il codice compilato;
ogni scenario ricostruisce gli stati iniziali. Il costo iniziale di compilazione
si paga quindi al riavvio del servizio. Un errore nel riscaldamento interrompe
l'avvio, senza passare automaticamente a Python. Il controllo di salute diventa
disponibile solo dopo questa preparazione (il container concede fino a cinque
minuti di avvio). Usare `server.py` anche fuori da Docker; `app.py` resta lo
script dell'interfaccia e, avviato direttamente, carica il worker alla prima richiesta.

La simulazione live mostra le fasi di preparazione, calcolo, estrazione e
verifica dei risultati. La barra segnala le fasi effettive, senza stimare il
tempo rimanente. La pagina `Policy mix e incertezza` confronta 128 mix su 100
campioni comuni: tutti i nove KPI sono disponibili nei grafici e nella
classifica pesata. Il nuovo KPI mostra la domanda elettrica coperta dal FV
autoconsumato al 2050. Definizioni e campionamento sono descritti nella
[guida dedicata](docs/policy-mix-100.md).

## Rigenerare gli store pre-calcolati

Il batch di produzione usa 32 processi Julia persistenti, con validazione
Python–Julia obbligatoria e checkpoint verificati. Seguire la
[procedura di rigenerazione](docs/julia-production.md).

Gli esperimenti e i generatori Vensim delle vecchie versioni sono recuperabili
nel tag `v0.3.1`. Non usarli per rigenerare gli store del modello corretto.

## Sorgenti del modello e manutenzione

Il modello eseguito è `SURE_pysd_v6_pvbounded`, con revisione
`sure-v6-pv-budget-2`. I sorgenti `SURE.mdl`, `SURE_pysd_v6.mdl` e
`SURE_pysd_v6.py` rimangono come input e riferimento per la generazione e
la verifica della correzione; non sono modelli alternativi da eseguire nell’app.
I loro checksum fanno parte della provenienza della release dati.

La correzione riproducibile si genera e si controlla con:

```bash
PYTHONHASHSEED=0 python -m sure_julia.pv_budget --check
```

La pipeline `retranslate_sure_pipeline.py` e i relativi script preparano un
nuovo sorgente upstream da Vensim: non producono da soli un modello validato
per l’app. Una modifica alle equazioni richiede la procedura completa nella
[guida Julia](docs/julia-production.md), inclusa la rigenerazione dei dati.
Senza `SURE_VARIANT` viene selezionata la base supportata `v6`.

La [mappa del repository](docs/repository-inventory.md) distingue file necessari,
strumenti di manutenzione e materiale storico rimosso. Le vecchie versioni e
le diagnosi restano recuperabili in Git; non vengono mescolate con il modello
supportato nel checkout corrente.
