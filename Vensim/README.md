# Modello SURE supportato

La revisione usata dall’app è **sure-v6-pv-budget-2**:

- `SURE_v6_pvbounded.mdl`: sorgente corretto per Vensim.
- `SURE_pysd_v6_pvbounded.mdl`: sorgente corretto preparato per PySD e Julia.
- `SURE_pysd_v6_pvbounded.py`: riferimento Python della stessa correzione.

`SURE.mdl`, `SURE_pysd_v6.mdl` e `SURE_pysd_v6.py` conservano il sorgente
upstream precedente al limite condiviso delle adozioni FV. Servono a
`sure_julia.pv_budget --check` per dimostrare quali equazioni sono cambiate;
non rappresentano il modello accettato per le simulazioni dell’app.

Gli input `*_pysd_v6.csv` e `../constants_ref_v6.pkl` appartengono alla
revisione supportata. I CSV senza suffisso sono anche sorgenti degli storici
mostrati nell’interfaccia. `SURE.vpmx` e i `.vdfx` arrivano dalla release dati
immutabile e non sostituiscono il modello corretto.

La [mappa del repository](../docs/repository-inventory.md) descrive le
dipendenze conservate. Le versioni v2–v5 si recuperano dal tag `v0.3.1`.
