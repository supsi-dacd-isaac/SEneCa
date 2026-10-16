# File del repository e modello supportato

La release `v0.4.0` usa **sure-v7-dispatch-1** e la calibrazione
ricevuta il 16 ottobre 2026. I dati v6 già pubblicati restano immutabili;
la v7 usa il dataset rigenerato `data-v2.0.0`.
Tutto il materiale rimosso resta recuperabile nel
[tag v0.3.1](https://github.com/supsi-dacd-isaac/SEneCa/tree/v0.3.1).

## File da mantenere

| File o cartella | Motivo |
| --- | --- |
| `server.py`, `app.py`, `pages/`, `.streamlit/` | Avvio, navigazione e interfaccia dell’app. |
| `pv_batteries/` | Configurazioni, lettura degli store, indicatori, grafici e contenuti divulgativi. |
| `sure_backend.py`, `sure_live.py`, `sure_pysd.py`, `sure_paths.py`, `pysd_explore_config.py` | Selezione del motore, processo live, parametri e adattatore Python. |
| `sure_julia/` | Generazione Julia, motori, controlli fisici, validazione e batch del modello corretto. L’allocatore corrente è `priority_allocation.jl`. |
| `Vensim/SURE.mdl` | Unico sorgente nativo v7, con FER, budget PV e dispatch corretti. |
| `Vensim/SURE_pysd_v7.mdl`, `.py` e `*_pysd_v7.csv` | Traduzione Python e input del medesimo modello. |
| `Vensim/calibration/*.out`, `manifest.json`, `constants_ref_v7.pkl` | Cinque file ricevuti, 56 assegnazioni originali e 33 gruppi ricostruiti in Float64. |
| CSV nativi in `Vensim/` | Storici mostrati nell’app e sorgenti dei dati preparati per PySD. |
| `content/system_dynamics/` restante | Immagini, mappa, storici e priorità del workshop effettivamente letti dalle pagine. |
| `calibration_sim_adoptions_v7.csv` e `.json` | Curve della baseline v7 per il confronto di calibrazione, con provenienza e verifica contro la baseline validata. Gli osservati arrivano da `PVinput.csv`, `HPinput.csv` ed `EVinput.csv`. |
| `Input and Output Streamlit.xlsx` | Specifica delle leve e degli output, verificata dai test e registrata nella provenienza del batch. |
| `SEneCa_documentation.pdf` | Documento scaricabile dalla home. |
| `data-release.json`, `scripts/data_release.py` | Identità, download e verifica del dataset immutabile. |
| `model_checks/`, `tests/` | Casi sintetici e test del traduttore, del motore e dell’interfaccia attuali. |
| `docs/validation/` | Evidenze della correzione FV, del batch e dell’avvio. Non sono copie eseguibili di vecchi modelli. |
| Dockerfile, Compose, workflow, lock delle dipendenze, `deploy/` | Build, verifica e distribuzione riproducibili. |

Le versioni v6, le copie `pvbounded`, il vecchio pickle e gli script di
`Vensim_test_runs/` sono rimossi. Le fixture ancora utili sono conservate in
`model_checks/dispatch_vectors.npy` e il ponte Windows in `vensim_windows.py`.
La provenienza del nuovo batch registra tutti i sorgenti v7 e i file OUT.

Dalla patch `v0.4.1`, i grafici di calibrazione ricavano il periodo dai valori
disponibili per ogni tecnologia: PV e pompe di calore includono il 2025,
batterie e veicoli si fermano al 2024. Il CSV delle curve simulate copre
l'unione di questi anni; ogni grafico mostra soltanto il proprio periodo
osservato. I valori mancanti restano mancanti, anche nei cumulati.
Le serie di potenza PV riportano tutti i punti presenti nell'input, fino al
2026; la variazione fra due punti consecutivi è disponibile fino al 2025.
La patch conserva modello, calibrazione e dataset `data-v2.0.0` della v0.4.0.

## Materiale rimosso dal checkout

| Gruppo | Contenuto e sostituzione |
| --- | --- |
| Varianti v2–v5 | `SURE_pysd_v2` … `SURE_pysd_v5` in `.mdl` e `.py`, i relativi `*_pysd_vN.csv` e `constants_ref_vN.pkl`: 36 file. Nessun backend attuale li usa. |
| Rapporti rigenerabili | `coherence_report_v*.csv` e `constants_mismatch_v*.csv`: sei output di diagnosi, non input del modello. |
| CSV divulgativi superati | `Calibration_PV.csv`, `Calibration_HP.csv`, `calibration_sim_adoptions.csv`, `Annual adoption HP.csv`, `Annual adoption HT.csv`: nessun lettore attuale. |
| Selezioni e risultati Vensim storici | `Vensim/out and calibration files/` e `Vensim_test_runs/outputs.parquet`. I dieci scenari di input utili sono conservati in `model_checks/native_scenarios.json`. |
| Esperimenti Julia precedenti | `scripts/julia_repro/`, `scripts/julia_parametric/`, `scripts/sure_v4/`, `scripts/vensim_comparison/`, i relativi driver e test dei runner ritirati. I casi sintetici usati dalla validazione corrente sono trasferiti in `model_checks/`; i test dei componenti ancora supportati verificano direttamente `sure_julia/`. |
| Vecchi batch Vensim | `_run_precompute.py`, `pv_batteries/precompute_*.py`, `section_engine*.py`, `vensim_runner.py`. La rigenerazione supportata passa per `sure_julia.batch` e `scripts/prepare_model_release.sh`. |
| Strumenti di confronto superati | `diff_sure_mdl.py`, `export_vensim_test_runs.py`, `validate_coherence_sure.py`. Le verifiche correnti sono in `sure_julia.validation`, `physical`, `smoke` e `scripts/verify_*.py` rimasti. |
| Vecchie diagnosi e prototipi | `benchmarks/`, dopo aver trasferito le prove del modello corretto in `docs/validation/`. La correzione provvisoria `legacy_stock_limits.py` non viene più distribuita. |

## Strumenti di manutenzione conservati

`retranslate_sure_pipeline.py`, `_translate.py`, `pysd_export_vdf.py`,
`patch_model_sure.py`, `extract_constants_sure.py` e `patch_hotpaths_sure.py`
servono alla preparazione di un nuovo sorgente upstream. Non sono il percorso
di esecuzione dell’app e non certificano da soli un nuovo modello.
`fix_selfref_sure.py` e `fix_allocate_sure.py` sono anche dipendenze dirette
della generazione del riferimento corretto e devono restare.

La procedura completa è nella [guida Julia](julia-production.md). Gli script
attuali di verifica dei dati, preparazione del policy mix e consegna del
modello Vensim restano disponibili in `scripts/`.

## Dati e file locali

`precomputed/`, `provenance/` e sei `.vdfx` ricostruiti dai CSV v7 sono
installati da `data-v2.0.0`. Il vecchio `SURE.vpmx` è escluso dal nuovo
manifest. I dataset v1 e i relativi manifest restano immutabili.

`sure_julia/generated/` viene costruita da Docker. `dist/`, ambienti virtuali,
cache e risultati locali non sono versionati e non vengono eliminati da
questa pulizia. `.env`, chiavi e dati locali restano esclusi da Git;
anche `.DS_Store` e `.agents/` sono ignorati.

## Verifiche della pulizia

Controlli v7 del 16 ottobre 2026: 418 confronti Python–Julia superati,
14.571 simulazioni complete, pilot seriale/parallelo identico e audit finale
superato. Evidenze in `v7-data-audit-20261016.json`, `v7-validation-20261016.json`
e `v7-pilot-20261016.json` sotto `docs/validation/`.

Controlli storici della pulizia v6, 15 ottobre 2026:

- 81 test Python dell’app e dei componenti numerici superati.
- 20 controlli dell’API Julia dei 40 parametri superati.
- Suite Julia dei casi sintetici superata: fixture generali, indici, dati
  esterni, stati e ritardi, semantica numerica, allocazione.
- Rigenerazione di controllo della correzione FV superata: 1.543 componenti
  Python invariati e artefatti corretti identici.
- Tutti i 16 sorgenti numerici coincidono con i checksum di `data-v1.2.0`.
- Dataset verificato; catalogo dei 418 scenari di accettazione conservato,
  inclusi gli stessi dieci scenari di input originariamente nativi.

I workflow eseguono tutti i test Python rimasti; la build nativa verifica
anche l’API Julia, le simulazioni Python–Julia e l’avvio dell’app. Le prove
locali di questa pulizia sono in `dist/repository-cleanup-20261015/`, escluse
sia da Git sia dall’immagine Docker.
