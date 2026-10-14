# SURE v4 — isolated alignment and verification

This experiment targets the v4 and ten native Vensim runs in main commit
`17db1f4245c6bb0e8ef41a4cac5e8d3a6817cac6`. It leaves the current app, its
environment, the v3 model and the certified v3 experiment unchanged.

See [RESULTS.md](RESULTS.md) for the measured outcome and
[results-summary.json](results-summary.json) for compact numerical evidence.

## Reproduce

The inherited numerical compatibility layer targets **macOS arm64** and
Python **3.11.8**. Use the existing isolated runtimes or prepare them with:

```sh
.venv/bin/python scripts/setup_julia_repro.py
```

This installs only below `dist/julia-repro/runtime`. PySD Python 3.14.3 and its
dependencies use `benchmarks/julia-repro/python-reference.lock`. Julia 1.10.12,
the translator at `8991d119e139029d4dec712d257cf5fcc3549b8f` and PySD.jl at
`abe4251fe91734f83776a9c782088d3a2f09dc57` use the existing pins and Julia
`Project.toml`/`Manifest.toml` in `benchmarks/julia-repro`.

Ensure the pinned main revision is available locally (`git fetch origin` if
needed), then choose a **new** output directory:

```sh
dist/julia-repro/runtime/python-reference/bin/python -B \
  scripts/verify_sure_v4.py all --run-dir dist/sure-v4/my-run
```

The runner fixes `PYTHONHASHSEED=0` and single-thread settings before starting
workers. Each reference worker explicitly selects v4. Individual phases are
`prepare`, `reference`, `fixtures`, `translate`, `run`, and `validate`. Result
workers refuse to overwrite earlier simulations; restart with a new directory
after any semantic change.

`validate` writes full comparisons, `summary.json`, `REPORT.md`, and checksums
in `evidence.json`. Successful command execution means the comparison finished;
check `alignment_pass`, `native_reconstructed_pass` and `pass` in
`validation.json` for acceptance. Native disagreement is an outcome, not an
exception silently converted into success.

The bulk artifacts remain outside Git in `dist/sure-v4/<run-id>`: pinned source
and input data, scenario metadata, applied calibration, native raw and explicitly
reconstructed snapshots, Python and Julia snapshots, every warning, state-order
audits, per-variable errors, raw Julia arrays and runtime timings.

## What is translated

The runner extracts the actual v4 MDL, generated Python, calibrated constants,
six external CSVs, app harness, output configurations and native run archive
from the pinned Git revision. It retranslates the **original-dimensional MDL**
with the experimental six-dimensional EXCEPT, stateful, external-data and
numerical compatibility patches. No existing v3 model artifact is needed.

`inherited-policy.json` preserves the previously audited reduction layouts and
environment inventory. They are hypotheses until the v4 comparison passes.
The v3-specific HS normalizations are disabled; the v4 equations are emitted.
The delay audit independently confirms the sequential update policy in both
v4 Python paths without changing their outputs.

The new allocator follows the v4 Python wrapper. It uses the priority algorithm
for common-width rectangular profiles and the inherited rectangular solver
otherwise. The implementation deliberately rejects unverified profile ranks
and more than fifteen nonzero suppliers; SURE has nine suppliers. Other profile
types remain unsupported in the inherited fallback. Extending to other models
requires extending the fixtures, not suppressing these guards.

Twenty runtime parameters share one immutable type. The Julia worker loads one
module for all ten scenarios and recreates initial states, caches and delays
for each run. It checks that the input initial state is preserved. A repeated
base after all other scenarios and a second fresh process test state isolation.

## Acceptance and native archive handling

Python–Julia compares all 110 variables, labels, coordinates and annual values,
including all 52 app outputs, all 60 native outputs and the inherited detailed
diagnostics. Nothing is sampled. The app and diagnostic Python runs are compared
separately. The approved tolerance remains
`1e-10 * max(1, S) + 1e-8 * abs(Python)`, where S is the maximum absolute value of
that individual coordinate series over time. Discrete values are exact.

Native comparisons add only the half-ULP bound of the declared Float32 export.
The reported one-percent diagnostic is **not** an acceptance criterion.

The raw Vensim archive has 288 Import export series per run with only a zero in
2011. Raw comparison marks these as incomplete. A separate snapshot reconstructs
the other 39 zeros only after verifying the exact missing-cell pattern and
`Hourly exported electricity[Month,Hour,Import] = 0` in the source MDL. The raw
archive is never edited; reconstructed cells are not independent native evidence.

The supplied VPMX hash differs from the local data release. All twenty app
parameters are explicit, but three additional lever defaults and native engine
settings are not fully specified. These limitations remain in the report.

## Focused checks

```sh
dist/julia-repro/runtime/python-reference/bin/python -B -m unittest discover -s tests -p 'test_sure_v4.py'
dist/julia-repro/runtime/python-reference/bin/python -B -m unittest discover -s tests -p 'test_vensim*.py'
dist/julia-repro/runtime/python-reference/bin/python -B -m unittest discover -s tests -p 'test_parametric_sure.py'
```

The runner also performs 314 Julia assertions over 104 Python-derived allocation
fixtures, including ties, negative requests, shortages, saturation, zero supply,
unequal-width fallback, and batched month/hour requests.

Timings captured during verification are diagnostic. This experiment does not
claim a new controlled performance benchmark or persistent web-service latency.
