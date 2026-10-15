# File del repository e modello supportato

L’app usa **sure-v6-pv-budget-2**, con i dati **data-v1.2.0**. La pulizia
conserva questo contratto numerico e rimuove dal checkout le versioni
precedenti, i generatori superati e i risultati di debug non usati.
Tutto il materiale rimosso resta recuperabile nel
[tag v0.3.1](https://github.com/supsi-dacd-isaac/SEneCa/tree/v0.3.1).

## File da mantenere

| File o cartella | Motivo |
| --- | --- |
| `server.py`, `app.py`, `pages/`, `.streamlit/` | Avvio, navigazione e interfaccia dell’app. |
| `pv_batteries/` | Configurazioni, lettura degli store, indicatori, grafici e contenuti divulgativi. |
| `sure_backend.py`, `sure_live.py`, `sure_pysd.py`, `sure_paths.py`, `pysd_explore_config.py` | Selezione del motore, processo live, parametri e adattatore Python. |
| `sure_julia/` | Generazione Julia, motori, controlli fisici, validazione e batch del modello corretto. I file `allocation_v4.jl` e le funzioni con suffissi storici sono ancora parte del motore attuale. |
| `Vensim/SURE_pysd_v6_pvbounded.mdl`, `.py` e `SURE_v6_pvbounded.mdl` | Modello corretto, riferimento Python e copia nativa per Vensim. |
| `Vensim/SURE.mdl`, `SURE_pysd_v6.mdl`, `SURE_pysd_v6.py` | Sorgenti upstream necessari per applicare e verificare la correzione FV. Non sono alternative supportate da eseguire nell’app. |
| `Vensim/*_pysd_v6.csv`, `constants_ref_v6.pkl` | Input e costanti calibrate del modello supportato. |
| CSV nativi in `Vensim/` | Storici mostrati nell’app e sorgenti dei dati preparati per PySD. |
| `content/system_dynamics/` restante | Immagini, mappa, storici e priorità del workshop effettivamente letti dalle pagine. |
| `calibration_sim_adoptions_v3.csv` | Riferimento simulato storico ancora usato dal confronto di calibrazione; il suffisso descrive la provenienza, non il motore live. Gli osservati arrivano da `PVinput.csv`, `HPinput.csv` ed `EVinput.csv`. |
| `Input and Output Streamlit.xlsx` | Specifica delle leve e degli output, verificata dai test e registrata nella provenienza del batch. |
| `SEneCa_documentation.pdf` | Documento scaricabile dalla home. |
| `data-release.json`, `scripts/data_release.py` | Identità, download e verifica del dataset immutabile. |
| `model_checks/`, `tests/` | Casi sintetici e test del traduttore, del motore e dell’interfaccia attuali. |
| `docs/validation/` | Evidenze della correzione FV, del batch e dell’avvio. Non sono copie eseguibili di vecchi modelli. |
| Dockerfile, Compose, workflow, lock delle dipendenze, `deploy/` | Build, verifica e distribuzione riproducibili. |

I nomi e i checksum dei sorgenti v6 sono parte della provenienza in
`data-v1.2.0`. Spostarli o riscriverli richiede una migrazione esplicita del
contratto dati: non è una semplice pulizia di file inutilizzati.

## Materiale rimosso dal checkout

| Gruppo | Contenuto e sostituzione |
| --- | --- |
| Varianti v2–v5 | `SURE_pysd_v2` … `SURE_pysd_v5` in `.mdl` e `.py`, i relativi `*_pysd_vN.csv` e `constants_ref_vN.pkl`: 36 file. Nessun backend attuale li usa. |
| Rapporti rigenerabili | `coherence_report_v*.csv` e `constants_mismatch_v*.csv`: sei output di diagnosi, non input del modello. |
| CSV divulgativi superati | `Calibration_PV.csv`, `Calibration_HP.csv`, `calibration_sim_adoptions.csv`, `Annual adoption HP.csv`, `Annual adoption HT.csv`: nessun lettore attuale. |
| Selezioni e risultati Vensim storici | `Vensim/out and calibration files/` e `Vensim_test_runs/outputs.parquet`. I dieci scenari di input utili sono conservati in `model_checks/native_scenarios.json`. |
| Esperimenti Julia precedenti | `scripts/julia_repro/`, `scripts/julia_parametric/`, `scripts/sure_v4/`, `scripts/vensim_comparison/`, i relativi driver e test dei runner ritirati. I casi sintetici usati dalla validazione corrente sono trasferiti in `model_checks/`; i test dei componenti ancora supportati verificano direttamente `sure_julia/`. |
| Vecchi batch Vensim | `_run_precompute.py`, `pv_batteries/precompute_*.py`, `section_engine*.py`, `vensim_runner.py`. La rigenerazione supportata passa per `sure_julia.batch` e `scripts/prepare_policy_mix.sh`. |
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

`precomputed/`, `provenance/`, i `.vdfx` e `SURE.vpmx` sono installati dalla
release dati. Anche i binari nativi storici sono inclusi nel suo manifest:
rimuoverli dall’installazione farebbe fallire la verifica del dataset.
Per eliminarli dalla distribuzione serve una nuova release dati, distinta
dalla pulizia del codice.

`sure_julia/generated/` viene costruita da Docker. `dist/`, ambienti virtuali,
cache e risultati locali non sono versionati e non vengono eliminati da
questa pulizia. `.env`, chiavi e dati locali restano esclusi da Git;
anche `.DS_Store` e `.agents/` sono ignorati.

## Verifiche della pulizia

Controlli del 15 ottobre 2026:

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
