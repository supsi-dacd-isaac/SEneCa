# SURE v8 EMS: traduzione Julia e verifica numerica

Valutazione del 4 novembre 2026, sul ramo sperimentale `ems-julia-validation`,
derivato da `ems-webapp` (`18405a21296479da61af0539ade09c8f761bb34e`).
Questo lavoro riguarda una istanza separata della webapp, non la release
ufficiale. La griglia degli incentivi EMS rimane **0%, 40%, 80%**.

## Stato

La traduzione compila e la pagina live esegue uno scenario EMS tramite Julia.
La verifica della revisione ricevuta ha rilevato scostamenti. È stata autorizzata
e applicata la correzione comune descritta sotto, come revisione `sure-v8-ems-2`.
**Passano tutti i 55 casi live e tutte le 871 simulazioni della griglia corretta.**
I controlli di accettazione conservano la
tolleranza preesistente; nessun fallimento viene convertito in successo.

Il modello ricevuto è `sure-v8-ems-1`, variante `ems1`. Il numero v8 identifica il modello,
non la versione della webapp. La documentazione storica v7 e il manifest della
release dati ufficiale non certificano questa variante. Per questo confronto
sono stati confrontati i cinque Parquet ricevuti in `seneca-ems-dati-20261102.zip`;
la pre-release usa i cinque nuovi Parquet rigenerati con la revisione corretta.

## Traduzione e controlli

- Julia 1.10.12, Python 3.11.8 e PySD 3.14.3; traduttore e dipendenze bloccati
  dalle revisioni già presenti nel runtime del progetto.
- 141 uscite con dimensioni e coordinate controllate; 42 parametri riutilizzabili.
- Stessi dati, calibrazioni, passo annuale 2011–2050 e ritardi sincroni.
- Aggiornati i riferimenti alle somme nelle due equazioni riorganizzate in v8.
- Riconosciute le espressioni MIN/MAX e le lookup scalari nelle potenze, inclusi
  i riferimenti a lookup definite successivamente nel file.
- Uniformati separatori dei percorsi e fine riga nella provenienza dei file.
  I dati ricevuti sono riconosciuti solo con hash esatto o differenze CRLF/LF.
- Gli input e le calibrazioni restano invariati. La sola modifica numerica al
  modello comune è il trattamento dello zero descritto sotto.

Il criterio, applicato a ogni cella con anni e coordinate corrispondenti, è:

```text
abs(Julia - Python) <= 1e-10 * max(1, max_time(abs(Python))) + 1e-8 * abs(Python)
```

Le categorie richiedono uguaglianza esatta. Si controllano inoltre valori finiti,
bilanci energetici, stock e trasferimenti, indicatori derivati e GMD.

Il programma `sure_julia.ems_store_validation` confronta le 871 simulazioni
distinte con le 1.197 configurazioni dei file ricevuti, comprese le due tabelle
GMD. Non rigenera né sovrascrive i Parquet. Il programma `sure_julia.validation`
copre 55 scenari live: base, regressione, estremi delle leve, 18 incroci fra
incentivi EMS, comunità energetiche e connessioni RCPv, e valori intermedi.

## Fragilità numerica individuata

La formula `PV removal fraction` distingue rigorosamente `PV buildings > 0`
da zero. Quando un archetipo si esaurisce, residui di arrotondamento possono
attivare il ramo positivo in un motore e il ramo zero nell'altro. Non serve una
differenza apprezzabile nello stock per ottenere una differenza nel rapporto.

Nel caso con tutte le leve al massimo, nel 2047 una cella contiene:

| Quantità | Python | Julia |
| --- | ---: | ---: |
| Edifici FV | 0 | 3,554 × 10⁻¹⁹ |
| Frazione di rimozione | 0 | 0,0198401693 |
| Perdite annuali di batteria installate, kWh/anno | 7.040,3769 | 7.040,3769 |

La differenza nel flusso si accumula nello stock delle perdite. Nel 2048 la
corrente FV immessa differisce di 0,000139682 GWh, circa 140 kWh su 942 GWh
(circa 0,000015%). Questo supera la tolleranza rigorosa e si propaga al dispaccio
e ad alcune variabili economiche. Nel caso intermedio la stessa dinamica appare
un anno prima, con i ruoli di Python e Julia invertiti.

Un confronto aggiuntivo fra Python locale e i Parquet ricevuti riproduce un
piccolo scostamento nella stessa variabile: la riproducibilità dipende anche
dagli arrotondamenti fra ambienti Python, non soltanto dalla traduzione Julia.

## Verifiche già completate

- Revisione 2: 55/55 scenari live, 345.224.000 celle confrontate, tutti entro
  la tolleranza invariata. Il massimo rapporto errore/tolleranza è 0,0000244.
- Griglia completa: 871/871 simulazioni distinte, 1.197 configurazioni nelle
  sezioni, 293.715.960 celle Python–Julia confrontate prima del salvataggio.
  Massimo rapporto errore/tolleranza: 0,0000231104. Rigenerazione con 32 worker.
- Caso base: tutte le 6.276.800 celle passano il confronto Python–Julia.
- Fixture mirate del traduttore: passate.
- API Julia: 22 controlli passati.
- Suite software: 129 test eseguiti, esito positivo, uno saltato perché non
  applicabile al ramo EMS.
- Pagina live: lo smoke di release usa un input EMS al 40%, confronta il risultato
  con il relativo scenario precalcolato e verifica il riuso del worker compilato.
- Curve di calibrazione riesportate: tutti i 141 output Python coincidono
  esattamente con il baseline verificato, confronto Julia superato. Rispetto al
  CSV del ramo di partenza la differenza massima è 1,82 × 10⁻¹², solo arrotondamento.
- Revisione 2 su ARM64 locale: smoke numerico base, massimo e regressione
  superato, incluse le verifiche GMD e di progressione del motore.
- Isolamento: base–massimo–base, processo nuovo, concorrenza e recupero dopo
  arresto del worker passano; i confronti ripetuti richiedono uguaglianza esatta.
  Certificato della suite live generato dopo il completamento di questi controlli.

Sulla revisione originale, 46/55 casi live e 609/871 simulazioni della griglia
ricevuta passano il criterio rigoroso. Il confronto dei cinque Parquet copre
4.400.865 celle; tutti i controlli fisici e GMD passano. Questa evidenza non viene
riutilizzata come certificato della revisione corretta.
Certificato live, audit dei dati, hash dei sorgenti e metadati del traduttore sono
inclusi in `provenance/build.json` nella release dati. I rapporti dettagliati sono
allegati alla pre-release applicativa. Non si rivendica equivalenza con Vensim nativo.

## Correzione autorizzata: revisione 2

Una copia diagnostica ha verificato `PV buildings > 1e-10` nei due test della
formula, con la stessa modifica in Python e Julia: base, caso massimo e caso
intermedio passano. Dopo autorizzazione, la modifica è stata applicata al modello
Vensim canonico, al Vensim preprocessato e a Python; Julia viene ritradotto da
queste equazioni. La correzione mantiene il comportamento del ramo zero per quantità
inferiori a un decimiliardesimo di edificio.

È una revisione numerica del modello comune, non una semplice correzione del
traduttore. `python -m sure_julia.python_batch <run> --verify-julia --workers N`
rigenera la griglia con Python e richiede il confronto rigoroso Julia di ogni
simulazione prima di salvare i dati. Gli originali e la griglia 0/40/80% vengono
conservati. `scripts/audit_ems_revision.py` verifica i risultati e misura gli
effetti rispetto ai Parquet ricevuti.

## Effetto sui dati ricevuti

La struttura, le chiavi, gli anni e la griglia dei cinque Parquet restano uguali.
Su 4.400.865 celle pubblicate, 1.311 superano la vecchia tolleranza rispetto ai
dati ricevuti, tutte nella sezione FV/batterie: 857 per l'immissione FV, 429 per
il prezzo dell'energia, 15 per il prelievo cantonale e 10 per il prezzo elettrico.
La differenza massima nell'immissione FV è 0,000587160 GWh (circa 587 kWh).
Le due tabelle GMD, risanamento e veicoli restano entro la vecchia tolleranza.
Questo confronto misura l'effetto della revisione e degli arrotondamenti
dell'ambiente originario; l'accettazione Python–Julia usa invece lo stesso
modello corretto in entrambi i motori.

## Pubblicazione separata

- Applicazione: pre-release `ems-v0.1.0`, ramo `ems-julia-validation`.
- Dati: pre-release `data-ems-v0.1.0`, con cinque Parquet e provenienza verificata.
- Immagine dedicata: `ghcr.io/supsi-dacd-isaac/seneca-ems:ems-v0.1.0`.
- Compose dedicato: `docker-compose.ems.yml`, porta esplicita obbligatoria.
- Il workflow esegue test e smoke numerico/UI su AMD64 e ARM64 prima di pubblicare
  l'immagine multiarch; non assegna il tag `latest` alla preview.

L'interfaccia multilingua del ramo di partenza è conservata. L'analisi di
incertezza non è esposta in questo ramo e non fa parte di questi dati.
Il numero v8 identifica il modello SURE, `sure-v8-ems-2` la sua revisione numerica,
mentre `ems-v0.1.0` identifica questa linea sperimentale della webapp.
