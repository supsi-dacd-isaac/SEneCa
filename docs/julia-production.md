# SURE v4 production backend

Implementation branch: `julia-production`, based on main
`17db1f4245c6bb0e8ef41a4cac5e8d3a6817cac6`; the validated experiments were
merged in `962b774`. Historical experiments remain under `benchmarks/` and
are excluded from the application image.

## Execution contract

`SURE_BACKEND=julia` is the application default; `SURE_BACKEND=python`
selects the independent PySD 3.14.3 implementation. Both use SURE v4,
calibrated constants, synchronous pre-step DELAY FIXED inputs, Float64 and
fixed annual Euler steps from 2011 through 2050. A Julia failure is reported
and never silently retried with Python. Switching the live backend does not
replace the precomputed dataset.

Julia 1.10.12, Python 3.11.8, the translator revision and companion PySD.jl
revision are pinned by `deploy/Dockerfile.julia-runtime`; package locks live
in `sure_julia/`. Production translation supports the audited SURE profile,
not arbitrary Vensim models. No Vensim DLL is needed. Equivalence with the
native Vensim engine has not been achieved and is not claimed.

The Julia process loads one generated model and accepts complete sets of
40 parameters. Each request owns its initial state, delay buffers and caches.
Results preserve the explicit dimension labels in `export.json`. The Python
adapter enforces a timeout and serializes access; a later request starts a new
process if the old one exited. Logs are retained in the worker's temporary
directory. Model and data identity are part of the bounded web result cache.

## Elettra

The worktree is `/ssd2/elettra/seneca-julia-production`, with runtime/depot in
`/ssd2/elettra/seneca-runtime` and results in `/ssd2/elettra/seneca-runs`.
The original clone in `/home/elettra/projects/SEneCa` remains on its branch.
Use 32 separate workers, CPU affinity `0-31` (one thread per physical core),
128 GiB memory, and one Julia/BLAS/OpenMP thread per worker. Launch the batch
in a detached Docker container so it does not depend on an SSH connection.

Inside the pinned runtime, with the repository at `/app` and results at `/runs`:

```sh
python scripts/data_release.py fetch
julia --startup-file=no --project=sure_julia/julia -e 'using Pkg; Pkg.instantiate(); Pkg.precompile()'
/opt/translator/bin/python -m sure_julia.build /app/sure_julia/generated
python -m sure_julia.targeted /runs/targeted
python -m sure_julia.validation /runs/validation --workers 32 --targeted /runs/targeted
python -m sure_julia.validation /runs/validation --repeats
python -m sure_julia.batch /runs/pilot-serial --pilot --workers 1 --validation /runs/validation
python -m sure_julia.batch /runs/pilot-parallel --pilot --workers 32 --validation /runs/validation
# Compare every pilot value hash before running the full dataset.
python -m sure_julia.batch /runs/full --workers 32 --validation /runs/validation
```

There are 317 validation cases and 8,179 dataset configurations, deduplicated
to 8,171 simulations. Every result cell uses
`abs(Julia-Python) <= 1e-10*max(1,S) + 1e-8*abs(Python)`, where S is the
maximum absolute Python value over time for that element. Discrete values,
labels and years are exact. Unsupported warnings and invalid values fail
validation. The 50 existing LHS samples (seed 20261004) are retained verbatim.
Resume requires identical build, code, parameter and sample identities and
verified completed-output checksums. No failed scenario is dropped.

The batch stages nine application Parquets plus provenance separately from
the installed dataset. The seven Vensim reference/input archives remain
historical files from `data-v1.0.0`. `data-v1.1.0` adds complete effective
parameters and build provenance; `v0.2.0` pins that immutable data release.

## Release checks and rollback

Build and numerically smoke-test both Linux AMD64 and ARM64 images. Run
`python -m sure_julia.smoke /tmp/smoke --ui` inside each image. The check runs
base/high in both engines and submits a real simulation through Streamlit
AppTest. Release publication additionally requires the full Elettra suite
and serial/parallel pilot comparison. Use a versioned image on the Mac,
smoke-test on a temporary port, and retain the previous image tag/digest for
rollback. Restore that tag to revert both application code and its pinned
dataset.

## Implementation status

- Elettra infrastructure and existing data-v1.0.0 archive verified.
- Linux runtime built; portable model translated with 121 exports and 40 parameters.
- First base comparison passed: 5,689,080 cells and energy conservation.
- Full-suite validation, pilot, complete regeneration and releases remain pending.
