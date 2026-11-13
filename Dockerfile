FROM python:3.11.8-slim-bookworm@sha256:90f8795536170fd08236d2ceb74fe7065dbf74f738d8b84bfbf263656654dc9b
# The model is the native translation of Vensim/SURE.mdl in sure_native/generated,
# validated against Vensim and committed with its checksums. The build does not
# translate the model again: it only checks that the pinned dataset was generated
# by exactly this build (scripts/verify_julia_release.py).
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY sure_julia/python.lock /opt/sure/python.lock
RUN pip install --no-cache-dir -r /opt/sure/python.lock
RUN case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      amd64) arch=x86_64; directory=x64; checksum=b0c50dfe349d76ffc8580d24e0c0be623988a6d91ed57ad8b73c0137fd27bc0d ;; \
      arm64) arch=aarch64; directory=aarch64; checksum=cc257b21967049642bfe17de1aff7dae17477eba4f423f98cb400c002080e5a2 ;; \
      *) exit 1 ;; esac && \
    curl --fail --location --retry 3 "https://julialang-s3.julialang.org/bin/linux/$directory/1.10/julia-1.10.12-linux-$arch.tar.gz" -o /tmp/julia.tar.gz && \
    echo "$checksum  /tmp/julia.tar.gz" | sha256sum -c - && \
    tar xzf /tmp/julia.tar.gz -C /opt && rm /tmp/julia.tar.gz && \
    ln -s /opt/julia-1.10.12/bin/julia /usr/local/bin/julia
ENV JULIA_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
    JULIA_DEPOT_PATH=/opt/julia-depot JULIA_CPU_TARGET=generic \
    PYTHONPATH=/app SURE_VARIANT=v8 SURE_BACKEND=julia SURE_JULIA_MODEL=/app/sure_native/generated \
    STREAMLIT_SERVER_PORT=8501 STREAMLIT_SERVER_ADDRESS=0.0.0.0
WORKDIR /app
# Julia packages of the native worker (versions pinned in sure_native/Manifest.toml)
COPY sure_native/Project.toml sure_native/Manifest.toml /app/sure_native/
RUN julia --startup-file=no --project=/app/sure_native -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'
ARG CODE_VERSION=dev
ARG DATA_RELEASE_TAG=unknown
COPY . /app
RUN python scripts/data_release.py verify && python scripts/verify_julia_release.py
LABEL org.opencontainers.image.source="https://github.com/supsi-dacd-isaac/SEneCa" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${CODE_VERSION}" \
      ch.supsi.seneca.data-release="${DATA_RELEASE_TAG}"
EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --start-period=300s --retries=3 CMD curl --fail --silent http://127.0.0.1:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "server.py", "--server.port=8501", "--server.address=0.0.0.0"]
