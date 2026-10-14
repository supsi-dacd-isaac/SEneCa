# Shared live worker warm-up

On 2026-10-14 the startup change was tested on Linux AMD64 on Elettra,
using the released v0.2.0 numerical model with the new `server.py`,
`sure_live.py` and live page from `policy-mix-100`. The numerical model and
pinned dependencies were unchanged.

The test used one logical CPU (32), while the full Python–Julia validation
occupied CPUs 0–31. These timings describe that concurrent load, not an idle
production server:

| Phase | Seconds |
| --- | ---: |
| Complete initial warm-up, including model load | 189.30 |
| Compilation inside the initial request | 122.56 |
| Subsequent base request, Julia execution/extraction | 19.52 |
| Subsequent high request, Julia execution/extraction | 18.82 |
| First UI request, including rendering in AppTest | 23.32 |

Every request after warm-up recorded exactly zero compilation time. The UI
used the same engine object, process PID and Julia module. Base → high → base
produced exactly equal labelled frames, and all 40 annual rows were finite.

A separate actual Streamlit server was then started through `server.py`.
Without any browser session, it warmed Julia in 192.08 seconds and only then
answered `/_stcore/health`. A browser opened the live page and submitted its
first simulation successfully; the process PID was unchanged. The temporary
server was stopped after the check.

The four unit tests cover concurrent resource creation, cache cleanup,
failed warm-up/retry, Python selection and real ASGI startup before health.
Release CI also repeats the numerical startup-to-UI check on AMD64 and ARM64
and requires a successful warm-up log before accepting server readiness.
Those final release checks remain required when the new data pin is ready.

Full local evidence: `dist/policy-mix-100-20261014/startup-check/`.
Elettra evidence: `/ssd2/elettra/seneca-runs/startup-check-20261014/`.
