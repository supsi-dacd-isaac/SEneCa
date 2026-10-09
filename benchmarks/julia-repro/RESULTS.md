# Riproducibilità locale SURE Python–Julia — 9 ottobre 2026

**Il modello SURE v3 è riprodotto in Julia nei 43 scenari congelati.**
Sono superati il confronto completo, la conservazione dell'energia nei casi
SURE e le prove di ripetibilità. Sullo stesso scenario già compilato, Julia
impiega circa **4,9–5,0 secondi**, contro **42–44 secondi** di Python:
un'accelerazione di **8,52–8,80 volte** sulle mediane a caldo. Nei processi
nuovi Julia rimane più lenta; la verifica finale certifica anche i timer.

Branch `codex/julia-reproducibility`, dal commit
`086be42884d92cd945c0afae2f2985f01cf13495`. Webapp, modello originale,
dati e ambiente `.venv` sono rimasti invariati. Le modifiche sono nel runner,
nei suoi test e nelle patch applicate alle copie sperimentali.

## Riferimento e copertura

Il riferimento è il percorso attuale della webapp con SURE v3, costanti
calibrate, dati `data-v1.0.0` e PySD 3.14.3. L'ambiente separato riproduce
le 142 versioni Python registrate. Julia 1.10.12 usa il backend `ode`,
PySD `8991d119e139029d4dec712d257cf5fcc3549b8f` e
PySD.jl `abe4251fe91734f83776a9c782088d3a2f09dc57`, con manifest Julia.
Entrambi eseguono in Float64, con un thread, Euler non adattivo e passo
annuale, producendo tutti gli anni 2011–2050.

| Controllo | Esito |
|---|---|
| Scenari SURE | 43/43 superati |
| Webapp Python vs diagnostica Python | 52 output, errore massimo 0 in tutti i 43 scenari |
| Confronto Julia–Python | 102 variabili, incluse le 52 della webapp e i 14 componenti raggiungibili a sei dimensioni |
| Valori confrontati | 214.578.600, senza campionamento |
| Schema | Etichette, dimensioni, anni e valori discreti esatti; nessun non finito o output mancante |
| Ripetibilità, entrambi i motori | Due processi nuovi e sequenza base → high → base superati con confronto esatto |
| Conservazione SURE | 86/86 controlli Python/Julia superati con le soglie originali |
| Test unitari Python del runner | 56 superati |
| Test indipendenti della verifica temporale | 11 superati, separati dai 56 del runner |
| Provenienza Python | Tutti i 91 artefatti del riferimento validi; checksum delle sorgenti invariati |

I test mirati coprono EXCEPT da una a sei dimensioni, sottogruppi,
autoriferimenti, stock, broadcasting, somme, ritardi 0.01/0.1/1/2/4 anni,
allocazione, confini temporali, dati esterni e semantica matematica.
Sono verificati tutti i 70 lettori esterni SURE. Restano bloccanti i costrutti
non supportati e gli avvisi non riconducibili alle interpolazioni degli
stessi dati mancanti del riferimento.

## Tolleranze e scarti

L'utente ha autorizzato il 9 ottobre di allentare moderatamente le tolleranze
per evitare ulteriore lavoro su differenze trascurabili di arrotondamento.
La politica è versionata in `acceptance.json`; il riferimento e le soglie
originali in `pins.json` non sono stati modificati.

Per ogni serie elementare, con S massimo assoluto della serie Python:

- Accettazione: `1e-10 × max(1, S) + 1e-8 × |Python|`.
- Diagnostica originale: `1e-12 × max(1, S) + 1e-9 × |Python|`.

**42/43 scenari superano anche la soglia originale.** Solo `lever_00_00`,
con contributo cantonale PV al minimo, usa il criterio autorizzato:
50 valori di `Electricity dispatched`, `Electricity consumed` e
`Hourly exported electricity` eccedono la soglia originale. Lo scarto
massimo fra questi valori è `5.14335e-11`; il primo superamento osservato
è nel 2034. Il massimo rapporto errore/soglia di accettazione è 0.19476,
quindi nessun confronto si trova vicino al limite.

Il massimo errore assoluto nell'intera suite è `5.96046e-8` su
`Total annual demand Districts[Locarno]` nel 2038, a fronte di un valore
Python di circa 437 milioni: errore relativo `1.36391e-16`.
Gli errori assoluti di variabili con unità diverse non vanno confrontati
senza la scala della rispettiva serie.

La conservazione dell'energia SURE mantiene la soglia originale, oltre
ai limiti esatti di non negatività e di allocazione non superiore alla
richiesta troncata. Il residuo massimo rilevato è `7.38900e-11`.

## Dimensioni e correzioni necessarie

La simulazione completa mantiene le sei dimensioni originali e tutte le
5.280 celle. La rappresentazione equivalente usa Archetipo =
District × Performance × Type (120), HS (11), Configurazione =
PVpanel × Battery (4), con corrispondenza esplicita per etichette.

La ricostruzione sui dati reali è esatta su 127.142.400 valori.
L'audit indipendente `scripts/validate_sure_packing.py` completa anche
selezioni, esclusioni, tre somme parziali e transizioni HS/PV sui
14 componenti, tutti i 43 scenari e tutti gli anni: **592.103.120 confronti
bit per bit superati**. Le somme mantengono esplicitamente lo stesso
ordine aritmetico. Il rapporto registra i checksum di script, mapping,
manifest e snapshot. Questo è un audit della rappresentazione: non è
stata riscritta o cronometrata la dinamica completa a tre dimensioni.
Non viene giustificata alcuna aggregazione o riduzione degli stati.

La compatibilità richiede patch locali sostanziali:

- EXCEPT N-dimensionale, copertura e precedenza delle assegnazioni,
  sottogruppi, identità dei nomi e dipendenze degli autoriferimenti.
- Lettura degli input multidimensionali, coordinate e interpolazioni,
  senza sostituzioni automatiche di dati o costrutti con zero.
- Inizializzazione, SMOOTH annidato, memoria di DELAY FIXED e ordine degli
  aggiornamenti del riferimento; esportazione anche degli ausiliari.
- Allocazione compatibile con il solutore PySD/SciPy e con il troncamento
  delle richieste negative già presente nella webapp.
- 353 contratti di riduzione NumPy, sei con layout distinto tra 2011 e
  gli anni successivi, e otto normalizzazioni HS ottimizzate della webapp.
- Semantica di EXP/POWER e lookup NumPy: libreria matematica del riferimento,
  distinzione fra potenze scalari/array e FMA dove effettivamente usata.

I piccoli arrotondamenti a monte potevano essere amplificati dal solutore
di allocazione. Le patch già completate sono conservate; dopo la nuova
politica non sono state aggiunte correzioni per inseguire gli ultimi ULP.

## Limiti del riferimento e della certificazione

Il riferimento è congelato con `PYTHONHASHSEED=0`. L'app corrente usa un
ordine di aggiornamento derivato da un set; una prova separata con seed 2
ha cambiato 51 dei 52 output. La certificazione riguarda quindi questo
riferimento deterministico e non dimostra che la webapp attuale sia
indipendente dal seed. L'app non è stata modificata per correggerlo.

EXP/POWER sono verificati sulla piattaforma macOS arm64 locale, con
versione del sistema e della libreria matematica controllate all'avvio.
La certificazione non si estende automaticamente a Linux o ad altre build.

Le quattro leve `Provvedimento 1.2`, `1.3`, `1.4`, `1.7` sono già ignorate
dalla webapp v3. Il runner registra e conserva tale comportamento.

Lo stress sintetico dell'allocazione riproduce Python in tutti i 1.575 casi
entro le soglie originali, ma **non supera una certificazione fisica
generale della conservazione**: 551 casi violano la conservazione già
nell'oracolo Python (299 eccessi, 252 deficit). Nell'esempio con massimo
residuo assoluto, scala 1e8 e 129 fornitori con priorità circa 1e6 e
larghezza 0.0002, l'eccesso è 589.606.929,7, cioè 11,1111% della
disponibilità. Questi non sono piccoli arrotondamenti e non vengono
sanati allargando le tolleranze. Il confronto Julia–Python dello stress
ha errore massimo `2.98023e-8`, quindi è numericamente equivalente,
non bitwise. Le proprietà di conservazione dei 43 scenari SURE sono
controllate separatamente e passano tutte; il benchmark riguarda soltanto
configurazioni SURE validate.

## Prestazioni

Il benchmark finale è accettato sia numericamente sia temporalmente:
**48 misure** per base, mid e high con entrambi i motori,
tre processi nuovi e cinque ripetizioni a caldo.
Tutte le **54 esecuzioni**, inclusi i sei riscaldamenti esclusi dalle mediane,
hanno superato nuovamente il confronto numerico. L'artefatto è legato ai
checksum correnti dell'esperimento, alla validazione completa e all'audit
temporale `benchmark-clock-verified/awake-clock-final/audit.json`.

Il confronto principale a caldo misura `simulation_and_capture_seconds`:
ricostruzione dello stato iniziale, simulazione e cattura degli output della
webapp, senza caricamento o compressione NPZ. I valori sono mediane in secondi,
con intervallo minimo–massimo delle cinque ripetizioni. Il rapporto divide
la mediana Python per quella Julia.

| Scenario | Python, mediana [min–max] (s) | Julia, mediana [min–max] (s) | Rapporto Python/Julia |
|---|---:|---:|---:|
| base | 43,51 [38,54–49,43] | 4,94 [4,91–5,05] | 8,80× |
| mid | 42,49 [40,21–43,06] | 4,98 [4,87–5,09] | 8,52× |
| high | 42,72 [41,51–44,20] | 4,89 [4,85–5,23] | 8,74× |

Per i processi nuovi, `wall_seconds` comprende avvio, caricamento del modello
già tradotto, compilazione necessaria, simulazione, estrazione e snapshot
numerico compresso. Anche qui sono riportate mediana e minimo–massimo, su
tre esecuzioni; i pacchetti Julia dispongono già della cache di precompilazione.

| Scenario | Python, mediana [min–max] (s) | Julia, mediana [min–max] (s) |
|---|---:|---:|
| base | 42,82 [42,34–56,54] | 68,45 [67,93–74,52] |
| mid | 46,21 [45,36–46,64] | 66,79 [66,21–71,62] |
| high | 47,31 [47,16–67,76] | 66,72 [66,30–71,60] |

La prima raccolta aveva mostrato tempi interni Julia incompatibili con la
durata esterna del processo, incluso un mid a caldo di 687,97 secondi.
Su questo macOS, [CPython 3.11.8](https://github.com/python/cpython/blob/v3.11.8/Python/pytime.c#L1006-L1027)
misura con `mach_absolute_time`, che esclude la sospensione;
[libuv incluso in Julia](https://github.com/JuliaLang/libuv/blob/2723e256e952be0b015b3c0086f717c3d365d97e/src/unix/darwin.c#L52-L64)
usa `mach_continuous_time`, che la include.
Le misure originali sono conservate integralmente in
`debug/clock-audit/benchmark-original.json`, insieme ai rispettivi file grezzi.

La verifica indipendente ha ripetuto **tutte le 27 esecuzioni Julia**, senza
selezionare o eliminare singole ripetizioni anomale. `caffeinate` impedisce
la sospensione per inattività e i due orologi vengono controllati durante
processo, serializzazione e intervallo complessivo: **51 controlli superati**,
con limite superiore della sospensione al massimo di 3,001 microsecondi,
contro il limite ammesso di 10 millisecondi. Anche le somme delle fasi
sono compatibili con le durate esterne. Le 24 misure Python originali sono
conservate perché usano già l'orologio che esclude la sospensione; provenienza
e risultati di tutte le loro 27 esecuzioni sono stati verificati nuovamente,
con corrispondenza esatta al riferimento. Modelli e motori restano invariati.

La preparazione della sorgente Julia è separata: **6,54 s per base, 6,97 s
per mid e 6,60 s per high**. Questi tempi comprendono parsing, applicazione
dei parametri e generazione; escludono gli audit del riferimento e la copia
preliminare dei file. Non sono il tempo necessario a cambiare le leve in un
servizio persistente.

`REPORT.md` e `benchmark.json` nella directory del run riportano valori
singoli, mediane e intervalli delle fasi di caricamento, compilazione,
inizializzazione, integrazione, estrazione e serializzazione. La compilazione
Julia è già inclusa nei tempi di parete e non va sommata nuovamente. PySD
calcola ausiliari durante la cattura e ne riutilizza la cache in Euler:
i tempi delle singole fasi non hanno confini identici fra i due motori.

I massimi di memoria per gruppo scenario/modalità sono **314–358 MiB per
Python** e **1,53–1,71 GiB per Julia**. La memoria registrata è il massimo
cumulativo del processo, inclusi
riscaldamento e compilazioni precedenti. Il picco Python include la
serializzazione NPZ; quello Julia esclude la conversione NPZ eseguita
dall'orchestratore Python. Non si deduce da questi valori una riduzione
della memoria complessiva.

SHA-256 del benchmark finale:
`9297cef8217f8d8cf0f2aecf01b84055133fbc00346dab479a6b3353b6867f47`.
SHA-256 della validazione a cui è legato:
`67ff0b0bb23b1dcfffbeab99c0bd1f97104d10fa69110829abe88b76baac9c1f`.
SHA-256 dell'audit temporale:
`52a8e406e3c1e57ca790825c886df4efc0f3ed170a9644b403fb2c87ada615d8`.

## Passaggio a una webapp parametrica

Non è necessario ricompilare il modello per ogni valore delle leve. Un
servizio persistente può passare lo scenario come dati numerici di tipi e
dimensioni stabili, riutilizzare il codice compilato e ricostruire a ogni
richiesta condizioni iniziali e memoria dei ritardi. Cambiare equazioni,
tipi o dimensioni può invece richiedere nuova compilazione; eventuali
percorsi non ancora eseguiti vanno inclusi nel riscaldamento iniziale.

Il runner attuale incorpora i parametri nella copia generata e isola gli
scenari in moduli distinti. I valori diventano costanti del modulo:
`ODEProblem.p` oggi contiene buffer del runtime, quindi non basta passarvi
nuovi valori. Dall'analisi del codice, il passo necessario è un contenitore
che conservi questi buffer e aggiunga parametri `Float64` con tipi e
dimensioni stabili. Le funzioni di accesso e gli inizializzatori dovranno
leggere da quel contenitore, senza riscrivere le equazioni.
Questa API parametrica non è ancora implementata.
Le ripetizioni a caldo riutilizzano quindi lo
stesso scenario, non dimostrano ancora il costo di cambiare le leve in un
unico modello parametrico. Questo passaggio richiederà la stessa suite
numerica e la sequenza base → high → base sul medesimo modulo compilato.
Non sono state modificate le API o l'applicazione per implementarlo.

## Riproduzione

I comandi e le dipendenze sono in [README.md](README.md).
Gli artefatti voluminosi restano fuori da Git in
`dist/julia-repro/20261009-reproducibility/`: `REPORT.md`, `summary.json`,
`validation.json`, `benchmark.json`, snapshot, log e checksum.
L'inventario immutabile ha SHA-256
`cb4d58bd3db2c173379b232d540d182a700b7535bf36f906d51fe0c8f73b303f`.
