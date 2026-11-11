# Staging su Elettra con la traduzione nativa

Lo staging è un secondo container accanto alla produzione: progetto Compose
`seneca-staging`, container `seneca-staging`, immagine `seneca-staging:native`,
porta 8503. La produzione (`seneca-streamlit-prod`, porta 8501, gestita da
`/home/elettra/projects/SEneCa`) non viene toccata.

## 1. Sul PC: scenari e pacchetto

```sh
# scenari della webapp con il build nativo (vedi sure_native/README.md)
PYTHONUTF8=1 SURE_JULIA_MODEL=sure_native/generated \
  python -m sure_julia.batch RUN_DIR --workers 4 --validation VALIDATION_DIR
# pacchetto: commit corrente + build nativo + RUN_DIR/release
python deploy/make_staging_bundle.py RUN_DIR/release
```

## 2. Copia su Elettra (VPN OpenVPN Connect attiva)

```sh
scp dist/seneca-staging-<commit>.tar.gz <utente>@<elettra>:/ssd2/elettra/
```

## 3. Su Elettra

```sh
cd /ssd2/elettra
mkdir seneca-staging-<commit> && tar xzf seneca-staging-<commit>.tar.gz -C seneca-staging-<commit> --strip-components=1
cd seneca-staging-<commit>
cp /home/elettra/projects/SEneCa/.env .env   # facoltativo: chiave CARTO per le mappe
docker compose -f deploy/docker-compose.staging.yml up -d --build
docker compose -f deploy/docker-compose.staging.yml logs -f   # attendere "Julia worker ready"
```

La build dell'immagine esegue `deploy/check_staging_release.py`: si ferma se gli
scenari precalcolati non sono stati generati con lo stesso build nativo.
L'avvio compila il modello (circa un minuto) prima di accettare richieste.

Indirizzo: `http://<elettra>:8503`

## 4. Arresto

```sh
docker compose -f deploy/docker-compose.staging.yml down
```
