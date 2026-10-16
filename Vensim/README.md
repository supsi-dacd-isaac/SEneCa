# Candidato SURE v7 con correzione del dispatch

**Per questa verifica usare `SURE.mdl` di questo branch.** Deriva dalla v7
`7950c32`, conserva i suoi parametri PV e applica la correzione del dispatch
`11bdbca`. Non usare `SURE_v6_pvbounded.mdl` o un vecchio `.vpmx` per validarlo.

- `SURE.mdl`: sorgente nativo da verificare e pubblicare nuovamente in Vensim.
- `SURE_pysd_v7.mdl` e `SURE_pysd_v7.py`: derivati della stessa versione.
- `*_pysd_v7.csv` e `constants_ref_v7.pkl` nella radice: input e costanti v7.
- `HPinput.csv`: riallineato allo storico già esportato per v7; gli altri CSV
  sorgente e le 31 costanti calibrate restano invariati.

Le [istruzioni per il collega](../docs/validation/DISPATCH_HANDOFF.md) indicano
commit, pacchetti Vensim, comandi, soglie e risultati da restituire. La
[nota tecnica](../docs/validation/dispatch-correction.md) descrive l'intervento.
La conferma nativa e la verifica della calibrazione sono ancora necessarie:
**questo candidato non autorizza una release**.

La conversione PySD viene gestita da noi. Per riprodurla dagli export presenti:

```shell
python retranslate_sure_pipeline.py --run --variant v7 --skip-export --reuse-constants constants_ref_v7.pkl
python -m unittest discover -s tests -p test_fer_cantonal.py
python -m unittest discover -s tests -p test_dispatch.py
python -m unittest discover -s tests -p test_v7_input_alignment.py
python scripts/check_dispatch.py --python
```

Usare l'ambiente di `requirements.txt` (PySD 3.14.3). La traduzione riusa la
calibrazione, senza validarla. Il modello nativo legge ancora i VDFX: occorrono
quelli aggiornati della v7, coerenti con i CSV, inclusi nel nuovo pacchetto.

Il runtime dell'app resta `sure-v6-pv-budget-2`, con
`SURE_pysd_v6_pvbounded.py` e i suoi artefatti. I file v6 sono conservati ma
non sono il riferimento per questa verifica v7. I report di validazione
precedenti non certificano il nuovo candidato.
