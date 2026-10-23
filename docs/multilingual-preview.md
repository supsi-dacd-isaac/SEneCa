# Anteprima italiano / inglese

Base: **v0.4.2**, commit `94b7db1b81604566a2441af01aa0988692328b52`, dati **data-v2.0.0**.
Branch: `interfaccia-multilingue`. Nessuna modifica al modello, alla calibrazione, ai dati o alle equazioni di calcolo.

## Pagine e contenuti tradotti

- Menu lingua (icona globo) nella barra superiore a destra, comune a tutte le pagine; italiano predefinito. Il pulsante Deploy è nascosto tramite `client.toolbarMode = "viewer"`. Il menu mostra le lingue per esteso e può accogliere francese e tedesco quando saranno disponibili i relativi cataloghi.
- Navigazione, contesto iniziale, metodologia, PV e batterie, riscaldamento e risanamento, veicoli, elettricità, analisi esplorativa e simulazione live nelle due lingue.
- Tutte le quattro sottosezioni PV: adozione PV, batterie, produzione/consumi, prezzi/costi.
- Leve, aiuti, indicatori, spiegazioni, storico e calibrazione, legende, assi e comandi ECharts.
- Anche spiegazioni estese, priorità dei workshop, profili elettrici, selettori, graduatorie, pesi, messaggi di avanzamento live e tabelle di sintesi sono tradotti.
- Il PDF della documentazione, le immagini originali dei workshop/modello e i nomi tecnici nelle tabelle/esportazioni grezze conservano lingua e identificatori originali. Il CSV della graduatoria esplorativa segue invece la lingua della tabella di sintesi. I controlli interni di Streamlit non sono tradotti da questo catalogo.

## Struttura

`pv_batteries/i18n.py` usa l'API a oggetti di `gettext`, senza installare traduttori globali. La lingua è conservata nella sessione del singolo utente; la cache contiene solo cataloghi immutabili per lingua. Testi mancanti ricadono sull'italiano.

- `locales/en/LC_MESSAGES/seneca.po`: catalogo revisionabile, con l'italiano come `msgid` e l'inglese come `msgstr`.
- `locales/en/LC_MESSAGES/seneca.mo`: catalogo compilato distribuito con l'app.
- `scripts/compile_translations.py`: compilazione con Babel, già presente nell'ambiente bloccato della release.

Per cambiare una traduzione, modificare il `.po`, eseguire `python scripts/compile_translations.py` e riavviare il processo locale: i cataloghi vengono conservati in cache. Aggiungere i nuovi testi al catalogo, compresi quelli delle configurazioni passati dinamicamente al renderer. I messaggi con variabili usano campi nominati (`{year}`), tradotti prima della sostituzione. I simboli `%` delle unità sono letterali, non placeholder Python.

La traduzione avviene al momento della visualizzazione. Le opzioni dei selettori, le chiavi dei widget, le URL, i nomi delle variabili del modello e gli identificativi degli scenari restano stabili. Le opzioni ECharts vengono copiate e tradotte **dopo** la selezione delle serie e dei colori; numeri e dati originali non cambiano. Cambiare lingua non esegue nuove simulazioni.

## Verifiche

```sh
python scripts/compile_translations.py
python -m unittest discover -s tests -p 'test_i18n*.py' -v
python -m unittest discover -s tests -p 'test_chart*.py' -v
python -m unittest discover -s tests -p 'test_live*.py' -v
python -m unittest discover -s tests -p 'test_exploratory_ui.py' -v
```

I test integrati delle pagine richiedono i parquet della release fissata in `data-release.json`; il test PV segnala esplicitamente se mancano; i test delle altre pagine richiedono lo store completo. Nell'anteprima locale è stato eseguito con i dati reali verificati tramite checksum.

I controlli coprono isolamento fra utenti, ripiego per testi mancanti, purezza della traduzione dei grafici, passaggi IT→EN→IT, persistenza di leve/scenario/sezione, valori degli indicatori e dati numerici identici. Sono coperti tutti i passi della metodologia, le viste annuali/mensili/orarie, le classifiche esplorative e gli input live senza avviare il motore al cambio lingua. La verifica nel browser comprende navigazione, impaginazione e una simulazione live.

Streamlit non espone un punto di inserimento per widget nella propria barra. Il contenitore `language_toolbar` è perciò posizionato sulla barra, con altezza e allineamento centrati; un padding sulla classe semantica `.stAppToolbar` gli riserva una corsia, separata dall’indicatore Running, dal pulsante Stop e dal menu. Non si usano classi CSS generate né si nascondono i controlli di esecuzione. Popover e selezione delle lingue restano nativi. Ricontrollare allineamento e assenza di sovrapposizioni, anche durante una simulazione, dopo aggiornamenti di Streamlit.

## Avvio locale

Preparare l'ambiente e i dati secondo il README della release. Con gli artefatti Julia v7 disponibili, impostare `SURE_BACKEND=julia`, `SURE_VARIANT=v7` e, se necessario, `SURE_JULIA_BIN` e `JULIA_DEPOT_PATH` per la propria installazione. Non ereditare un `SURE_JULIA_MODEL` di un esperimento diverso.

```sh
python -m streamlit run server.py --server.address 127.0.0.1 --server.port 8504 --server.headless true
```

Il lifecycle attende il riscaldamento del motore Julia prima di dichiarare l'app pronta. La porta 8504 è distinta dall'anteprima sperimentale E22 sulla porta 8503.
