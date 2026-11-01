# SURE v8 canonico

Usare `SURE.mdl`: rispetto alla v7 aggiunge il sottomodello FV non
residenziale (`NR class`, verosimiglianza binomiale negativa), il calendario
delle installazioni FV, l’economia "Study" degli incentivi storici, il rebate
federale interpolato e le perdite delle batterie residenziali. Mantiene la
correzione FER, il budget condiviso delle adozioni PV e il dispatch
`ALLOCATE BY PRIORITY`. `SURE_pysd_v8.mdl` e `.py` sono i derivati per
Python e Julia. Il sorgente è salvato in configurazione di calibrazione
(`FINAL TIME = 2025`): `patch_model_sure.py` porta il derivato a 2050.

I quattro file `calibration/*.out` sono quelli ricevuti il 30 ottobre 2026
(`WP13/Vensim/TI/Claude/out and calibration files`). `PV power.out` non
esiste più: i parametri NR sono nel modello. Il manifest registra 53
assegnazioni e 30 gruppi; `constants_ref_v8.pkl` viene ricostruito dai
decimali originali in Float64, senza ricalibrazione.

I sei VDFX vengono dalla stessa cartella. Senza `vendll64.dll` i CSV si
esportano aprendo Vensim DSS con uno script di comandi, gli stessi della DLL:

```text
SPECIAL>LOADMODEL|SURE.mdl
MENU>VDF2TAB|PVinput.vdfx|PVinput.tab||
...
MENU>EXIT
```

`vendss64.exe export.cmd` scrive i `.tab`; `tab_to_csv` di
`pysd_export_vdf.py` li converte nei CSV. EVinput e Input Hour Factors,
invariati, riproducono byte per byte i CSV v7. PVinput non contiene più
le capacità 30–100 e >100 kW: lo storico del grafico è esportato da
`scripts/export_nr_history.py`.

```shell
python scripts/import_calibration.py --check
python -m sure_julia.pv_budget --check
python retranslate_sure_pipeline.py --run --variant v8 --skip-export --reuse-constants constants_ref_v8.pkl
python -m unittest discover -s tests
```

Correzione del 1° novembre 2026 in `Calendar order fraction`: il termine
al netto degli ordini pendenti usa `XIDZ(..., 1)` invece di `ZIDZ`. Con
meno di 1e-6 edifici disponibili `ZIDZ` restituiva 0 e il calendario
accettava nuovi ordini oltre lo stock (stock negativo di 3,7e-8 edifici
nello scenario PV 0,2/0,4 al 2042, anche in Vensim nativo).

`GAMMA LN` non è implementata da PySD 3.14.3: `fix_functions_sure.py` la
sostituisce con `scipy.special.gammaln`. Serve solo all’obiettivo di
calibrazione NR, non alla dinamica.

Gli store delle pagine "Simulazioni SEneCa" possono essere rigenerati con
il backend Python (`python -m sure_julia.python_batch`). La release Julia
richiede ancora la build, la validazione Python–Julia e la rigenerazione
completa descritte nella [guida Julia](../docs/julia-production.md).
Le versioni v7 sono recuperabili nella storia Git.
