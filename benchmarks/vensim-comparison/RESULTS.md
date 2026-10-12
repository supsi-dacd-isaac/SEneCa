# SURE: confronto con gli archivi nativi Vensim — 12 ottobre 2026

**Julia riproduce Python anche nei casi con le maggiori divergenze da Vensim.
L'equivalenza con Vensim, invece, non è dimostrata: alcuni scarti sono
sostanziali e non sono risolvibili accettando soltanto piccoli arrotondamenti.**

Il confronto usa il modulo Julia parametrico già certificato, SURE v3,
costanti calibrate e release dati `data-v1.0.0`. Non modifica webapp, modello,
dati o motori. I risultati nativi provengono dai Parquet storici generati
dal modello pubblicato `SURE.vpmx`; non sono nuove esecuzioni di Vensim.
I limiti di provenienza degli scenari sono descritti sotto.

## Copertura effettiva

| Sezione | Scenari presenti e inventariati | Scenari confrontati | Variabili | Valori confrontati |
|---|---:|---:|---:|---:|
| PV e batterie | 324 | 21 | 25 | 80.640 |
| Risanamento | 1.215 | 25 | 15 | 19.000 |
| Veicoli | 144 | 22 | 5 | 21.120 |
| Elettricità | 144 | 18 | 5 | 7.672.320 |
| Totale | 1.827 | **86** | **50 distinte** | **7.793.080** |

Sono confrontati tutti gli anni 2011–2050 e tutte le coordinate degli
output di ciascuna sezione selezionata, senza campionare celle. La scelta
include base/low/mid/high, tutti i valori delle singole leve e otto
combinazioni casuali per sezione, eliminando i duplicati. Il seme è
`20261012`; parametri completi e alias sono salvati nell'inventario.
Non è stata simulata l'intera griglia di 1.827 scenari.

Il riuso dei parametri comuni richiede 82 esecuzioni Julia per 90 confronti:
86 casi principali e quattro controprove sui default dei casi base. Tutte
usano lo stesso modulo in un processo; dopo il primo scenario il contatore
JIT registra zero nuova compilazione. I 15 scenari già eseguiti nel pilot
sono riprodotti **esattamente**, con tutte le 50 variabili, nel nuovo processo
e nella diversa sequenza di richieste. Questi tempi non sono un benchmark.

L'audit completo trova 62.066.952 valori nativi effettivamente memorizzati,
tutti finiti e rappresentabili esattamente in Float32. Nello store elettrico
mancano 1.617.408 celle: le 288 serie di export del fornitore Import hanno
solo lo zero del 2011. Il sorgente MDL definisce quelle serie costanti a zero.
I confronti elettrici grezzi rimangono incompleti; una ricostruzione distinta
e documentata aggiunge **202.176 celle** nei 18 scenari selezionati. Queste
sono incluse nei 7.793.080 valori della tabella, non dichiarate osservazioni
Vensim. Anche con questa ricostruzione il confronto numerico non passa.

Mancano negli archivi delle sezioni due output dell'app: `Power by Type` e
`Annual CO2 emissions`. Non viene dichiarata una verifica Vensim dei 52
output completi o degli stati interni a sei dimensioni.

## Entità delle differenze

La soglia vicina all'errore numerico concordata viene mantenuta, aggiungendo
soltanto la metà ULP dell'esportazione Float32. **0/86 scenari** la superano
su tutte le proprie celle: 3.383.962 valori eccedono la soglia. Questo
conteggio include scarti piccolissimi e non ne misura l'importanza pratica.
Passano 21 dei 1.100 confronti variabile/scenario: `TSO charge` in tutti i
casi PV. La [metodologia](README.md) distingue tolleranze, scale e dati mancanti.

| Sezione | Massimo scarto assoluto, diviso per il picco della rispettiva variabile | Variabile e caso |
|---|---:|---|
| PV e batterie | 2,4033% | `Energy price`, `pv_batteries_019` |
| Risanamento | 0,5590% | `Annual incentives Heating Technologies`, `risanamento_018` |
| Veicoli | 0,1788% | `Adoption Vehicles`, `veicoli_011` |
| Elettricità | **87,7012%** | `PHS hourly demand`, `elettricita_012` |

Queste percentuali usano il picco dell'intera variabile nel rispettivo
scenario, non il valore della cella. I CSV registrano anche errori assoluti,
relativi, prime divergenze e totali annuali per singolo fornitore.

Due esempi nello scenario elettrico `elettricita_012` mostrano perché non
si può dichiarare la coerenza guardando soltanto i totali più grandi:

- Domanda di pompaggio a febbraio, ora H14, anno 2049: **0,032239735 GWh
  Vensim contro 0,327254843 GWh Julia/Python**, differenza 0,295015108 GWh.
- Importazioni annue nel 2050: **17,672769 GWh Vensim contro 2,808755 GWh
  Julia/Python**, circa −84,1%. Nello stesso scenario la domanda annuale di
  pompaggio è invece quasi identica: 663,294496 contro 663,295000 GWh.

I parametri elettrici di questo caso sono FiT=0,10, contributo federale
PV=0,20, provvedimenti 1.2/1.3/1.7 attivi e 1.4 disattivo. Gli altri
parametri seguono l'ipotesi dei default MDL, esplicitata sotto.

Anche lo scenario base mostra una differenza oraria nel pompaggio:
M2/H14 del 2031, 0,130110547 contro 0,104034187 GWh, circa −20,04%.
Il massimo scarto annuale della stessa variabile è soltanto 0,000498 GWh.
Nel base PV il prezzo dell'energia a Mendrisio nel 2036 è 0,062639803
contro 0,065928484 CHF/kWh, circa +5,25% rispetto alla cella Vensim.

## Confronto a tre e diagnosi

Il riferimento Python è stato eseguito nuovamente sui tre vettori di
parametri distinti dei quattro casi base e sui due casi elettrici critici
`elettricita_002` e `elettricita_012`. **5/5 confronti Python–Julia passano
su tutte le 50 variabili e tutti gli anni.** Il massimo rapporto fra errore
e tolleranza autorizzata è 0,11248, nel caso elettrico peggiore. Questo
conferma che gli scarti Vensim di questi casi sono già presenti nel
riferimento Python e non sono introdotti dalla traduzione Julia.
Non è stata rieseguita Python per tutti gli 86 scenari nuovi.

Le prime differenze oltre la quantizzazione compaiono già nel 2011, per
esempio 1,20e−5 su `Specific final consumption` (circa 92,67) e 3,25e−8
su `Electricity dispatched[M1,H1,RoR]` (circa 0,05795). Queste differenze
iniziali sono molto piccole. Non dimostrano da sole la causa degli scarti
più grandi negli anni successivi.

È stata localizzata una parte della propagazione nel pompaggio base:
l'equazione normalizza l'inverso dell'offerta PHS oraria, con limite
inferiore 0,001681. Applicata alle rispettive offerte archiviate, ricostruisce
il profilo della domanda con residuo massimo 1,29e−8 GWh per Vensim e
4,16e−17 per Julia. Nel punto M2/H14 del 2031 le offerte sono 0,002318010
e 0,002903410 GWh: il profilo della domanda cambia di conseguenza, pur
conservando quasi lo stesso totale. La verifica usa il totale osservato
solo per isolare l'identità del profilo, senza ricalibrare il modello.

Resta da risalire all'origine della diversa offerta: dati/calibrazioni,
configurazione del modello pubblicato, semantica degli aggiornamenti dei
ritardi o altre differenze del motore. Gli archivi non esportano tutti
gli ausiliari necessari a separare queste cause. Non viene attribuito
automaticamente il problema al solo `ALLOCATE AVAILABLE`.

## I quattro provvedimenti funzionano anche in Vensim

Le prove a leva singola confermano effetti in entrambi i motori dal 2027,
con lo stesso primo anno per ciascuna delle cinque variabili elettriche
confrontate. Per il pompaggio, i provvedimenti 1.4 e 1.7 iniziano dal 2028.
Alcuni effetti annui diretti nel 2050 sono molto vicini:

| Provvedimento | Effetto rispetto al base | Vensim | Julia |
|---|---|---:|---:|
| 1.2 | Offerta Hydro | +213,999994 GWh | +213,999990 GWh |
| 1.3 | Offerta PHS | +344,000000 GWh | +344,000019 GWh |
| 1.3 | Domanda di pompaggio | +429,999993 GWh | +430,000000 GWh |
| 1.4 | Offerta RoR | +79,999983 GWh | +79,999982 GWh |

Il provvedimento 1.7 modifica la distribuzione oraria; nel confronto la
variazione del totale annuo Hydro è circa zero. Questi riscontri confermano
l'attivazione dei controlli e alcuni effetti diretti. Non certificano tutte
le conseguenze indirette, dove restano le differenze già descritte.

## Provenienza e passo successivo

Gli archivi memorizzano soltanto i parametri della propria sezione. I
default delle altre leve nel `.vpmx` non sono registrati. Il confronto
principale usa i letterali del sorgente come ipotesi, mentre le controprove
usano il base UI. I quattro default differenti sono:

| Parametro | Sorgente MDL | Base UI |
|---|---:|---:|
| Retrofit incentive input | 60 | 50 |
| EV charger incentive input | 500 | 2.000 |
| CO2 coefficient ICE | 2,5 | 2 |
| ICE fuel price input | 1,81 | 2 |

La controprova UI non elimina gli scarti. Non si sceglie il profilo con il
miglior adattamento per dedurre i parametri Vensim. Il checksum del VPMX
e della release identifica i file locali, ma non sostituisce il manifest
dell'esecuzione storica. L'export Float32 non rivela la precisione interna
della DLL; la relativa documentazione è citata nella metodologia.

**Il prossimo riferimento utile è una nuova esportazione Vensim con tutti
i 20 parametri impostati e registrati**, versione della DLL, equazioni,
costanti complete, dati, passo, metodo di integrazione e output di tutte
le 52 variabili. Per la diagnosi elettrica servono anche `PHS hourly supply`,
`PHS hourly increase/decrease`, `Share grid demand per hour`, `PV hourly
difference`, `Hourly imported electricity`, `Hourly electricity grid demand`,
`Hour factor PHS consumption` e i componenti stagionali PHS.
Partire da base e dai due casi critici sopra identifica il problema prima
di estendere nuovamente la griglia. L'attuale macchina macOS non esegue
la DLL Windows usata dal progetto.

Non sono state cambiate le tolleranze per ottenere un esito positivo.
Gli scarti maggiori richiedono questo riallineamento e una diagnosi del
riferimento nativo prima di dichiarare equivalenza con Vensim.

## Artefatti e controlli

- Branch: `julia-reproducibility`; commit dell'implementazione precedente:
  `0cd60e9`. Riferimento Python originario: `086be42884d92cd945c0afae2f2985f01cf13495`.
- Modulo Julia congelato: SHA-256
  `a80f302afd90c5faf1bb6f9dccc94499e00d57804ee68d46470f3c4c5d15fb87`.
- Esecuzioni: `dist/vensim-comparison/20261012-pilot` e
  `dist/vensim-comparison/20261012-targeted`.
- `analysis/summary.json`, `variables.csv` e `annual-by-supplier.csv`
  contengono la diagnostica completa; `triangulation.json` nel pilot e
  `triangulation-python-extremes.json` nella suite estesa conservano il
  confronto a tre. [evidence.json](evidence.json) raccoglie gli esiti sintetici
  e i checksum rilevanti senza versionare gli array.
- **11 test superati**: quantizzazione, soglia dell'1% solo diagnostica,
  dati mancanti/non finiti, forme, ordine delle coordinate, duplicati,
  ricostruzione limitata alla costante documentata, aggregati che non
  nascondono gli errori, fattore annuale, fornitori separati e alias della griglia.
- I checksum del modello, dati, patch e implementazioni numeriche precedenti
  sono verificati prima e dopo la simulazione; gli avvisi nuovi sono bloccanti.
  Nessun avviso nuovo è stato rilevato. Il codice delle analisi viene
  registrato separatamente dal codice che ha generato le simulazioni.

Le istruzioni per riprodurre la prova sono in [README.md](README.md).
