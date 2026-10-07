# SEneCa — modello SURE per la transizione energetica in Ticino

Webapp Streamlit costruita sul modello di system dynamics **SURE**, che simula la
transizione energetica del Canton Ticino dal 2011 al 2050: adozione del
fotovoltaico e delle batterie residenziali, risanamento degli edifici e
sostituzione dei sistemi di riscaldamento, elettrificazione della mobilita',
bilancio orario del sistema elettrico e ricadute sul prezzo dell'elettricita'.

Il modello e' sviluppato in Vensim e tradotto in Python con
[PySD](https://pysd.readthedocs.io/), cosi' che la webapp possa sia servire
scenari pre-calcolati sia lanciare simulazioni live.

## Riconoscimenti

Il modello SEneCa e questa applicazione sono stati sviluppati da SUPSI
nell'ambito del [caso di studio del Canton Ticino](https://sweet-sure.ch/case-studies/)
del progetto [SWEET SURE – Sustainable and Resilient Energy for Switzerland](https://sweet-sure.ch/).
SURE è coordinato dal Paul Scherrer Institut e sostenuto dall'Ufficio federale
dell'energia (UFE) attraverso il programma SWEET.

## Licenza

Questo repository è distribuito con licenza MIT; vedi [LICENSE](LICENSE).

## Requisiti

- Python 3.11 o superiore
- I dati binari sono distribuiti nella [release dati pinata](data-release.json),
  non nel checkout Git corrente; Git LFS non serve per i nuovi cloni
- Vensim DSS con `vendll64.dll` — necessario **solo** per rigenerare gli store
  pre-calcolati o ritradurre il modello, non per usare la webapp

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
streamlit run app.py
```

La cartella di progetto deve essere sul `PYTHONPATH`; da Windows PowerShell:

```powershell
$env:PYTHONPATH = $PWD
.venv\Scripts\python.exe -m streamlit run app.py
```

Se il download dei dati fallisce o un checksum non corrisponde, l'avvio va
interrotto: non utilizzare vecchi file LFS come alternativa. Per versioni e
aggiornamenti dei dati vedi [la guida alle release dati](docs/data-releases.md).

## Docker

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
una versione o fare rollback, impostare `SENECA_IMAGE_TAG=v0.1.0` (o un altro
tag pubblicato) prima dei comandi. `SENECA_PORT` cambia la porta host, che di
default è 8501. Entrambi i Compose leggono la chiave CARTO solo a runtime.

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
| `pv_batteries/` | Renderer, configurazioni di sezione e script di pre-calcolo |
| `precomputed/` | Store Parquet installati dalla release dati pinata |
| `Vensim/` | Modello `.mdl`, traduzione PySD e input binari dalla release dati |
| `content/system_dynamics/` | Testi, immagini e dati della pagina divulgativa |

## Le pagine

Le quattro pagine di risultati (`PV e Batterie`, `Riscaldamento e Risanamento`,
`Veicoli`, `Elettricita'`) servono all'istante combinazioni gia' simulate: si
scelgono le leve di policy con gli slider e il confronto con lo scenario Base e'
immediato. `Simulazione in tempo reale` lancia invece una simulazione live su
tutte le leve disponibili, al costo di alcuni minuti per run.

## Rigenerare gli store pre-calcolati

Ogni sezione ha il suo script di batch, che richiede Vensim DSS:

```bash
python pv_batteries/precompute_pv_batteries.py
python pv_batteries/precompute_risanamento.py
python pv_batteries/precompute_veicoli.py
python pv_batteries/precompute_elettricita.py
```

## Ritradurre il modello da Vensim a PySD

La pipeline applica al modello le patch necessarie a PySD, lo traduce, corregge
autoriferimenti e allocazioni, ed estrae le costanti di riferimento:

```bash
python retranslate_sure_pipeline.py --variant v3
python validate_coherence_sure.py --variant v3
```

Ogni traduzione vive in una **variante** identificata da un suffisso
(`SURE_pysd_v2.py`, `constants_ref_v2.pkl`, ...), cosi' che piu' versioni
convivano nella stessa cartella. Senza la variabile d'ambiente `SURE_VARIANT` il
codice risolve automaticamente sulla traduzione piu' recente presente in
`Vensim/`.
