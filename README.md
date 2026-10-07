# SEneCa — modello SURE per la transizione energetica in Ticino

Webapp Streamlit costruita sul modello di system dynamics **SURE**, che simula la
transizione energetica del Canton Ticino dal 2011 al 2050: adozione del
fotovoltaico e delle batterie residenziali, risanamento degli edifici e
sostituzione dei sistemi di riscaldamento, elettrificazione della mobilita',
bilancio orario del sistema elettrico e ricadute sul prezzo dell'elettricita'.

Il modello e' sviluppato in Vensim e tradotto in Python con
[PySD](https://pysd.readthedocs.io/), cosi' che la webapp possa sia servire
scenari pre-calcolati sia lanciare simulazioni live.

## Licenza

Questo repository è distribuito con licenza MIT; vedi [LICENSE](LICENSE).

## Requisiti

- Python 3.11 o superiore
- [Git LFS](https://git-lfs.com/): gli store pre-calcolati e i sorgenti Vensim
  sono tracciati con LFS, senza di esso il clone scarica solo i puntatori
- Vensim DSS con `vendll64.dll` — necessario **solo** per rigenerare gli store
  pre-calcolati o ritradurre il modello, non per usare la webapp

## Installazione

```bash
git lfs install
git clone https://github.com/supsi-dacd-isaac/SEneCa.git
cd SEneCa

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
| `precomputed/` | Store degli scenari pre-calcolati, in formato parquet |
| `Vensim/` | Modello `SURE.mdl`/`.vpmx`, traduzione PySD e dati di input |
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
