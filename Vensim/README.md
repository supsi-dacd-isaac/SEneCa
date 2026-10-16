# SURE v7 canonico

Usare `SURE.mdl`: contiene la calibrazione v7, la correzione FER, il budget
condiviso delle adozioni PV e il dispatch `ALLOCATE BY PRIORITY`.
`SURE_pysd_v7.mdl` e `.py` sono i derivati per Python e Julia.

I cinque file `calibration/*.out` sono quelli ricevuti il 16 ottobre 2026.
Il manifest registra 56 assegnazioni e 33 gruppi; `constants_ref_v7.pkl`
viene ricostruito dai decimali originali in Float64, senza ricalibrazione.
I CSV correnti sono la sorgente dei dati: i VDFX nativi vanno rigenerati
da questi CSV, in particolare HPinput, e non copiati dal vecchio ZIP.

```shell
python scripts/import_calibration.py --check
python -m sure_julia.pv_budget --check
python retranslate_sure_pipeline.py --run --variant v7 --skip-export --reuse-constants constants_ref_v7.pkl
python -m unittest discover -s tests -p test_dispatch.py
```

La [diagnosi numerica](../docs/validation/dispatch-correction.md) distingue
l’errore residuo dell’allocatore Vensim dalla validazione Python–Julia.
La nuova release è subordinata ai controlli completi e alla rigenerazione.
Le versioni v6 sono recuperabili nella storia Git; i vecchi VPMX non sono
modelli alternativi supportati.
