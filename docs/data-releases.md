# Release dati e immagini Docker

## Cosa viene versionato

Il codice contiene `data-release.json`, che fissa un tag `data-vX.Y.Z`, il nome
dell'archivio e il suo SHA-256. L'archivio della release dati contiene i 9
Parquet pre-calcolati, i 6 input Vensim `.vdfx` e un manifest con
dimensione e SHA-256 di ciascun file. La prima release è
[`data-v1.0.0`](https://github.com/supsi-dacd-isaac/SEneCa/releases/tag/data-v1.0.0),
preparata riusando i file esistenti senza rigenerarli.

Dalla release `data-v1.1.0` sono richiesti anche
`provenance/scenarios.parquet` e `provenance/build.json`: registrano i 40
parametri effettivi, il modello, i checksum e le evidenze della validazione.
Dalla release `data-v2.0.0` il vecchio `SURE.vpmx` è escluso e i sei VDFX
sono ricostruiti dai CSV correnti della v7. La riesportazione nativa è
verificata su tutte le serie e gli anni; sorgenti e checksum sono registrati
in `provenance/build.json`. Gli archivi v1 restano immutabili e leggibili.

Il download non richiede Git LFS o Vensim:

```bash
python scripts/data_release.py fetch
python scripts/data_release.py verify
```

Il comando `fetch` scarica l'asset pubblico della release indicata nel pin,
verifica l'archivio e ogni file, e installa i percorsi attesi. Un asset assente,
un checksum diverso, un puntatore LFS o un percorso inatteso causano un errore.
Non usare lo ZIP sorgente generato automaticamente da GitHub: è diverso
dall'asset dati allegato alla release.

## Pubblicare una nuova versione dei dati

1. Partire da un checkout aggiornato, eseguire `fetch` per recuperare il
   precedente snapshot e sostituire solo i file che devono cambiare. Per
   rigenerare gli output Julia seguire la [procedura validata](julia-production.md).
   Vensim DSS serve per rigenerare i riferimenti nativi Vensim. Verificare la
   correttezza scientifica dei nuovi output prima di pubblicarli.
2. Installare `requirements.txt` e preparare un tag dati mai usato, per esempio:

   ```bash
   python scripts/data_release.py pack --tag data-v2.0.0 --source-commit "$(git rev-parse HEAD)"
   ```

   `pack` richiede 17 file per v2, 18 per v1.1–v1.2 e 16 per v1.0.0, rifiuta puntatori LFS e Parquet vuoti o
   illeggibili, e produce in `dist/data-release/` l'archivio, `SHA256SUMS.txt`
   e un nuovo `data-release.json`. I percorsi dei file rimangono quelli attesi
   dal codice; se cambiano, aggiornare e testare insieme il tool e l'app.
3. Pubblicare gli asset sullo **stesso repository**, con un tag dati nuovo:

   ```bash
   gh release create data-v2.0.0 \
     dist/data-release/seneca-data-v2.0.0.tar.gz \
     dist/data-release/SHA256SUMS.txt \
     --target "$(git rev-parse HEAD)" \
     --title "SEneCa data v2.0.0" \
     --notes-file dist/data-release/release-notes.md
   ```

   Riportare nelle note la provenienza degli output, le modifiche e il commit
   sorgente. Non sostituire asset o tag già pubblicati.
4. Copiare il contenuto del `data-release.json` generato nel file omonimo
   tracciato dal codice. Eseguire `fetch` da GitHub e `verify` in un checkout
   pulito; poi aggiornare il README e pubblicare una nuova release **codice**
   `vX.Y.Z`. La GitHub Action usa il pin del commit rilasciato, esegue uno smoke
   test e pubblica l'immagine versionata e `latest`. Una release `data-v…` non
   pubblica immagini da sola.

## Sviluppo e deploy

`docker-compose.yml` costruisce localmente: eseguire prima `fetch`.
`docker-compose.prod.yml` usa `ghcr.io/supsi-dacd-isaac/seneca:latest` per
default. Il deploy è manuale (`docker compose -f docker-compose.prod.yml pull`
seguito da `up -d`). Impostare `SENECA_IMAGE_TAG=vX.Y.Z` per tenere o ripristinare
una versione precisa. L'immagine espone nei metadati il tag della release dati
incorporata. La chiave CARTO resta una variabile d'ambiente a runtime.
Il rollback all'immagine `v0.1.1` richiede anche `SURE_VARIANT=v3` e
`SURE_BACKEND=python`, coerenti con il modello contenuto in quella versione.

I file LFS rimangono nella cronologia Git e sullo storage remoto, anche se non
sono più nella versione corrente di `main`: questa migrazione non recupera la
quota LFS storica.
