# Prova nativa necessaria per chiudere l'allineamento

Non è stata eseguita in questa sessione: manca un runtime Vensim DSS nativo
utilizzabile sul Mac. Non serve ricompilare SURE per la prima prova statica.

## 1. Generare i due modelli sperimentali

```sh
dist/julia-repro/runtime/python-reference/bin/python -B -m scripts.sure_v4.allocation_probe prepare \
  --directory dist/sure-alignment/native-probe \
  --source dist/sure-v4/20261012-alignment/source/Vensim/SURE.mdl
dist/julia-repro/runtime/python-reference/bin/python -B -m scripts.sure_v4.allocation_probe check-python \
  --directory dist/sure-alignment/native-probe \
  --source dist/sure-v4/20261012-alignment/source/Vensim/SURE_pysd_v4.py
```

Sono generati `allocation_probe.mdl`, `cases.json`, un manifest con checksum,
`SURE_priority_candidate.mdl` e la sua piccola patch revisionabile.
Il modello statico non dipende da file Excel/CSV esterni. I suoi ingressi sono
sintetici, dichiarati e costanti: non vanno presentati come osservazioni native
del modello SURE. Il controllo Python registra tutti gli avvisi; i soli avvisi
ammessi riguardano il profilo PP misto costante/ausiliario (poi escluso dalla
prova Python) e la selezione esplicita del sottomodello.

## 2. Eseguire il modello statico in Vensim

Aprire `allocation_probe.mdl` in Vensim DSS e verificarne la sintassi nativa.
Pubblicarlo come `allocation_probe.vpmx`, senza cambiarne le equazioni.
Da Windows, nella radice di questo repository, con Python a 64 bit e NumPy:

```powershell
python -m scripts.sure_v4.allocation_probe export-native `
  --directory dist/sure-alignment/native-probe `
  --published C:/percorso/allocation_probe.vpmx `
  --dll C:/Windows/System32/vendll64.dll `
  --out dist/sure-alignment/native-probe-result
```

La cartella di destinazione deve essere nuova. Conservare anche versione di
Vensim DSS e impostazioni usate nella pubblicazione. Il comando registra hash
di DLL, VPMX e casi, tutti i valori grezzi restituiti dalla DLL e un confronto
separato per funzione. Dato che il modello è statico, una costante salvata solo
all'istante zero è lecita ed è conservata come tale. Dati assenti, non finiti,
coordinate estranee o casi diversi causano errore.

Rieseguire l'analisi senza la DLL, se necessario:

```sh
python -m scripts.sure_v4.allocation_probe compare-native \
  --directory dist/sure-alignment/native-probe \
  --out dist/sure-alignment/native-probe-result
```

`comparison.json` confronta tutte le 450 celle per funzione. Aggiunge alla
tolleranza numerica solo mezzo ULP della serializzazione Float32, e riporta
separatamente l'errore sul bilancio. Non arrotonda residui a 0.01.
Le priorità traslate permettono di verificare separatamente l'effetto del loro
segno: la documentazione di ALLOCATE AVAILABLE indica priorità positive mentre
SURE usa l'opposto dei costi marginali. Localmente la traslazione mantiene
l'allocazione entro il solo arrotondamento numerico.

Se BY PRIORITY supera il test e AVAILABLE no, abbiamo una giustificazione
sperimentale per provare la sostituzione nel modello completo. Se entrambi
falliscono, non adottare la modifica: occorre esaminare il risultato nativo o
usare una formulazione esplicita condivisa dai motori.

## 3. Solo dopo: prova sul modello SURE completo

`SURE_priority_candidate.mdl` sostituisce l'allocazione con BY PRIORITY e
`MAX(0, richiesta)`. Richiede gli stessi file esterni del sorgente originale,
il profilo rettangolare di tipo 1 e la larghezza comune 0.1. Il generatore
rifiuta altri profili. Il nuovo modello deve essere pubblicato separatamente;
non sostituire il VPMX dei dieci run di riferimento.

Eseguire originale e candidato con gli stessi venti parametri registrati in
`Vensim_test_runs/inputs.json`, passo annuale, stesso metodo d'integrazione e
stessi dati/calibrazione. Registrare anche i valori effettivi di `ICE ban year`,
`Deflussi minimi LPAc` e `Cambiamento climatico Hydro`, la versione del motore,
gli hash di sorgente, VPMX e dati. Conservare gli output originali.

Aggiungere ai 60 output già esportati:

- `Hourly demand and PHS`, `Priority vector by supplier`, `Marginal cost by supplier`;
- `Hourly imported electricity`, `PHS hourly supply`, `Hour factor PHS consumption`;
- `Seasonal PHS monthly demand`, `Seasonal PHS monthly production`;
- `Seasonal PHS hourly demand`, `Seasonal PHS hourly production`.

Questi ingressi consentono il replay dell'allocatore sulle stesse quantità
native e la diagnosi della prima divergenza nel circuito di pompaggio.
Prima confrontare il base; poi tutti i dieci scenari, ogni cella e ogni anno.
Il nuovo sorgente rimane candidato finché questi confronti non passano.
