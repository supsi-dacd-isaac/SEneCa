# Modello SURE supportato

**Questo ramo contiene un candidato FER da ricalibrare.** `SURE.mdl` e
`SURE_v6_pvbounded.mdl` includono la correzione storica del contributo cantonale;
per il collega usare il secondo, che conserva il limite condiviso delle adozioni.
La [nota FER](../docs/validation/FER_CANTONAL_CORRECTION.md) documenta modifiche,
verifiche e approssimazioni. I derivati dell’app restano alla revisione precedente:
non rigenerare simulazioni o pubblicare una release prima della ricalibrazione.

La revisione usata dall’app distribuita è **sure-v6-pv-budget-2**. Al commit
`3017fe4`, prima di questa correzione FER, i sorgenti allineati erano:

- `SURE_v6_pvbounded.mdl`: sorgente corretto per Vensim.
- `SURE_pysd_v6_pvbounded.mdl`: sorgente corretto preparato per PySD e Julia.
- `SURE_pysd_v6_pvbounded.py`: riferimento Python della stessa correzione.

`SURE_pysd_v7.mdl` è la copia del `SURE.mdl` pubblicato il 16 ottobre 2026, con
gli input VDF convertiti in CSV. `SURE_pysd_v7.py` è la relativa traduzione
PySD 3.14.3, con gli stessi post-process della v6 per le equazioni
auto-referenziali e `ALLOCATE AVAILABLE`. Rispetto alla v6 il modello cambia
sei equazioni sul fotovoltaico (potenziali, quote e soglia 2022 del sussidio
cantonale) e la serie storica `HPinput`. Le 31 costanti calibrate restano quelle
della v6. `SURE_pysd_v6.mdl` e `SURE_pysd_v6.py` restano la traduzione della
revisione precedente.

La presenza delle 20 leve e delle famiglie di output live si controlla con:

```powershell
$env:SURE_VARIANT = "v7"
.\.venv\Scripts\python.exe retranslate_sure_pipeline.py --check --variant v7
.\.venv\Scripts\python.exe -m unittest tests.test_pysd_translation
```

Il confronto con il `.vpmx` pubblicato, su 60 famiglie e quattro scenari, lascia
232 confronti su 240 entro la tolleranza pratica. Lo scenario base è interamente
entro tolleranza. Fuori restano il prezzo dell’energia e il dispacciamento orario
negli scenari estremi, come nelle traduzioni v3–v6. Finché il candidato non viene
ricalibrato e gli store non vengono rigenerati, `SURE_pysd_v7.py` non deve
sostituire il modello di produzione `SURE_pysd_v6_pvbounded.py`.

Gli input `*_pysd_v7.csv` e `../constants_ref_v7.pkl` appartengono a questa
traduzione. I CSV `*_pysd_v6.csv` e `../constants_ref_v6.pkl` restano quelli della
revisione precedente. I CSV senza suffisso sono anche sorgenti degli storici
mostrati nell’interfaccia. `SURE.vpmx` e i `.vdfx` arrivano dalla release dati
immutabile e non sostituiscono il modello corretto.

La [mappa del repository](../docs/repository-inventory.md) descrive le
dipendenze conservate. Le versioni v2–v5 si recuperano dal tag `v0.3.1`.
