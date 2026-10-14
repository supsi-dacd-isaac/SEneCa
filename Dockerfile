FROM python:3.11.8-slim-bookworm@sha256:90f8795536170fd08236d2ceb74fe7065dbf74f738d8b84bfbf263656654dc9b AS runtime
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates && rm -rf /var/lib/apt/lists/*
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
RUN git clone https://github.com/SDXorg/pysd.git /opt/pysd && \
    git -C /opt/pysd checkout 8991d119e139029d4dec712d257cf5fcc3549b8f && \
    git -C /opt/pysd -c submodule.pysd/builders/julia/PySD.jl.url=https://github.com/rogersamso/PySD.jl.git submodule update --init pysd/builders/julia/PySD.jl && \
    test "$(git -C /opt/pysd/pysd/builders/julia/PySD.jl rev-parse HEAD)" = abe4251fe91734f83776a9c782088d3a2f09dc57 && \
    python -m venv --system-site-packages /opt/translator && /opt/translator/bin/pip install --no-deps -e /opt/pysd
ENV JULIA_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1 SURE_VARIANT=v6 JULIA_DEPOT_PATH=/runtime/julia-depot
WORKDIR /app

FROM runtime AS model-builder
ENV JULIA_DEPOT_PATH=/opt/julia-depot JULIA_CPU_TARGET=generic
COPY sure_julia/julia/Project.toml sure_julia/julia/Manifest.toml /opt/julia-env/
RUN julia --startup-file=no --project=/opt/julia-env -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'
COPY . /app
RUN python scripts/data_release.py verify && python -m sure_julia.pv_budget --check && /opt/translator/bin/python -m sure_julia.build /app/sure_julia/generated && python scripts/verify_julia_release.py

FROM runtime AS application
ARG CODE_VERSION=dev
ARG DATA_RELEASE_TAG=unknown
ENV JULIA_DEPOT_PATH=/opt/julia-depot JULIA_CPU_TARGET=generic PYTHONPATH=/app SURE_BACKEND=julia STREAMLIT_SERVER_PORT=8501 STREAMLIT_SERVER_ADDRESS=0.0.0.0
COPY --from=model-builder /opt/julia-depot /opt/julia-depot
COPY --from=model-builder /app /app
RUN rm -rf /opt/pysd /opt/translator && python scripts/data_release.py verify
LABEL org.opencontainers.image.source="https://github.com/supsi-dacd-isaac/SEneCa" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${CODE_VERSION}" \
      ch.supsi.seneca.data-release="${DATA_RELEASE_TAG}"
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
