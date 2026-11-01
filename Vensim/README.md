# SURE v8 con EMS (variante ems1)

Usare `SURE.mdl`: è il modello v8 con il modulo dei sistemi di gestione
dell'energia residenziali (vista "Utility EMS"), copiato da
`SUREwork/model/SURE.mdl` il 1° novembre 2026. Le equazioni precedenti al
modulo coincidono con la v8 (`SURE_before_ems.mdl` differisce solo nelle
impostazioni salvate da Vensim). `SURE_pysd_ems1.mdl` e `.py` sono i derivati
per Python e Julia; `patch_model_sure.py` garantisce `FINAL TIME = 2050`.

Il modulo EMS valuta l'adozione di un EMS a ogni nuova adozione FV
residenziale (individuale e RCPv), con e senza auto elettrica che ricarica a
casa. L'autoconsumo aggiuntivo (`EMS self consumption by District`) è sommato
a `PV electricity SC by District`, quindi riduce l'immissione in rete e la
domanda servita dalla rete; la spesa del rebate (`EMS rebate spending`) entra
in `Annual Total Cantonal Subsidy`. `Alpha EMS` = 0.5078 è tarato perché il
30 % dei nuovi impianti FV residenziali del 2025 abbia un EMS.

`Buildings PVno connected to RCPv` è il numero di edifici senza FV collegati
a ogni edificio RCPv: agisce solo con `Energy Community scenario` = 1, perché
le richieste RCPv sono moltiplicate per quell'interruttore.

I quattro file `calibration/*.out` sono identici a quelli v8 (anche in
`SUREwork/model/out and calibration files`). Il manifest registra 53
assegnazioni e 30 gruppi; `constants_ref_ems1.pkl` viene ricostruito dai
decimali originali in Float64, senza ricalibrazione. I sei VDFX e i CSV
esportati sono quelli v8 della cartella WP13: HPinput, Input2011,
InputRenovation e PVinput di `SUREwork/model` (26 ottobre) sono diversi e non
sono usati.

```shell
python scripts/import_calibration.py --check
python -m sure_julia.pv_budget --check
python retranslate_sure_pipeline.py --run --variant ems1 --skip-export --reuse-constants constants_ref_ems1.pkl
python -m unittest discover -s tests
```

Correzione in `Calendar order fraction` (1° novembre 2026, riportata dalla
v8): il termine al netto degli ordini pendenti usa `XIDZ(..., 1)` invece di
`ZIDZ`. Con meno di 1e-6 edifici disponibili `ZIDZ` restituiva 0 e il
calendario accettava nuovi ordini oltre lo stock (stock negativo di 3,7e-8
edifici nello scenario PV 0,2/0,4 al 2042, anche in Vensim nativo).

`GAMMA LN` non è implementata da PySD 3.14.3: `fix_functions_sure.py` la
sostituisce con `scipy.special.gammaln`. Serve solo all’obiettivo di
calibrazione NR, non alla dinamica.

Gli store delle pagine "Simulazioni SEneCa" si rigenerano con il backend
Python (`python -m sure_julia.python_batch`). La release Julia richiede
ancora la build, la validazione Python–Julia e la rigenerazione completa
descritte nella [guida Julia](../docs/julia-production.md).
