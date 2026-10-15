# Correzione FER cantonale FV — candidato da ricalibrare

15 ottobre 2026. Base del confronto: `3017fe41dc10107ee40a29908d07feb572f4de73`.

Questo ramo corregge i sorgenti nativi `Vensim/SURE.mdl` e
`Vensim/SURE_v6_pvbounded.mdl`. **Per la ricalibrazione destinata all’app usare
`SURE_v6_pvbounded.mdl`**, che conserva anche il limite condiviso delle adozioni
FV già verificato. `SURE.mdl` mantiene la struttura upstream, senza tale limite.

I modelli PySD/Julia, `constants_ref_v6.pkl`, i dataset e gli scenari dell’app
restano alla revisione precedente. Non sono stati rigenerati né rietichettati
come compatibili con questa correzione. Questo ramo non è pronto per una release.

## Verifica della regola e intervento

Il [RFER, art. 25 cpv. 1 e 3](https://m3.ti.ch/CAN/RLeggi/public/index.php/raccolta-leggi/legge/num/525)
conferma la segnalazione: fino al 31 marzo 2022 il contributo è 1/3 della RU-CH;
successivamente è il 50% della quota fino a 30 kW più 1/3 della quota eccedente,
con massimo CHF 250’000 per impianto. I bonus federali aggiuntivi sono esclusi.

Sono cambiate soltanto tre equazioni, con nomi e unità `CHF` invariati:

| Equazione | Modifica |
|---|---|
| `PV cantonal subsidy 30 - 100 kW check` | Data 2021 → 2022; percentuali invertite corrette; massimale nei rami storici |
| `PV cantonal subsidy > 100 kW check` | Stessa correzione |
| `PV cantonal subsidy[District,Type]` | Sola data 2021 → 2022, come autorizzato; nessuna modifica alle percentuali |

Le altre equazioni cantonali FV non contengono la stessa inversione.
`PV initial cantonal subsidy` appartiene al ramo dal 2026 e resta invariata.
Non sono cambiati gli incentivi federali, FiT, batterie, altri incentivi,
interfaccia, slider o scenari precalcolati.

Indicando con `R` la RU federale già calcolata dal modello e con `P` la potenza,
le due equazioni sopra 30 kW ora applicano:

```text
fino al 2021: min(250000, R / 3)
2022–2025:    min(250000, R / 2 * 30/P + R / 3 * (P - 30)/P)
dal 2026:    ramo precedente, invariato anche nel massimale
```

Il modello mantiene il passo annuale: attribuisce la regola nuova all’intero
2022, anticipandola anche alle entrate in esercizio del primo trimestre.
Non è stata introdotta una media 3/12–9/12, che richiederebbe un’ipotesi sulla
distribuzione delle installazioni durante l’anno.

## Approssimazione della ripartizione federale

La formula conserva la ripartizione proporzionale `R30 = R * 30/P` già presente.
**È un’approssimazione, non il calcolo esatto della RU riferita ai primi 30 kW.**
La RU può comprendere un contributo fisso e una componente legata alla potenza,
come descritto da [Pronovo](https://pronovo.ch/ufaqs/a-quanto-ammonta-la-rimunerazione-unica-per-il-mio-impianto-fotovoltaico/?Display_FAQ=10151).

Nel sorgente, le due RU non residenziali sono `B + r * P`, eventualmente limitate
dal successivo controllo al 30% del costo d’investimento. La ripartizione
proporzionale distribuisce quindi anche `B` tra le due quote. Se, a parità di
tariffa uniforme `r` e senza quel limite, si attribuisse tutto `B` ai primi 30 kW,
la differenza sul contributo cantonale sarebbe `B/6 * (1 - 30/P)`.
Per 60 kW e `B = 385`, vale CHF 32.08. Questo è un confronto algebrico esplicativo,
non una nuova ipotesi applicata al modello né una tariffa normativa ricostruita.

Inoltre le tariffe federali esistenti differiscono tra classi: nel 2022 il
residenziale usa `385 + 420*P`, mentre la classe 30–100 kW usa `385 + 330*P`.
Di conseguenza la continuità della **formula cantonale a RU identica** è verificata,
ma il modello federale attuale non è continuo passando tra queste classi:
a 30 kW fornisce rispettivamente RU CHF 12’985 e CHF 10’285, che diventano
contributi cantonali CHF 6’492.50 e CHF 5’142.50. Correggere tale differenza
richiederebbe intervenire sul contributo federale, escluso da questa modifica.

Non risultano componenti per bonus federali aggiuntivi nelle equazioni che
alimentano questi contributi storici. Nessun bonus è stato aggiunto o sottratto.

## Controlli numerici

I test traducono con PySD 3.14.3 le equazioni estratte dai due sorgenti Vensim e
le valutano con ingressi controllati; il residenziale è ridotto a una cella.
Non vengono eseguiti scenari SURE. Un primo controllo assume una RU sintetica
di CHF 300/kW, per separare il calcolo cantonale dalle tariffe federali:

| kW | RU di prova | 2021 prima → dopo | 2022 prima → dopo |
|---:|---:|---:|---:|
| 20 | 6’000 | 3’000 → 2’000 | 3’000 → 3’000 |
| 30 | 9’000 | 4’500 → 3’000 | 4’500 → 4’500 |
| 60 | 18’000 | 7’500 → 6’000 | 7’500 → 7’500 |
| 100 | 30’000 | 13’500 → 10’000 | 13’500 → 11’500 |

20 e 30 kW usano il ramo residenziale; entrambe le formule sopra 30 kW sono
anche provate separatamente a 30, 60, 100 e 300 kW come controlli algebrici.
A 60 kW le due quote di potenza sono uguali: il solo scambio delle percentuali
non cambia il totale, motivo per cui sono essenziali anche gli altri casi.

Usando invece i contributi fissi e le tariffe presenti nel modello, con limite
federale sul costo non vincolante nell’esempio, il confronto è:

| kW | 2021 prima → dopo (CHF) | 2022 prima → dopo (CHF) |
|---:|---:|---:|
| 20 | 4’585.00 → 3’056.67 | 4’392.50 → 4’392.50 |
| 30 | 6’685.00 → 4’456.67 | 6’492.50 → 6’492.50 |
| 52, media classe 30–100 | 7’030.96 → 5’803.33 | 7’085.48 → 7’535.35 |
| 60 | 8’320.83 → 6’656.67 | 8’410.42 → 8’410.42 |
| 100 | 14’746.50 → 10’923.33 | 15’023.25 → 12’797.58 |
| 300, media classe >100 | 42’388.33 → 29’233.33 | 39’319.17 → 28’472.50 |

Esito: **6 test superati**. Verificati anche i limiti temporali, la continuità
algebrica a 30 kW, RU nulla, saturazione a CHF 250’000 e i due percorsi ordinario
ed esplorativo dal 2026, inclusi importi oltre il massimale storico.
Il confronto con le equazioni precedenti conferma **507 valutazioni invariate**
nei rami non interessati (anni 2011–2020 e dal 2026, a ingressi uguali e sotto
il massimale per il periodo storico).

```sh
python -m unittest discover -s tests -p test_fer_cantonal.py -v
```

L’[audit numerico](fer-cantonal-checks-20261015.json) registra hash e confronti.
Escludendo i tre blocchi modificati, entrambi i file sono identici byte per byte
alla base, inclusi passo temporale, federale, altri incentivi e disegni Vensim.
Anche i rami dal 2026 sono identici byte per byte. Entrambi i sorgenti completi
passano il parser Vensim di PySD; il sorgente bounded corrisponde esattamente
all’applicazione della correzione condivisa delle adozioni al nuovo `SURE.mdl`.
L’esecuzione nel motore nativo Vensim è ancora da verificare con il collega.

## Passaggio al collega e blocco release

Ricalibrare `Vensim/SURE_v6_pvbounded.mdl` su questo ramo, riportando il commit
usato e restituendo modello e parametri aggiornati. I CSV e le calibrazioni
precedenti sono conservati come input di partenza, non come nuova calibrazione.

Solo dopo il rientro della calibrazione: allineare i derivati PySD/Julia,
assegnare la nuova revisione, ripetere le verifiche numeriche e fisiche,
rigenerare le simulazioni e i dataset, quindi preparare la release.
I manifest della revisione precedente non devono essere aggiornati per far
passare artificialmente i controlli: con questi sorgenti nativi modificati,
la vecchia certificazione di identità del modello non è più valida.

Nessuna release, pubblicazione di immagine o distribuzione viene eseguita
prima della nuova calibrazione.
