# SURE v7 production backend

The supported model is `sure-v7-dispatch-1`. Its retained validation evidence
is under `docs/validation/`; small-model regression fixtures are under
`model_checks/`. Obsolete models and experiment runners are available in
the Git history at `v0.3.1`, not in the current checkout. See the
[repository inventory](repository-inventory.md).

## Execution contract

`SURE_BACKEND=julia` is the application default; `SURE_BACKEND=python`
selects the independent PySD 3.14.3 implementation. Both use the canonical v7 equations
including the FER, shared PV budget and priority dispatch corrections,
calibrated constants, synchronous pre-step DELAY FIXED inputs, Float64 and
fixed annual Euler steps from 2011 through 2050. A Julia failure is reported
and never silently retried with Python. Switching the live backend does not
replace the precomputed dataset.

Release `v0.4.0` pins `data-v2.0.0`, regenerated with this v7 model and the
five supplied calibration OUT files. The run `v7-calibrated-001` completed
14,571 unique simulations on 16 October 2026 at 20:28 Europe/Zurich. All 418
Python–Julia cases, state-isolation checks, serial/parallel pilots and the
final physical/data audit passed. See the
[v7 report](validation/dispatch-correction.md).

The original native Vensim allocator retains small numerical differences in
the high scenario. An equivalent diagnostic allocation isolates their cause;
this is not a certificate of native equivalence across arbitrary scenarios.
Release acceptance uses strict Python–Julia agreement and physical checks.
Previous v6 releases (`v0.2.0`–`v0.3.1`) and their data remain immutable.

`python -m sure_julia.pv_budget --check` verifies that the canonical native and
preprocessed v7 sources contain the same shared PV budget. It does not generate
another model. `python scripts/import_calibration.py --check` verifies the 56
OUT assignments and their Float64 export. Native precision diagnosis and its
limits are documented in [the dispatch report](validation/dispatch-correction.md).

The policy-mix update uses `sh scripts/prepare_model_release.sh <new-run-id>`:
418 validation cases, serial/parallel pilots, 14,571 unique simulations and
the final data audit. It has no publication, merge or deployment step. Its
final status is `ready-for-release`. See the
[100-sample procedure](policy-mix-100.md) for the input specification and
sample identity. To reproduce the earlier 8,171-simulation release, check out
`v0.2.0` and use its `prepare_pv_bounded.sh` and pinned 50-sample dataset.

Launch from the Elettra host (choose an unused run ID). Pass the commit from
the host because the worktree's Git administration directory is not mounted
inside the container:

```sh
task_source_commit=$(git -C /ssd2/elettra/seneca-v7-calibrated rev-parse HEAD)
docker run -d --init --name seneca-v7-calibrated-new \
  --cpuset-cpus=0-31 --memory=128g --memory-swap=128g \
  -e SURE_SOURCE_COMMIT="$task_source_commit" \
  -v /ssd2/elettra/seneca-v7-calibrated:/app \
  -v /ssd2/elettra/seneca-runtime:/runtime \
  -v /ssd2/elettra/seneca-runs:/runs \
  seneca-julia-runtime:production sh -c \
  'cd /app && sh scripts/prepare_model_release.sh v7-calibrated-new > /runs/v7-calibrated-new-launch.log 2>&1'
```

Progress, exit status and memory samples are written under `/runs/<run-id>`.
A new directory is required; a failed gate stops all subsequent phases.

Julia 1.10.12, Python 3.11.8, the translator revision and companion PySD.jl
revision are pinned by `deploy/Dockerfile.julia-runtime`; package locks live
in `sure_julia/`. Production translation supports the audited SURE profile,
not arbitrary Vensim models. No Vensim DLL is needed. Equivalence with the
native Vensim engine has not been achieved and is not claimed.

Application images precompile dependency caches with `JULIA_CPU_TARGET=generic`
so the cache can move between processors of the same architecture. This affects
on-disk package images, not the model's in-memory JIT; see the
[Julia 1.10 documentation](https://docs.julialang.org/en/v1.10.0/manual/environment-variables/#JULIA_CPU_TARGET).

From v0.3.0 the application starts through `streamlit run server.py`.
Its ASGI lifespan warms the shared live engine with a complete base simulation
before the server accepts requests or reports health. `sure_live.get_engine`
owns that single cached process, also imported by the live page; the warm-up
result is discarded, while the compiled code stays resident. Shutdown closes
the worker, and a failed warm-up aborts startup. The Python backend is still
explicitly selectable and does not launch Julia. Every service restart pays
the compilation cost once; a worker restarted after a crash must also compile
again. Image checks prove that the first UI simulation reuses the warmed PID
and records zero compilation time.

The live page displays progress for initialization, integration, result
extraction and validation. Annual updates describe extraction of the 2011–2050
outputs; the integration phase is reported as a whole. The bar measures four
completed phases, not elapsed time or a predicted finish time. Optional JSON
events travel on the worker's existing request channel, are tied to the request
ID and share the original absolute timeout. They do not modify the generated
model, solver or delay callbacks. Cached results do not replay old progress
messages, and errors clear the transient bar. Startup warms this event path too.

The Julia process loads one generated model and accepts complete sets of
40 parameters. Each request owns its initial state, delay buffers and caches.
Results preserve the explicit dimension labels in `export.json`. The Python
adapter enforces a timeout and serializes access; a later request starts a new
process if the old one exited. Logs are retained in the worker's temporary
directory. Model and data identity are part of the bounded web result cache.

## Elettra

The current worktree is `/ssd2/elettra/seneca-v7-calibrated`, with runtime/depot
in `/ssd2/elettra/seneca-runtime` and results in `/ssd2/elettra/seneca-runs`.
The earlier model worktree is `/ssd2/elettra/seneca-julia-production`;
`/home/elettra/projects/SEneCa` manages the production deployment on `main`.
Use 32 separate workers, CPU affinity `0-31` (one thread per physical core),
128 GiB memory, and one Julia/BLAS/OpenMP thread per worker. Launch the batch
in a detached Docker container so it does not depend on an SSH connection.

The gated script above also installs and validates the deterministic 100-sample
design before validation. After that preparation, the individual commands
inside the pinned runtime, with the repository at `/app` and results at `/runs`,
are:

```sh
julia --startup-file=no --project=sure_julia/julia -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'
/opt/translator/bin/python -m sure_julia.build /app/sure_julia/generated
python -m sure_julia.targeted /runs/targeted
python -m sure_julia.validation /runs/validation --workers 32 --targeted /runs/targeted
python -m sure_julia.validation /runs/validation --repeats
python -m sure_julia.validation /runs/validation --certify --targeted /runs/targeted
python -m sure_julia.batch /runs/pilot-serial --pilot --workers 1 --validation /runs/validation
python -m sure_julia.batch /runs/pilot-parallel --pilot --workers 32 --validation /runs/validation
python -c 'from sure_julia.batch import compare_pilots; compare_pilots("/runs/pilot-serial", "/runs/pilot-parallel", "/runs/pilot-comparison.json")'
python -m sure_julia.batch /runs/full --workers 32 --validation /runs/validation
```

There are 418 validation cases and 14,579 dataset configurations, deduplicated
to 14,571 simulations. Every result cell uses
`abs(Julia-Python) <= 1e-10*max(1,S) + 1e-8*abs(Python)`, where S is the
maximum absolute Python value over time for that element. Discrete values,
labels and years are exact. Unsupported warnings and invalid values fail
validation. The 100 LHS samples (seed 20261004) replace the former 50-sample
design; all 128 policy mixes use the same 100 uncertainty draws.
The translated build manifest remains immutable; validation is recorded in a
separate certificate, checked before any regeneration starts.
Resume requires identical build, code, parameter and sample identities and
verified completed-output checksums. No failed scenario is dropped.

The corrected model rejects substantive negative housing stocks or GMD weights.
Roundoff exclusions in GMD remain explicitly audited; raw simulation arrays
are never modified or excluded from the Python–Julia comparison. Every live
request and batch scenario checks stock nonnegativity, paired heating/PV/
renovation transfers, Euler integration and building-population conservation.
The small initial fine/coarse input discrepancy is recorded and its offset
must remain constant. Nonfinite values or missing diagnostics fail the run.

The batch stages nine application Parquets plus provenance separately from
the installed dataset. Release `data-v2.0.0` includes six native input VDFX rebuilt from the current
CSVs and excludes the obsolete published VPMX. Native source hashes and
roundtrip checks accompany the Julia scenario/build provenance.

## Release checks and rollback

Build and numerically smoke-test both Linux AMD64 and ARM64 images. Run
`python -m sure_julia.smoke /tmp/smoke --ui` inside each image. The check runs
base/high and the negative-stock regression case in both engines and submits a real simulation through Streamlit
AppTest. Release publication additionally requires the full Elettra suite
and serial/parallel pilot comparison. Use a versioned image on the Mac,
smoke-test on a temporary port, and retain the previous image tag/digest for
rollback. Restore that tag to revert both application code and its pinned
dataset.

For the previous `v0.1.1` image, also restore its model selection:
`SENECA_IMAGE_TAG=v0.1.1 SURE_VARIANT=v3 SURE_BACKEND=python docker compose -f docker-compose.prod.yml up -d`.
The new images require v7; the variant override exists to make old-image
rollback explicit, not to run the production Julia backend against v3.

## Historical investigations

The v2–v5 models, the unbounded-stock investigations and the superseded
experimental correction are retained in the
[v0.3.1 archive](https://github.com/supsi-dacd-isaac/SEneCa/tree/v0.3.1/benchmarks).
They are not supported simulation alternatives. Current validation uses the
fixtures in `model_checks/` and production translator helpers directly, including
the allocation oracle extracted from `SURE_pysd_v7.py`.

To audit a newly regenerated dataset:

```sh
python scripts/verify_production_data.py /runs/full /runs/release-verification.json --resources /runs/resources.jsonl
```

This checks all nine application Parquets, complete 40-parameter scenario
provenance, physical reports, unchanged uncertainty samples, configuration
coverage, Float64/finite values and zero compilation after worker warm-up.
