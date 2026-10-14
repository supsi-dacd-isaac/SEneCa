# SURE v5: residual negative housing stocks

Source: upstream `bf39813`, production adapter `294771f`, profile
`sure-v5-bf39813`. Run on Elettra: `/ssd2/elettra/seneca-runs/v5-diagnostic-001`.
These results concern the supplied v5 equations, without the provisional v4
stock-flow correction. No native Vensim execution was performed for this v5
diagnostic.

## Result

Python and Julia agree within the unchanged tolerance on all 126 outputs and
5,695,640 values per scenario (17,086,920 values across base, high and the
original adverse case). Energy conservation, paired transfers, Euler
integration, population balances and warning classification pass. Housing
stock/transfer nonnegativity fails in both engines in all three cases.
Therefore these cases fail acceptance; data regeneration and release remain
blocked. Numerical agreement does not certify physical validity.

| Scenario | Minimum Heating Solution | Minimum Annual archetypes |
| --- | ---: | ---: |
| base | -0.0016747880895084943 | -0.00378490763087826 |
| high | -0.019439192189022347 | -0.043714565939452464 |
| regression_negative_stock | -0.00782258298378391 | -0.11963555494971043 |

The complete 40 inputs, coordinate labels, minima and first failed stock
transitions are in [v5-negative-stock-trace-20261013.json](v5-negative-stock-trace-20261013.json).
Build/source hashes and hashes of every raw output/report are in
[v5-diagnostic-evidence-20261013.json](v5-diagnostic-evidence-20261013.json).

## Smallest clear reproduction: base, 2038 to 2039

Select `Heating Solution[Bellinzona,ElectricHeater,VeryLow,SFH,PVyes,Byes]`.
With annual Euler integration, its 2038 quantities are:

| Quantity | Value |
| --- | ---: |
| Heating Solution | 0.09752152220490995 |
| Consumers leaving HS for old age | 0.09478171099710651 |
| Building demolition by archetype | 0.0011579668744821712 |
| Buildings HS Renovation From | 0.001581844333321255 |
| Consumers adopting PV no | 0 |
| Total Buildings leaving HS | 0.09752152220490995 |
| Consumers adopting PV yes with battery | -0.000451305578995047 |
| Other incoming flows | 0 |

The outgoing flows consume exactly the available stock. The negative PV
adoption inflow then makes the 2039 stock `-0.0004513055789950454`:

```text
stock_next = 0.09752152220490995
             - 0.000451305578995047
             - 0.09752152220490995
```

The v5 old-age limiter reserves positive outgoing flows but does not account
for a negative incoming adoption flow. In the next year the negative stock
also produces negative demolition, renovation and old-age flows. This is an
equation-level effect already present in the Python reference.

## A second independent transition: high, 2028 to 2029

For `Heating Solution[Leventina,HeatPump,VeryHigh,MFH,PVyes,Byes]`, the 2028 stock
is `0.05067493139110331`. Positive inflows sum to `0.0069121060506509795`.
PV and RCPv inflows are respectively `-0.05979720790983606` and
`-0.01691417714911566`; the old-age outflow is `0.00031484457182492096`.
The 2029 stock becomes `-0.019439192189022347`. Merely reducing the old-age
outflow cannot prevent this negative state: the net inflow itself removes
more stock than is available.

Negative adoption flows already occur in 2011 in all three scenarios at
`Leventina,HeatPump,VeryHigh,MFH,PVyes,Bno`: PV inflow
`-0.00002987936331379461`. Their magnitudes are not always small: high contains
`Consumers adopting PV no = -90.04175327553472` in 2028 at
`Lugano,HeatPump,Low,SFH,PVno,Bno`. This last number is a flow, not a negative
housing stock.

## Source correction to investigate

Inspect the potential-minus-existing-adopters expressions in all six
`Owners/Renters adopting PV/RCP/RCPv` equations. They can request a negative
adoption transfer even when the housing stocks are still positive. Decide
whether the model intends unidirectional adoption or explicit disadoption.
For unidirectional adoption, bound the requested flow at its origin and apply
the accepted flow consistently to both source and destination, including
the ownership/community stocks and dependent costs. If disadoption is intended,
represent and limit that reverse transfer against its actual source pool.

In either case, check the combined per-step withdrawals from each source
category; correcting just one destination or clamping the integrated stock
would conceal the cause and break conservation. This diagnostic does not
claim that changing the six adoption equations alone fixes every scenario.

## Reproduction and acceptance after the source update

Use the recorded explicit parameters rather than the defaults saved in the
model. Apply `constants_ref_v5.pkl` (SHA256
`565e862dc8d78f8d7a44d43e31e5fd7699d64924be680c13d13fdedcb3dc0e55`), annual Euler,
2011–2050, and the supplied CSV inputs. Inspect every heating/PV/battery cell,
not only aggregate weights. Fixed controls remain ICE ban year 2050,
Deflussi minimi LPAc 1 and Cambiamento climatico Hydro 1.

Inside the pinned Elettra environment, after rebuilding the model:

```sh
python -m sure_julia.validation /runs/v5-diagnostic-new --workers 3 \
  --cases base high regression_negative_stock
```

`PhysicalInvariantError` preserves failed numerical arrays only for diagnosis;
it still fails application/batch requests and acceptance. Passing these three
cases is necessary but does not replace the 318-case suite, state-isolation
checks, serial/parallel pilot and full regeneration on the corrected source.
