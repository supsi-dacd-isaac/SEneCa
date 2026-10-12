# Allineamento SURE v4: Python, Julia e Vensim

Sorgente main fissata a `17db1f4245c6bb0e8ef41a4cac5e8d3a6817cac6`. Tutte le elaborazioni sono isolate da webapp, modello v3 e ambiente corrente.

## Esito

**Julia–PySD v4: PASS** su 10 scenari, 110 variabili e 54,175,200 valori, senza campionamento. Sono inclusi i 52 output webapp, i 60 output nativi e i diagnostici multidimensionali già verificati nella v3.
**Equivalenza con Vensim: non dimostrata.** Gli stessi scarti nativi sono presenti con PySD v4 e con Julia. Alcuni sono consistenti e non giustificano un aumento delle tolleranze.

## Allineamento e ripetibilità

- Rigenerazione dal MDL v4; cinque accumulatori aggiuntivi per i nuovi diagnostici.
- Rimossa la sostituzione specifica delle normalizzazioni HS della v3; mantenute le equazioni v4.
- Portato il wrapper v4 ALLOCATE AVAILABLE: algoritmo per priorità quando tutti i profili rettangolari hanno la stessa larghezza, fallback precedente per larghezze diverse. Richieste negative troncate come in PySD v4.
- 104 casi mirati di allocazione, 314 verifiche: PASS; conservazione dell’energia: PASS.
- Julia 1.10.12, PySD Python 3.14.3, Float64, un thread, Euler fisso, passo annuale, tutti gli anni 2011–2050. Dipendenze Julia nel manifest preesistente.
- Soglia Python–Julia invariata: `1e-10 × max(1, S) + 1e-8 × abs(Python)`, con S massimo della singola serie temporale. Etichette, anni e valori discreti esatti.
- Il massimo scarto usa solo 0.00076025823 della tolleranza consentita.
- Identità dei 52 output fra percorso diagnostico e webapp, in tutti i dieci scenari: PASS.
- Identità bit per bit del base dopo gli altri scenari e in un secondo processo, per entrambi i motori: PASS.
- Un solo modulo e tipo dei parametri; zero nuova compilazione dopo il primo scenario: PASS. Ogni run ricrea stato iniziale e ritardi.
- Audit dei ritardi con strumentazione a risultati invariati e conferma della lettura dello SMOOTH già aggiornato per il ritardo delle importazioni: PASS.
- Tutti gli avvisi sono conservati e classificati; esclusione di costrutti ignorati o non supportati: PASS.

## Scarti Vensim

La tabella riporta il massimo errore assoluto diviso per il massimo assoluto della variabile Vensim nello scenario. Non è l’errore percentuale puntuale, né un criterio di accettazione. Le celle orarie non sono aggregate per determinare l’esito.

| Scenario | Python–Julia | PHS: errore / picco | Dispatch: errore / picco |
|---|---:|---:|---:|
| 01_base | PASS | 14.46% | 7.82% |
| 02_pv_max | PASS | 6.04% | 2.91% |
| 03_pv_min | PASS | 12.06% | 6.35% |
| 04_fit_005 | PASS | 13.82% | 7.42% |
| 05_heat_max | PASS | 14.67% | 8.08% |
| 06_heat_min | PASS | 15.26% | 11.73% |
| 07_vehicles_max | PASS | 14.53% | 7.55% |
| 08_vehicles_min | PASS | 14.45% | 7.95% |
| 09_hydro_on | PASS | 76.06% | 35.51% |
| 10_mixed | PASS | 71.94% | 25.44% |

Il confronto nativo considera esplicitamente la quantizzazione Float32 dell’export (mezzo ULP), oltre alla tolleranza numerica. Questa correzione non elimina gli scarti della tabella.

Già nel 2011, M5/H3, l’elettricità dispatchata dal fornitore Import vale 0.0142742572 in Vensim e 0.0196406214 in PySD. Nella stessa cella disponibilità dei fornitori e domanda di pompaggio sono quasi uguali. Mancano però la domanda oraria di rete e i profili di priorità nativi: non è ancora possibile attribuire univocamente lo scarto all’allocatore anziché ai suoi input.

## Archivio e limiti di provenienza

L’archivio contiene 8.480.480 valori nativi finiti. Per `Hourly exported electricity[Month,Hour,Import]` le 288 serie di ciascun run hanno solo il 2011. Il confronto grezzo le segnala incomplete. Un secondo confronto aggiunge separatamente 112.320 zeri complessivi secondo l’equazione MDL costante; questi zeri non sono misure native indipendenti. Nessun originale è modificato.
Tutti i 20 parametri della webapp sono registrati. Restano impliciti nel VPMX i default di ICE ban year, Deflussi minimi LPAc e Cambiamento climatico Hydro. Nella sorgente Python sono 2050, 1 e 1; non costituiscono prova del contenuto del VPMX.
Il VPMX usato per i run ha SHA-256 `bc18a741008dd2b299083d9c81a0f59acc2288d884991833dd3634354f52bf01` e non coincide con quello locale della release data-v1.0.0. I risultati si possono confrontare senza DLL; per riprodurre e diagnosticare il run nativo serve lo stesso VPMX e un ambiente Vensim compatibile.

## Diagnosi nativa successiva

Usare lo stesso VPMX dei nuovi run, registrare esplicitamente anche i tre default e le impostazioni del motore, ed esportare gli intermedi seguenti nello scenario base e in 09_hydro_on:

- Hourly electricity demand
- Hourly electricity grid demand
- Hourly demand and PHS
- Priority vector by supplier
- Marginal cost by supplier
- Hourly imported electricity
- PHS annual demand
- Seasonal PHS hourly demand
- Hour factor PHS consumption

I tempi raccolti durante questi controlli sono diagnostici: non costituiscono un nuovo benchmark controllato né una misura di latenza del servizio web.

Riproduzione: vedere `benchmarks/sure-v4/README.md`. Manifest, coordinate, parametri applicati, warning, risultati completi e checksum sono nella directory del run. `summary.json` è il riepilogo compatto; `validation.json` conserva tutti gli esiti per variabile.
