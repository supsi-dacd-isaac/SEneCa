# Verifica nativa della correzione PV della v6

Branch: `julia-production`. Revisione del modello: `sure-v6-pv-budget-1`.
**Release e deploy sospesi fino alla verifica del collega in Vensim.**

## Sorgente da aprire

Usare `Vensim/SURE_v6_pvbounded.mdl` con gli stessi file di input del sorgente
v6 originale. È una copia di `Vensim/SURE.mdl` con la sola correzione descritta
qui. Non usare il vecchio VPMX: pubblicare un nuovo VPMX dal sorgente corretto
e conservare hash, versione Vensim, impostazioni e log di compilazione.

`Vensim/SURE_pysd_v6_pvbounded.mdl` contiene la medesima correzione nella
versione con dati CSV predisposta per PySD. Python e Julia partono da questo
file. `sure_julia/pv-budget.json` registra equazioni, checksum, avvisi Python
classificati e verifica di conservazione delle equazioni non modificate.
Lo sketch originale è conservato; i nuovi ausiliari non sono disegnati.

## Equazioni e priorità

Le sei definizioni `Owners/Renters adopting PV/RCP/RCPv`, incluse tutte le
clausole specifiche per MFH e le esclusioni, diventano `Requested ...`.
Le definizioni con i nomi originali restituiscono:

```
MAX(0, Requested <flusso>) * PV availability factor
```

Per ogni District × HS × Performance × Type:

```
Available PV adoption = MAX(0,
    Heating Solution[...,PVno,Bno]/TIME STEP
    - MAX(0, Building demolition by archetype[...,PVno,Bno])
    - MAX(0, Buildings HS Renovation From[...,PVno,Bno]))
Total PV request = somma delle sei richieste non negative
PV availability factor = MIN(1, Available PV adoption / Total PV request)
```

Quando la richiesta totale è zero, il fattore vale 1; la divisione usa un
denominatore protetto anche per i motori che valutano entrambi i rami.
La priorità resta demolizioni/risanamenti, poi PV, poi sostituzioni del
riscaldamento per vecchiaia. Le entrate simultanee non finanziano ulteriori
adozioni nello stesso passo. Tutte le destinazioni, gli stock di proprietà
e i costi continuano a dipendere dai flussi accettati con i nomi originali.
Restano invariati allocatori, ritardi e le altre correzioni della v6.

## Prove richieste

1. Controllare sintassi, unità e assenza di cicli algebrici. Segnalare anche
   gli avvisi preesistenti separatamente da quelli introdotti. Non cambiare
   equazioni per far passare il test senza registrare il diff del sorgente.
2. Euler, TIME STEP=1, INITIAL TIME=2011, FINAL TIME=2050, SAVEPER=TIME STEP.
   Registrare i valori effettivi: non assumere che SETVAL sia stato accettato.
3. Applicare tutti i 40 parametri dello scenario e le 31 costanti calibrate
   di `constants_ref_v6.pkl`, incluse le coordinate degli array. Registrare
   anche ICE ban year=2050, Deflussi minimi LPAc=1 e Cambiamento climatico
   Hydro=1. I nomi PECC vanno risolti anche con le virgolette.
4. Prima base, high, regression_negative_stock e sample_min_12; poi tutti
   i 318 casi della suite. Ripetere base in un nuovo processo e la sequenza
   base → high → base. Gli input completi e gli export richiesti sono nel
   pacchetto di consegna generato dopo la validazione Python–Julia.
5. Esportare tutti gli anni e tutte le coordinate degli output applicativi,
   dei diagnostici e dei 15 ausiliari/flussì PV del pacchetto. Non limitarsi
   agli aggregati. Conservare valori grezzi Float32/Float64 e precisione del
   motore, senza arrotondare piccole popolazioni a zero.
6. Verificare non negatività, budget PV, bilanci dei trasferimenti e Euler.
   Caso noto: nella base v6 originale, a fine passo 2038 la categoria
   Mendrisio/ElectricHeater/VeryLow/DFH/PVno/Bno ha stock zero ma una richiesta
   di uscita PV di circa 1.2345669441641882e-6; il flusso accettato deve essere
   zero quando il budget è zero. La traiettoria corretta può già divergere
   dall'originale negli anni precedenti: verificare l'invariante su tutte le celle.
7. Confrontare Python–Julia e Vensim, riportando prima divergenza, errore
   massimo e propagazione. Separare gli scarti del dispacciamento/prezzo già
   noti dagli effetti della nuova correzione; non dichiarare equivalenza
   nativa sulla sola base di bilanci aggregati o della corrispondenza dei sorgenti.

Nessun motore Vensim è stato eseguito per preparare questa correzione.
