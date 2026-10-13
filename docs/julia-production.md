# SURE v5 production backend

Implementation branch: `julia-production`, based on main
`17db1f4245c6bb0e8ef41a4cac5e8d3a6817cac6`; the validated experiments were
merged in `962b774`. Historical experiments remain under `benchmarks/` and
are excluded from the application image.

## Execution contract

`SURE_BACKEND=julia` is the application default; `SURE_BACKEND=python`
selects the independent PySD 3.14.3 implementation. Both use the upstream v5
equations from commit `bf39813` without the provisional v4 stock-flow patch,
calibrated constants, synchronous pre-step DELAY FIXED inputs, Float64 and
fixed annual Euler steps from 2011 through 2050. A Julia failure is reported
and never silently retried with Python. Switching the live backend does not
replace the precomputed dataset.

Julia 1.10.12, Python 3.11.8, the translator revision and companion PySD.jl
revision are pinned by `deploy/Dockerfile.julia-runtime`; package locks live
in `sure_julia/`. Production translation supports the audited SURE profile,
not arbitrary Vensim models. No Vensim DLL is needed. Equivalence with the
native Vensim engine has not been achieved and is not claimed.

Application images precompile dependency caches with `JULIA_CPU_TARGET=generic`
so the cache can move between processors of the same architecture. This affects
on-disk package images, not the model's in-memory JIT; see the
[Julia 1.10 documentation](https://docs.julialang.org/en/v1.10.0/manual/environment-variables/#JULIA_CPU_TARGET).

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
python -m sure_julia.validation /runs/validation --certify --targeted /runs/targeted
python -m sure_julia.batch /runs/pilot-serial --pilot --workers 1 --validation /runs/validation
python -m sure_julia.batch /runs/pilot-parallel --pilot --workers 32 --validation /runs/validation
python -c 'from sure_julia.batch import compare_pilots; compare_pilots("/runs/pilot-serial", "/runs/pilot-parallel", "/runs/pilot-comparison.json")'
python -m sure_julia.batch /runs/full --workers 32 --validation /runs/validation
```

There are 318 validation cases and 8,179 dataset configurations, deduplicated
to 8,171 simulations. Every result cell uses
`abs(Julia-Python) <= 1e-10*max(1,S) + 1e-8*abs(Python)`, where S is the
maximum absolute Python value over time for that element. Discrete values,
labels and years are exact. Unsupported warnings and invalid values fail
validation. The 50 existing LHS samples (seed 20261004) are retained verbatim.
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
the installed dataset. The seven Vensim reference/input archives remain
historical files from `data-v1.0.0`. `data-v1.1.0` adds complete effective
parameters and build provenance; `v0.2.0` pins that immutable data release.

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
Current images require v5; the variant override exists to make old-image
rollback explicit, not to run the production Julia backend against v3.

## Historical validation of the original, unbounded v4

The following results predate the authorized stock correction. They remain a
baseline only and cannot certify the corrected model or its data release.

- Elettra infrastructure and existing data-v1.0.0 archive verified.
- Linux runtime built; portable model translated with 121 exports and 40 parameters.
- First base comparison passed: 5,689,080 cells and energy conservation.
- Full Linux AMD64 suite passed: all 317 cases, each comparing 5,689,080 cells
  across 121 application and diagnostic outputs. Targeted tests also passed.
- State isolation and crash recovery passed, including exact fresh-process
  repeats and zero compilation when changing scenario after warm-up.
- Native AMD64 and ARM64 images passed base/high, GMD and Streamlit checks.
- All 100 pilot scenarios produced identical numeric hashes and Parquet files
  in serial and parallel. Total time: 1,087.15 seconds in serial and 195.27
  seconds with 32 workers, including startup. Warm parallel scenarios averaged
  13.07 seconds. Serial warm scenarios had median 9.58 seconds and range
  8.71–11.15 seconds, with output sets specific to each section.
- A separate single-core check of the actual 52-output live backend measured
  9.70 seconds median over five warm base runs (9.17–9.88 seconds), 10.71 seconds
  for high and 111.52 seconds for the first cold base request, including loading.
  These times include dataframe extraction but exclude Streamlit rendering,
  network and cache hits. No compilation occurred on any warm request.
- Full regeneration completed on 2026-10-13 at 14:38 CEST: 8,171 simulations
  representing 8,179 configurations, no failures, 3,622.90 seconds including
  consolidation. No worker compiled additional code after warm-up. Sampled
  peak container memory was 39,199,764,480 bytes (36.51 GiB), below 128 GiB.
- Final artifact verification passed: expected row counts and columns, no
  missing or nonfinite numeric values, Float64 outputs, all 40 parameters
  recorded per scenario and the original uncertainty sample checksum intact.
- The full GMD audit records substantive negative weights in 2,186 scenarios;
  the smallest weight is -688.6002. The established exclusion rule is preserved
  and every affected scenario is identified in the provenance table. A further
  direct check of the worst case (PV/battery policy, 29 arrays) passed against
  Python, including the GMD indicators; the negative states are shared.
- Generation source commit: `170fe746fe5fbe6f52228f7061910374edc4e6c9`.
  Numerical evidence is attached to the draft `data-v1.1.0` and must be replaced
  with evidence for the corrected model before publication.

## Nonnegative-stock investigation before publication

The 10 archived Vensim runs and the additional native base diagnostics do not
export `Annual archetypes`, `Heating Solution` or `Cumulative archetype HH`.
They therefore cannot establish whether those native states are negative.
Python–Julia agreement alone is not evidence of native Vensim behavior.

Tracing the most negative final-weight scenario in the Python reference finds
its first stock value below -1e-6 in 2038. The affected coordinate is Lugano,
ElectricHeater, VeryLow, SFH, PVno, Bno. At 2037 the stock is 3.880072355 buildings,
with zero inflow and net outflow 4.461664451 buildings/year. Annual Euler produces
-0.581592096 in 2038. The previous outflow combines old-age replacement
3.866225796, demolition 0.587843719, renovation 0.068483297 and a negative PV
adoption flow -0.060888360. The full Euler identity closes within 4.55e-13.

A stock clamp alone would change population balances. A model correction must
address signed adoption flows and combined withdrawals, and apply each corrected
transfer consistently at its source and destination. Such a correction changes
the equations and requires a new numerical reference and regenerated dataset.
The user authorized this correction before release. The data release remains
a draft until the corrected model passes validation and full regeneration.

## Superseded provisional stock-flow correction

`benchmarks/sure-production/legacy_stock_limits.py` generated equivalent Python and Vensim equations
from the unchanged original sources. The corrected Vensim copy is translated
to Julia; there are no manual edits to generated Julia. The build identifies
the revision and checksums the correction source. The original adverse case,
including all 40 inputs, is in
`benchmarks/sure-production/vensim-negative-case.json` and is now a regression
scenario in the acceptance suite.

Demolition retains its original eligibility (VeryLow, PVno, Bno), but its
distribution uses the actual eligible source stock. Demolition and renovation
share the available demographic budget; demolition is additionally capped by
the eligible pool remaining after its proportional renovation withdrawals.
An empty or near-empty eligible pool therefore cannot suppress renovation of
other buildings. Heating replacement and PV adoption share the remainder
proportionally. Negative requested adoption transfers become zero; the sum of
accepted withdrawals cannot exceed the available source stock per time step.
The matching destination and cost equations use these same accepted flows.
Integrated states are never clamped. Historical net construction inputs, which
can be slightly negative, remain unchanged.

This is a model-policy change, not a numerical-equivalence fix for Vensim.
Python and Julia must agree on the corrected equations. Native Vensim behavior
has not been verified for this revision. Initial Python tests of base, high
and the adverse case pass nonnegativity and all transfer/population balances;
the three cross-engine cases subsequently passed. The wider run was interrupted
after 160 successful cases when the owner confirmed the original negative
stocks in native Vensim and supplied a corrected source. These experimental
equations are retained for investigation only and are not used by production.

## Current upstream v5

Commit `bf39813` supplies the updated `Vensim/SURE.mdl`, its translated
`SURE_pysd_v5.mdl`/`.py`, CSV inputs and calibrated constants. CSV contents and
calibration values match v4. Demolition is now distributed across every PV and
battery configuration within VeryLow buildings. Old-age heating replacement
is capped by the source stock remaining after demolition, renovation and PV
adoption. The annual levy also uses nonnegative net purchased electricity.

The production adapters consume these equations directly. The builder no longer
applies the provisional correction. All 40 scenario inputs remain explicit,
so changed defaults saved inside the source cannot silently change a run.
The profile is `sure-v5-bf39813`; older generated profiles are rejected.
The new source equations have synthetic regression tests and retain every
physical/numerical release gate. Prior v4 validation certificates and data
cannot certify this version; v5 requires its own full suite and regeneration.

The first v5 check on Elettra compares base, high and the original adverse
scenario. All 17,086,920 Python–Julia values pass the numerical tolerance,
but all three cases fail housing-stock nonnegativity in both engines.
Negative PV adoption inflows can still drive a positive stock below zero;
the first exact transition and all 40 inputs are recorded in
[`benchmarks/sure-production/V5_RESULTS.md`](../benchmarks/sure-production/V5_RESULTS.md).
Regeneration and release remain blocked. Failed arrays are saved for diagnosis
without weakening the physical gate. The v5 targeted translator suite passes;
neither the full v5 suite nor a replacement dataset is certified.
