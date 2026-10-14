# Policy mix: 100 samples and nine indicators

The Elettra run `policy-mix-100-002` completed on 2026-10-14 at 17:06 CEST.
Generation and final audit exited successfully. Generation source commit:
`bef0f55717d0da0b9662fe20b776bc6b707dfad6`.

## Dataset and model identity

- 128 policy mixes × 100 uncertainty samples = **12,800 exploratory results**.
- All application sections: 14,579 configurations, **14,571 distinct simulations**.
- Nine indicators, including PV self-consumption divided by total district
  electricity demand at 2050. The denominator is converted from kWh to GWh;
  the ratio and both source energies are stored as Float64.
- The workbook defines seven binary policy choices and **17** uncertain
  parameters. The 100 Latin hypercube draws use seed `20261004`, uniform
  marginals and the same draws for all policy mixes. This design replaces
  the preceding 50 draws rather than appending another 50.
- Equations, calibration, input data and exported coordinates match
  `data-v1.1.0`: model revision `sure-v6-pv-budget-2`, Julia 1.10.12,
  Float64, annual Euler and outputs for 2011–2050.
- All seven non-exploratory application Parquets and all seven historical
  Vensim binaries are **byte-identical** to `data-v1.1.0`. Only the exploratory
  stores and generation provenance change.

Workbook SHA-256:
`140a4dcf12bb9e25798bdc559d9ea275f583cfe9d7c1ed8f95981dd8938cf410`.
100-sample Parquet SHA-256:
`d27dcf0c7e8d60b619f5a566ad6ea955eeba296344cc9f35b4f159519f543677`.

## Validation

All **418** Python–Julia cases passed, comparing 137 application and diagnostic
outputs per case: **2,623,551,920 values**, zero failed cells. All derived KPI
comparisons, targeted translator tests, physical checks and state-isolation
checks passed. The acceptance tolerance remained
`abs(Julia-Python) <= 1e-10*max(1,S) + 1e-8*abs(Python)`, with S the largest
absolute Python value over time for each labelled series. Labels, years and
discrete values are exact.

The largest absolute difference was `2.384185791015625e-7` kWh in
`Total annual demand Districts`, within the unchanged elementwise tolerance.
The 100 pilot scenarios produced exactly identical numerical output hashes
and Parquet files in serial and parallel execution.

The full audit verifies all 14,571 scenarios, all 40 effective input values,
complete configuration coverage, Float64/finite values, physical invariants,
provenance hashes and zero compilation after worker warm-up. There are no
substantive negative GMD weights. In 4,886 scenarios the recorded GMD roundoff
exclusions include values as small as `-1.616484723854228e-14`; raw simulation
arrays remain unchanged.

Full equivalence with native Vensim is not certified. These are the
Python–Julia and physical acceptance results for the unchanged corrected model.

## Elettra measurements

32 persistent processes, one Julia/BLAS/OpenMP thread each, CPUs 0–31 and
a 128 GiB memory limit:

| Measurement | Result |
| --- | ---: |
| 100-case serial pilot, including warm-up | 1,282.94 s |
| 100-case parallel pilot, including warm-up | 202.41 s |
| Full generation including consolidation | 7,698.56 s (2 h 8 min 19 s) |
| Mean scenario time under parallel load | 16.41 s |
| Median scenario time under parallel load | 16.21 s |
| Scenario range under parallel load | 13.24–26.06 s |
| Sampled peak container memory | 38,889,246,720 bytes (36.22 GiB) |
| Compilation after warm-up | 0 s |

These batch timings are not measurements of a single-user web request.
The shared worker startup and progress UI checks are recorded separately in
[STARTUP_WARMUP.md](STARTUP_WARMUP.md). Native AMD64 and ARM64 image checks
remain mandatory release gates, including Python–Julia comparisons, all nine
indicators, the first UI request after warm-up and optional progress events.

## Reproduction and release evidence

Follow [the 100-sample procedure](../../docs/policy-mix-100.md).
Raw Elettra evidence is under
`/ssd2/elettra/seneca-runs/policy-mix-100-002`.
The `data-v1.2.0` assets include `policy-mix-100-validation.zip` with the full
case reports, warning classifications, certificate, state isolation, targeted
tests, sample specification, pilot comparison, generation manifest and audit.
The data archive includes complete scenario and model provenance.

Data archive SHA-256:
`0d7ed2351236a7174c8f55708a1c210986a239b2bb53bb7011e27438c3b29b8f`.
Validation archive SHA-256:
`f9064f09f481a9094cf836d1e3614de783c03937773835aa467f81df96f4eac7`.
