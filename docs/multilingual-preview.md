# Anteprima multilingue: italiano, inglese, francese e tedesco

Base: **v0.4.2**, commit `94b7db1b81604566a2441af01aa0988692328b52`, dati **data-v2.0.0**.
Branch: `interfaccia-multilingue`. Nessuna modifica al modello, alla calibrazione, ai dati o alle equazioni di calcolo.

## Pagine e contenuti tradotti

- Menu lingua (icona globo) nella barra superiore a destra, comune a tutte le pagine; italiano predefinito. Il pulsante Deploy è nascosto tramite `client.toolbarMode = "viewer"`. Il menu mostra Italiano, English, Français e Deutsch per esteso.
- Navigazione, contesto iniziale, metodologia, PV e batterie, riscaldamento e risanamento, veicoli, elettricità, analisi esplorativa e simulazione live nelle quattro lingue.
- Tutte le quattro sottosezioni PV: adozione PV, batterie, produzione/consumi, prezzi/costi.
- Leve, aiuti, indicatori, spiegazioni, storico e calibrazione, legende, assi e comandi ECharts.
- Anche spiegazioni estese, priorità dei workshop, profili elettrici, selettori, graduatorie, pesi, messaggi di avanzamento live e tabelle di sintesi sono tradotti.
- Il PDF della documentazione, le immagini originali dei workshop/modello e i nomi tecnici nelle tabelle/esportazioni grezze conservano lingua e identificatori originali. Il CSV della graduatoria esplorativa segue invece la lingua della tabella di sintesi. I controlli interni di Streamlit non sono tradotti da questo catalogo.

## Struttura

`pv_batteries/i18n.py` usa l'API a oggetti di `gettext`, senza installare traduttori globali. La lingua è conservata nella sessione del singolo utente; la cache contiene solo cataloghi immutabili per lingua. Testi mancanti ricadono sull'italiano.

- `locales/{en,fr,de}/LC_MESSAGES/seneca.po`: cataloghi revisionabili, con l’italiano come `msgid` e la lingua di destinazione come `msgstr`.
- `locales/{en,fr,de}/LC_MESSAGES/seneca.mo`: cataloghi compilati distribuiti con l’app.
- `scripts/compile_translations.py`: compilazione con Babel, già presente nell'ambiente bloccato della release.

Per cambiare una traduzione, modificare il `.po`, eseguire `python scripts/compile_translations.py` e riavviare il processo locale: i cataloghi vengono conservati in cache. Aggiungere i nuovi testi al catalogo, compresi quelli delle configurazioni passati dinamicamente al renderer. I messaggi con variabili usano campi nominati (`{year}`), tradotti prima della sostituzione. I simboli `%` delle unità sono letterali, non placeholder Python.

La traduzione avviene al momento della visualizzazione. Le opzioni dei selettori, le chiavi dei widget, le URL, i nomi delle variabili del modello e gli identificativi degli scenari restano stabili. Le opzioni ECharts vengono copiate e tradotte **dopo** la selezione delle serie e dei colori; numeri e dati originali non cambiano. Cambiare lingua non esegue nuove simulazioni. Il callback del selettore reinvia esplicitamente le scelte canoniche al browser quando cambiano le etichette, evitando che radio e selectbox perdano la selezione al clic successivo.

## Verifiche

```sh
python scripts/compile_translations.py
python -m unittest discover -s tests -p 'test_i18n*.py' -v
python -m unittest discover -s tests -p 'test_four_languages.py' -v
python -m unittest discover -s tests -p 'test_relative_views.py' -v
python -m unittest discover -s tests -p 'test_chart*.py' -v
python -m unittest discover -s tests -p 'test_live*.py' -v
python -m unittest discover -s tests -p 'test_exploratory_ui.py' -v
```

I test integrati delle pagine richiedono i parquet della release fissata in `data-release.json`; il test PV segnala esplicitamente se mancano; i test delle altre pagine richiedono lo store completo. Nell'anteprima locale è stato eseguito con i dati reali verificati tramite checksum.

I controlli coprono isolamento fra utenti, ripiego per testi mancanti, purezza della traduzione dei grafici, passaggi IT→EN→IT, persistenza di leve/scenario/sezione, valori degli indicatori e dati numerici identici. Sono coperti tutti i passi della metodologia, le viste annuali/mensili/orarie, le classifiche esplorative e gli input live senza avviare il motore al cambio lingua. La verifica nel browser comprende navigazione, impaginazione e una simulazione live.

Streamlit non espone un punto di inserimento per widget nella propria barra. Il contenitore `language_toolbar` è perciò posizionato sulla barra, con altezza e allineamento centrati; un padding sulla classe semantica `.stAppToolbar` gli riserva una corsia, separata dall’indicatore Running, dal pulsante Stop e dal menu. Non si usano classi CSS generate né si nascondono i controlli di esecuzione. Popover e selezione delle lingue restano nativi. Ricontrollare allineamento e assenza di sovrapposizioni, anche durante una simulazione, dopo aggiornamenti di Streamlit.

## Layout e viste relative

- Le schede KPI usano contenitori nativi che vanno a capo secondo lo spazio disponibile. Valori, titoli e delta non vengono abbreviati con puntini.
- I pannelli dei grafici si dispongono su una sola colonna quando due grafici non avrebbero spazio sufficiente. Assi, radar e torte adattano etichette e dimensioni; le legende restano sotto e sono scorrevoli.
- I boxplot esplorativi sono orizzontali: le lunghe etichette dei nove indicatori non devono essere ruotate né uscire dal grafico. I dati e la normalizzazione 0–1 restano identici.
- Immatricolazioni annue e parco veicoli offrono **valori assoluti / quote sul totale [%]**. Per ogni anno il denominatore è la somma di tutte le motorizzazioni dello stesso scenario. La baseline usa il proprio totale; nascondere una serie nella legenda non cambia il denominatore. Totali nulli, incompleti o negativi danno una quota non disponibile, mai uno zero artificiale.
- Le quote sono visualizzate come aree impilate al 100%, senza smussamento fra gli anni. Con il confronto attivo, scenario selezionato e Base hanno due pannelli distinti con la stessa scala: le loro quote non vengono sommate. BEV è la prima area, così i punti storici sono direttamente confrontabili con il suo bordo superiore. Tornando ai valori assoluti vengono ripristinate le linee e la scala automatica; cambi di unità, limiti o impilamento non riutilizzano la transizione animata precedente.
- I punti storici BEV nelle immatricolazioni restano disponibili **dal 2011 al 2024 anche in percentuale**: `EVinput.csv` contiene le sette serie `Adoption Vehicles[...]` e il denominatore è il loro totale nell’anno. Non si usa il totale simulato per normalizzare le osservazioni. Si tratta dello storico delle immatricolazioni, non del parco in circolazione.
- La conversione riguarda soltanto la visualizzazione: modello, parquet, CSV di input e schema delle esportazioni grezze non cambiano.

### Estensione delle quote a energia e superficie

Gli stessi componenti sono usati dalle pagine precalcolate e dalle simulazioni live:

| Grafico | Denominatore della vista relativa |
| --- | --- |
| Mix elettrico per fonte | Totale del flusso selezionato: dispacciamento, consumo, esportazione oppure offerta locale. L'offerta esclude le importazioni, come la vista assoluta. |
| Consumo per vettore di riscaldamento | Somma degli otto vettori, incluso il calore ambiente delle pompe di calore. |
| Superficie riscaldata per efficienza | Somma delle superfici di tutte le classi di efficienza nell'anno. |
| Energia PV annuale | Produzione PV annuale; le sole componenti sono autoconsumo e immissione in rete. La produzione non viene sommata nuovamente alle componenti. |

Le quote elettriche annuali/mensili sono calcolate **dopo** l'aggregazione dell'energia, non come media delle percentuali orarie. Analogamente, nelle viste cumulate si normalizzano i valori cumulati. Le viste annuali e orarie usano aree impilate al 100%; quella mensile barre impilate al 100%. Il pompaggio, che mostra un unico flusso di domanda, mantiene la vista assoluta.

Il confronto relativo con la Base ha pannelli separati, con denominatore proprio e scala comune 0–100%. I periodi con totale nullo non hanno quote definite. La vista assoluta conserva i grafici precedenti e ripristina i limiti automatici anche per le barre mensili/orarie. Il controllo dello storico PV viene disabilitato soltanto nella vista relativa: esistono osservazioni di produzione totale, non della sua ripartizione in autoconsumo e immissione. Tornando alla vista assoluta lo storico è nuovamente disponibile.

Test mirati: `python -m unittest discover -s tests -p 'test_energy_relative_views.py' -v`. Coprono denominatore PV, storico, baseline, cumulati energetici, superfici, esclusione delle importazioni dall'offerta, totali nulli e ritorno alla scala assoluta in tutte le viste elettriche.

Verifica dell'estensione (23 ottobre 2026): 42 test pertinenti superati, inclusi i cinque nuovi controlli sui denominatori; ripetuti anche i tre test multilingue dopo l'adattamento della griglia PV. Nel browser sono stati verificati i quattro casi a 1280 e 1024 pixel, il ritorno ai GWh (anche mensili), i pannelli Base e una corsa Julia live con contributo cantonale PV all'11%. Tutte le quattro viste sono state aperte anche sui risultati live; il cambio IT→FR→DE conserva risultati e vista relativa. La griglia PV condivisa ora va a capo secondo la larghezza disponibile, anche nella pagina live.

## Verifica visiva della preview (23 ottobre 2026)

Controllo nel browser a 1440×900 e 1280×800 (desktop/laptop), 1024×768 e 768×1024 (tablet), 853×600 e 390×844. La larghezza di 853 pixel verifica anche lo spazio CSS disponibile su un laptop da 1280 pixel con zoom 150%; è una verifica equivalente del layout, non una prova dello zoom nativo o di un tablet fisico. Sono stati controllati KPI e delta, radar, boxplot, grafici temporali e a torta, selettori, sidebar aperta/chiusa e toolbar durante una simulazione.

La prova live completa usa il modello v7 invariato, con RCPv attivato prima del cambio IT→FR. La scelta è conservata al clic successivo e nel riepilogo del risultato; passando FR→DE restano identici risultati numerici e sezione selezionata. Questo controllo browser integra AppTest: il solo test Python non riproduceva la perdita delle etichette selezionate nel frontend.

Esito: 50 test pertinenti superati (11 i18n, 3 sulle quattro lingue, 3 sulle quote, 19 sui grafici, 5 sulla sintesi live e 9 sull’analisi esplorativa), oltre alla simulazione live e ai controlli visivi descritti sopra.

## Avvio locale

Preparare l'ambiente e i dati secondo il README della release. Con gli artefatti Julia v7 disponibili, impostare `SURE_BACKEND=julia`, `SURE_VARIANT=v7` e, se necessario, `SURE_JULIA_BIN` e `JULIA_DEPOT_PATH` per la propria installazione. Non ereditare un `SURE_JULIA_MODEL` di un esperimento diverso.

```sh
python -m streamlit run server.py --server.address 127.0.0.1 --server.port 8504 --server.headless true
```

Il lifecycle attende il riscaldamento del motore Julia prima di dichiarare l'app pronta. La porta 8504 è distinta dall'anteprima sperimentale E22 sulla porta 8503.
