# Istruzioni per l'agente del collega

**Modello:** `Vensim/SURE.mdl` del commit
`11bdbcaf79339b34529c2a569af30578600cf795`, branch `dispatch-merit-order`.
Deriva dalla tua calibrazione `c8a7cd8`, corregge il dispatch e ripristina il FER
residenziale dal 2022. Non usare i file `*_pvbounded` o un vecchio `.vpmx`.
La nuova traduzione PySD è già inclusa; **non occorre riconvertirla**.

1. Parti da un checkout pulito del commit indicato, su Windows con Vensim e
   l'ambiente Python del progetto (`requirements.txt`, PySD **3.14.3**).
   Mantieni i tuoi input VDFX della calibrazione pubblicata in `c8a7cd8`.
   Dalla radice del repository, con l'ambiente attivo:

   ```powershell
   git fetch origin
   git switch --detach 11bdbcaf79339b34529c2a569af30578600cf795
   python -m unittest discover -s tests -p test_fer_cantonal.py
   python -m unittest discover -s tests -p test_dispatch.py
   python scripts/check_dispatch.py --prepare
   ```

2. In Vensim verifica la sintassi e pubblica due pacchetti **nuovi**:
   - `dist/dispatch-check/dispatch_fixture.mdl` → `dist/dispatch-check/dispatch_fixture.vpmx`;
   - `Vensim/SURE.mdl` → `Vensim/SURE_dispatch.vpmx`, includendo gli input necessari.
   Conserva passo annuale, Euler e intervallo 2011–2050 del modello completo.

3. Esegui:

   ```powershell
   python scripts/check_dispatch.py --native-fixture dist/dispatch-check/dispatch_fixture.vpmx --native-model Vensim/SURE_dispatch.vpmx > dispatch-validation.log 2>&1
   ```

**Esito richiesto:** exit code 0, `pass: true` in `native_fixture.json` e per
entrambi gli scenari in `comparison.json`. Il test verifica 179 vettori reali
+ 10 casi limite; poi base/high completi, con pompaggio stagionale spento/acceso
e ritardi sincroni. Controlla tutti i campioni, capacità, domanda servita e
bilancio (tolleranza 2e-6); confronta dispatch, PHS, prezzi, potenza PV e CO₂
con PySD allo 0,1% più il piccolo margine assoluto riportato nel JSON.
Anni/serie mancanti, NaN o leve rifiutate devono fallire. Non allargare le soglie.

**Restituisci:** `dispatch-validation.log`, uno ZIP di `dist/dispatch-check/`
(JSON, CSV e run native), versione/precisione di Vensim e conferma che i due
pacchetti provengano dai sorgenti indicati. In caso di errore restituisci anche
il messaggio completo e fermati prima della ricalibrazione.

Se tutto passa, usa questo `SURE.mdl` per ricontrollare/aggiornare la calibrazione,
in particolare PV dopo il ripristino del 2021 a un terzo della RU. Consegnaci
modello calibrato, input aggiornati ed export delle costanti con i risultati
di calibrazione. Alla conversione PySD finale e alla validazione per l'app
provvediamo noi. **Nessuna release in questa fase.**
