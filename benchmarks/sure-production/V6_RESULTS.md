# SURE v6 production checks

Upstream source: `9080f62`; production translation: `e3d33ad`;
profile: `sure-v6-9080f62`. Runs use the pinned Python 3.11.8/PySD 3.14.3 and
Julia 1.10.12 environments on Elettra, annual Euler 2011–2050, Float64 and the
unchanged comparison tolerance.

## Targeted and initial checks

The targeted translator suite passes EXCEPT/indexing, external data, stateful
functions, semantic fixtures and allocation. Ten production contract tests
and nine source/physical regression tests pass. The new source wraps six
adoption functions in MAX; all 56 affected SUM expressions were proved
structurally identical to v5 before moving their audited reduction-policy
paths under the new wrapper. See `v6-reduction-remap-audit.json`.

Base, high and the original adverse case agree in Python and Julia on all
126 outputs and 17,086,920 values. Energy conservation, population/transfer
balances and warning classification pass. High and the adverse case pass
all physical checks; base fails stock nonnegativity.

For base, the minimum Heating Solution is `-0.0000026023519876082936` and the
minimum Annual archetypes is `-0.000005204703975216587`. There are 12 failed
cells in each output. These are small quantities but arise from a positive
withdrawal from an empty source stock, not floating-point cancellation.

## Exact first failure

At 2038, select
`Heating Solution[Mendrisio,ElectricHeater,VeryLow,DFH,PVno,Bno]`:

| Quantity | Value |
| --- | ---: |
| Heating Solution | 0 |
| Buildings adopting HS | 0 |
| Demolition, renovation and old-age outflows | 0 |
| Consumers adopting PV no | 0.0000012345669441641882 |

Annual Euler therefore gives `-0.0000012345669441641882` in 2039. The complete
40 inputs and the before/after flow balance are in
[v6-negative-stock-trace-20261014.json](v6-negative-stock-trace-20261014.json).

V6 implements the lower bound on adoption requests. It does not implement the
previously proposed common upper bound for the six requests against the
available `PVno,Bno` source stock after demolition and renovation. A common
factor must be applied to all six owner/renter adoption flows, preserving the
same accepted transfer at source and destination. The old-age limiter alone
cannot constrain a PV outflow when old-age withdrawal is already zero.

## Release status

The gated pipeline `/runs/regeneration-v6-002.sh` stopped after the base
failure. No v6 dataset has been generated or published. A separate full
diagnostic suite at `/runs/v6-diagnostic-full-001` completed all 318 cases:

- Python–Julia comparison: 318/318 pass, 1,811,213,520 values across 126 outputs.
- Energy conservation and warning classification: 318/318 pass in both engines.
- Housing/transfer acceptance: 169 pass, 149 fail. Stock nonnegativity fails in
  147 cases; all 149 failures include a negative demolition flow. All other
  physical balances pass.
- Minimum Heating Solution and Annual archetypes: `-0.00003465381053905168`,
  in `sample_min_12`, year 2050, at
  `Mendrisio,ElectricHeater,VeryLow,SFH,PVno,Bno` (Battery omitted for Annual
  archetypes). The first failure in this scenario also starts with a positive
  PV withdrawal from an exactly empty source category.
- Two independent fresh base processes give bit-for-bit identical arrays for
  each engine, including the residual negative stocks.

The complete case outcomes, all 40 inputs of the worst case and evidence hashes
are in [v6-full-results-20261014.json](v6-full-results-20261014.json).
The quantities are small; their demonstrated origin is an unbounded source
withdrawal. The acceptance thresholds have not been changed.

Native Linux AMD64 and ARM64 image builds and unit tests also completed in
[CI run 38476123989](https://github.com/supsi-dacd-isaac/SEneCa/actions/runs/38476123989).
Both numerical smoke jobs stopped on the same Python base physical failure,
before their Julia comparison or UI smoke could run. Therefore neither
architecture has passed the complete release check for v6.

No validation certificate was issued. State-isolation certification, pilots,
full data regeneration, publication and deployment remain pending until every
numerical and physical gate passes. Historical v4/v5 evidence does not certify
v6.

The compact evidence archive (646 reports/manifests, excluding large raw NPZs)
is retained at `/ssd2/elettra/seneca-runs/v6-verification-20261014.zip`, SHA256
`2f9643e9822478e5212b7b6c34359072aed8b55dd17459cc4bf3d63c6d9d4357`.
Raw arrays remain in the diagnostic run directory on Elettra. All workers have
finished; no regeneration job is waiting to restart automatically.
