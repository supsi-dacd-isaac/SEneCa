# Diagnosi numerica del dispatch — 16 ottobre 2026

La calibrazione ricevuta è completa: cinque OUT, 56 assegnazioni. Le 54
assegnazioni già presenti coincidono dopo conversione Float32 con il pickle
v7; le altre due sono pesi nulli già a zero nel modello. Per la nuova release
si conservano direttamente i decimali degli OUT in Float64 (33 gruppi).

Con gli stessi input CSV in entrambi i motori, il confronto nativo originale
passa per la baseline ma conserva 24 celle fuori tolleranza nel caso alto:
massimo 160,832 kWh nel dispatch e 124,612 kWh nel pompaggio. Arrotondare
separatamente dati e parametri a Float32 non elimina questi residui.

In una copia diagnostica, le allocazioni sono espresse come minimo tra capacità
e domanda rimasta dopo i fornitori meno costosi. La distanza minima tra le
priorità meno la larghezza è 0,4 in tutti gli anni: i rettangoli non si
sovrappongono, quindi la formula è equivalente nei due casi verificati.
Il modello diagnostico mantiene in parallelo l’allocatore nativo originale:
il suo errore locale massimo è 0,634 kWh. Il circuito di importazioni filtrate
e pompaggio stagionale amplifica questi errori durante l’integrazione.

Con la formula diagnostica, tutti i 12 gruppi di output passano in baseline
e nel caso alto, senza modificare le soglie. Gli scarti massimi sono
0,675 kWh nel dispatch e 1,123 kWh nel pompaggio. La conclusione riguarda
questi due scenari e non certifica l’equivalenza nativa per ogni configurazione.
Il modello distribuito mantiene `ALLOCATE BY PRIORITY`: la formula diagnostica
non entra nel runtime. La validazione Python–Julia resta integrale e stretta.

Evidenza: `dispatch-precision-20261016.json`. Gli esperimenti completi sono
in `dist/dispatch-precision-20261016/`; il pacchetto ricevuto ha SHA256
`482a6135aa31b76725b65d3423ffc239c051ab362a88387a63b66b5d297bcbdd`.
HPinput.csv e il VDFX dello ZIP differiscono in 482 celle: per questa release
il CSV corrente, coerente con la traduzione v7, è la sorgente autorevole.

## Nota originaria del candidato (stato precedente alla diagnosi)

# Dispatch candidate — 16 October 2026

The candidate derives from `7950c321a255a7af966dda1f72e387165bc99336`
(`sure-v7-pysd-translation`) and integrates the dispatch correction from
`11bdbcaf79339b34529c2a569af30578600cf795`. The authoritative source is `Vensim/SURE.mdl`.
The following sections record the original candidate investigation; current status is above.

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
