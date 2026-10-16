# Dispatch candidate — 16 October 2026

The candidate derives from `c8a7cd8e26e39ee1e423699620f3f587b63f5413`
(`sure-v6-published-translation`). The authoritative source is `Vensim/SURE.mdl`.
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

The already-approved residential FER transition is restored to 2022. The other
two FER equations regain their explanatory comments without changing their
formulas. A normalized equation audit found no other existing equation changes.
In particular, price-setting, smoothing, PHS, time step and calibration values
are unchanged. The separate questionable price-setting order remains outside
this correction; cross-engine agreement does not establish its economic validity.

## Translation and numerical checks

The `v6` Python model was regenerated locally using PySD 3.14.3 and the committed
CSV inputs/constants. `--skip-export --reuse-constants constants_ref_v6.pkl`
allows translation on macOS/Linux; binary Vensim export still requires Windows.
This reuses calibration values, it does not validate or recalibrate them.
The existing `*_pvbounded` files and Julia/app runtime have not been updated.

An edge-case test exposed a PySD 3.14.3 empty-active-set error within a few
Float64 ULPs of full capacity. The translation guard snaps supply to total
capacity only within four ULPs. It does not suppress small positive imports.
The independent test oracle inverts rectangular-profile linear segments.

Validation comprises 179 recorded vectors plus ten edge cases (ties, overlap,
cheap import, tiny import, negative hydro, surplus, zero demand/capacity and
shortfall), the six FER tests, and full base/high runs from 2011 through 2050.
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
