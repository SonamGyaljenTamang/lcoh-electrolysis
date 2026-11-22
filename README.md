# lcoh-electrolysis

Levelised cost of hydrogen (LCOH) for **PEM vs alkaline** water electrolysis:
a discounted cash-flow model with stack degradation and replacement, an
optional hourly dispatch that respects each technology's minimum load,
sensitivity (tornado) analysis, sweeps and a PEM break-even CAPEX.

## Quick start

```bash
pip install -e ".[dev]"          # numpy, matplotlib, pytest; Python >= 3.11
python -m lcoh                    # defaults: 10 MW, 55 % CF, 60 USD/MWh
python -m lcoh --config config/example.toml --plots out/ --json out/results.json
python -m lcoh --profile hybrid --plots out/            # synthetic PV+wind
python -m lcoh --availability-csv re.csv:pu --price-csv da.csv:price --price-cap 120
python -m lcoh --set project.wacc=0.05 --set pem.capex_per_kw=1800
pytest
```

As a library:

```python
from lcoh import ALKALINE, PEM, ProjectParams, compute_lcoh
proj = ProjectParams(electricity_price_per_mwh=45, capacity_factor=0.6)
for tech in (ALKALINE, PEM.with_(capex_per_kw=1900)):
    print(compute_lcoh(tech, proj).summary())
```

## Method

LCOH = Σ C_t (1+r)^-t / Σ M_t (1+r)^-t, with C_t the costs in year t (CAPEX at t = 0,
then electricity, fixed O&M, water, stack replacements) and M_t the kg of H₂ produced.
The per-component breakdown uses the same denominator, so it adds up to the LCOH.

* **Operation.** *Simple mode*: rated power × capacity factor at a flat price.
  *Hourly mode*: an availability profile (fraction of rated power the source can
  deliver) and/or an hourly price. The electrolyser follows the available power,
  turns off below `min_load` (default 20 % for alkaline vs 5 % for PEM) and,
  optionally, above a price cap. One year is repeated for the whole lifetime.
* **Degradation.** Electrical input is fixed, so degradation lowers output:
  SEC(h) = SEC_BoL·(1 + d·h/1000), where h is the hours on the current stack.
* **Stacks.** A stack is replaced when it reaches `stack_lifetime_h`. If less than 25 % of a stack life remains
  in the project, the replacement is skipped (`skip_replacement_if_remaining_frac`).
  `stack_wear_basis` sets what counts toward stack life:
  `"operating"` = every hour with load > 0 (conservative, and it penalises PEM's long
  part-load operation); `"full_load"` = full-load-equivalent hours.

## Default parameters (installed, non-Chinese, MW-scale, USD)

| | Alkaline | PEM | Basis |
|---|---|---|---|
| System CAPEX incl. EPC [USD/kW] | 2 000 | 2 300 | IEA GHR 2025: 1 900–2 600 outside China |
| SEC, system, BoL [kWh/kg] | 54.6 | 55.1 | BNEF 2026 Western benchmarks |
| Degradation [%/1000 h] | 0.15 | 0.35 | midpoints of 0.1–0.25 / 0.2–0.5 (OEM claims) |
| Stack lifetime [h] | 80 000 | 60 000 | literature; PEM quotes recently ~8 yr |
| Stack replacement [USD/kW] | 400 | 500 | ~340 / 420 EUR/kW in literature, rounded up |
| Minimum load [-] | 0.20 | 0.05 | NREL 2019: 20–40 % vs 3–10 % |
| Fixed O&M [-/yr of CAPEX] | 0.025 | 0.025 | typical 2–3 % |
| Project | 10 MW, 25 yr, WACC 7 %, 60 USD/MWh, CF 55 % | | |

For Chinese-made systems installed in China, use roughly 500–1 200 USD/kW (IEA).
For EUR figures, set `currency = "EUR"` and enter all inputs in EUR.

## Limitations

* SEC does not depend on load: there is no part-load efficiency curve and no
  standby or cycling losses. Both matter for highly variable operation.
* Compression, storage, grid fees, taxes, subsidies and residual value are not
  included. Electricity in hourly mode is priced per hour, so for a direct
  renewables supply set a flat price equal to the renewables LCOE.
* The synthetic PV/wind/price profiles (`lcoh/profiles.py`) are only for
  demonstration. For real studies use measured data (renewables.ninja, PVGIS,
  ENTSO-E day-ahead prices).

## Layout

```
lcoh/params.py       TechParams, ProjectParams, ALKALINE/PEM defaults
lcoh/model.py        dispatch_year, compute_lcoh, compare
lcoh/sensitivity.py  tornado, sweep, breakeven_capex
lcoh/profiles.py     CSV loader + synthetic solar/wind/price
lcoh/plots.py        breakdown bar, sweeps, tornado
lcoh/cli.py          command line (python -m lcoh)
config/example.toml  scenario template
tests/               closed-form and behaviour tests
```
