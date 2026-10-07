# Release dati e immagini Docker

## Cosa viene versionato

Il codice contiene `data-release.json`, che fissa un tag `data-vX.Y.Z`, il nome
dell'archivio e il suo SHA-256. L'archivio della release dati contiene i 9
Parquet pre-calcolati, i 6 input Vensim `.vdfx`, `SURE.vpmx` e un manifest con
dimensione e SHA-256 di ciascun file. La prima release è
[`data-v1.0.0`](https://github.com/supsi-dacd-isaac/SEneCa/releases/tag/data-v1.0.0),
preparata riusando i file esistenti senza rigenerarli.

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
   **rigenerare** risultati o binari Vensim occorre una macchina con Vensim DSS;
   su una macchina senza Vensim si possono soltanto riusare o caricare output
   già prodotti altrove. Verificare la correttezza scientifica dei nuovi output
   prima di pubblicarli.
2. Installare `requirements.txt` e preparare un tag dati mai usato, per esempio:

   ```bash
   python scripts/data_release.py pack --tag data-v1.0.1 --source-commit "$(git rev-parse HEAD)"
   ```

   `pack` richiede tutti i 16 file, rifiuta puntatori LFS e Parquet vuoti o
   illeggibili, e produce in `dist/data-release/` l'archivio, `SHA256SUMS.txt`
   e un nuovo `data-release.json`. I percorsi dei file rimangono quelli attesi
   dal codice; se cambiano, aggiornare e testare insieme il tool e l'app.
3. Pubblicare gli asset sullo **stesso repository**, con un tag dati nuovo:

   ```bash
   gh release create data-v1.0.1 \
     dist/data-release/seneca-data-v1.0.1.tar.gz \
     dist/data-release/SHA256SUMS.txt \
     --target "$(git rev-parse HEAD)" \
     --title "SEneCa data v1.0.1" \
     --notes "Snapshot dati v1.0.1; licenza MIT. Usare l'asset, non l'archivio sorgente automatico."
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

I file LFS rimangono nella cronologia Git e sullo storage remoto, anche se non
sono più nella versione corrente di `main`: questa migrazione non recupera la
quota LFS storica.
