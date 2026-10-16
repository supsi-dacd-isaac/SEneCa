# Dispatch candidate — 16 October 2026

The candidate derives from `7950c321a255a7af966dda1f72e387165bc99336`
(`sure-v7-pysd-translation`) and integrates the dispatch correction from
`11bdbcaf79339b34529c2a569af30578600cf795`. The authoritative source is `Vensim/SURE.mdl`.
Native verification is pending. This branch is not a release or app-runtime update.

## Changes and rationale

`Electricity dispatched` now uses `ALLOCATE BY PRIORITY`, with the original
negative marginal-cost priorities, supplier order and width 0.1. Vensim documents
this as the common-width rectangular counterpart of `ALLOCATE AVAILABLE`:
[allocation semantics](https://www.vensim.com/documentation/24337.html),
[function arguments and tie behavior](https://www.vensim.com/documentation/fn_allocate_by_priority.html).
The equivalence assumes the current profile type 1; changing the profile family
would require revisiting this equation. Ties share capacity proportionally and
nearby priorities retain overlapping rectangles; no supplier order is hardcoded.
The native solver's behavior must still be measured with the supplied fixture.

`Dispatchable supply by supplier` clips negative raw capacity to zero, making
the previous Python handling explicit in the native source. Two diagnostics
report dispatch balance (against demand capped by capacity) and unmet demand.
No residual import threshold is introduced. A capacity shortfall is reported,
not filled with fictitious production.

The v7 residential FER transition at 2022 is preserved. All three FER equations
regain their explanatory comments without changing their formulas. The five
updated v7 PV parameters are retained. A normalized equation audit found that
dispatch is the only existing equation changed relative to v7.
In particular, price-setting, smoothing, PHS, time step and calibration values
are unchanged. The separate questionable price-setting order remains outside
this correction; cross-engine agreement does not establish its economic validity.

## Translation and numerical checks

The `v7` Python model was regenerated locally using PySD 3.14.3 and the committed
CSV inputs/constants. `--skip-export --reuse-constants constants_ref_v7.pkl`
allows translation on macOS/Linux; binary Vensim export still requires Windows.
This reuses calibration values, it does not validate or recalibrate them.
The existing `*_pvbounded` files and Julia/app runtime have not been updated.

`HPinput.csv` is aligned by series label with the v7 exported data (482 data
cells updated, all 33 source series retained). Regenerating the v7 translation
now reproduces its committed input CSVs. The native Vensim package must include
the matching updated `HPinput.vdfx`; the raw CSV is not a VDFX replacement.
The 31 calibration constants are unchanged from the colleague's v7 commit.

An edge-case test exposed a PySD 3.14.3 empty-active-set error within a few
Float64 ULPs of full capacity. The translation guard snaps supply to total
capacity only within four ULPs. It does not suppress small positive imports.
The independent test oracle inverts rectangular-profile linear segments.

Validation comprises 179 recorded vectors plus ten edge cases (ties, overlap,
cheap import, tiny import, negative hydro, surplus, zero demand/capacity and
shortfall), the six FER tests, HP input alignment, and full base/high runs from 2011 through 2050.
Full runs use the app's synchronous fixed-delay policy, including PHS feedback.
The fixture also duplicates the Month dimension to check broadcasting.
PySD rounds embedded lookup coordinates to eight decimals: fixture comparison
allows 1e-7; separate unrounded replay checks 1e-11. Native DLL export allows
2e-6 for the fixture and physical balance. Full native/Python comparison is
pointwise 0.1%, plus `max(1e-6, 1e-6 * variable scale)` absolute tolerance.
NaNs, missing years/outputs, rejected controls and incomplete runs fail.

Only native base/high confirmation can establish that the original Vensim
dispatch defect and its PHS amplification have been removed. Calibration
review comes after that; release generation remains blocked on both steps.

## Why earlier translations could appear acceptable

The archived [v2 report](https://github.com/supsi-dacd-isaac/SEneCa/blob/v0.3.1/coherence_report_v2.csv)
already records 1,445 pointwise dispatch failures in the base case while marking
the variable `practical=True`: its aggregate error was 1.52%, below the 5%
aggregate threshold. The v6 base similarly had 1,007 pointwise failures and
`practical=True`. This explains how hourly discrepancies could pass the older
practical gate. It does not establish that every historical discrepancy had
the same allocation cause. The [v4 audit](https://github.com/supsi-dacd-isaac/SEneCa/blob/v0.3.1/benchmarks/sure-v4/RESULTS.md)
explicitly distinguishes Python–Julia agreement from unproven Vensim equivalence.
The new check never lets an annual aggregate waive an hourly failure.
