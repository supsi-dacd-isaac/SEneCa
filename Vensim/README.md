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

`SURE.mdl` conserva la struttura upstream precedente al limite condiviso delle
adozioni FV, ora con la correzione FER. `SURE_pysd_v6.mdl` e `SURE_pysd_v6.py`
restano al sorgente upstream precedente anche alla correzione FER. Servivano a
`sure_julia.pv_budget --check` per dimostrare quali equazioni sono cambiate;
su questo ramo la verifica completa e i manifest devono essere riallineati solo
dopo la ricalibrazione. Non rappresentano un nuovo modello accettato per l’app.

Gli input `*_pysd_v6.csv` e `../constants_ref_v6.pkl` appartengono alla
revisione supportata. I CSV senza suffisso sono anche sorgenti degli storici
mostrati nell’interfaccia. `SURE.vpmx` e i `.vdfx` arrivano dalla release dati
immutabile e non sostituiscono il modello corretto.

La [mappa del repository](../docs/repository-inventory.md) descrive le
dipendenze conservate. Le versioni v2–v5 si recuperano dal tag `v0.3.1`.
