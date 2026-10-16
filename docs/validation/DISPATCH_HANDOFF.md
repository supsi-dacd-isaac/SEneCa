# Verifica Vensim del candidato v7

Usare il branch `v7-dispatch-validation`, **commit del modello
`55493428b37233463b6ff156f08b7e99a0b8519c`**, e il sorgente **`Vensim/SURE.mdl`**.
Conserva la calibrazione e i parametri PV della v7, corregge il dispatch e
riallinea `HPinput.csv` ai dati già esportati nella v7. PySD è già stato
rigenerato: non occorre riconvertirlo. Nessuna release prima di questi test e
della successiva conferma della calibrazione.

## 1. Preparazione

Su Windows, con Vensim e Python a 64 bit, nell'ambiente di `requirements.txt`
(PySD 3.14.3). La DLL attesa è `C:\Windows\System32\vendll64.dll`.
Dalla radice del repository:

```shell
git fetch origin
git switch --detach 55493428b37233463b6ff156f08b7e99a0b8519c
python -m unittest discover -s tests -p test_fer_cantonal.py
python -m unittest discover -s tests -p test_dispatch.py
python -m unittest discover -s tests -p test_v7_input_alignment.py
python scripts/check_dispatch.py --prepare
```

Tutti i comandi devono terminare con codice 0. Pubblicare **nuovi** pacchetti
con Vensim, senza riutilizzare vecchi `.vpmx`:

| Sorgente | Pacchetto da creare |
| --- | --- |
| `dist/dispatch-check-v7/dispatch_fixture.mdl` | `dist/dispatch-check-v7/dispatch_fixture.vpmx` |
| `Vensim/SURE.mdl` | `Vensim/SURE_dispatch_v7.vpmx` |

Nel pacchetto SURE includere i VDFX aggiornati della v7, **in particolare
`HPinput.vdfx` coerente con `HPinput.csv`**; il CSV non sostituisce il VDFX.
Mantenere le impostazioni originali del modello: Euler, passo annuale,
2011–2050. La fixture ha un proprio orizzonte: non modificarlo.

## 2. Test conclusivo

```shell
python scripts/check_dispatch.py --native-fixture dist/dispatch-check-v7/dispatch_fixture.vpmx --native-model Vensim/SURE_dispatch_v7.vpmx > dispatch-validation-v7.log 2>&1
```

Richiedere codice 0, `pass: true` in `native_fixture.json`, in entrambi i casi
`base` e `high` di `comparison.json`, e nel `manifest.json` finale. Quest'ultimo
deve indicare anche `native_fixture_tested: true` e `native_full_tested: true`.
Il comando verifica 189 casi sintetici/registrati e due simulazioni complete,
confrontando puntualmente 12 famiglie di variabili, inclusi dispatch orario,
importazioni, pompaggio e prezzi. Le soglie sono già nel codice: 2e-6 per
fixture/bilancio fisico; 0,1% più una piccola tolleranza assoluta per il confronto
completo. Non allargarle e non sostituire gli errori orari con medie annue.
Anni mancanti, NaN, leve rifiutate e simulazioni incomplete devono fallire.

## 3. Cosa restituire

Inviare `dispatch-validation-v7.log`, uno ZIP di **`dist/dispatch-check-v7/`**
(report, serie e output nativi), versione/precisione di Vensim e conferma che
i due pacchetti sono stati pubblicati dai sorgenti indicati con i dati v7.
In caso di errore, restituire l'errore esatto e fermarsi prima della calibrazione.
Se tutto passa, usare questo `Vensim/SURE.mdl` per verificare/aggiornare la
calibrazione e restituire modello, input eventualmente aggiornati, export
delle costanti e risultati del fit. La conversione PySD finale la gestiamo noi.
