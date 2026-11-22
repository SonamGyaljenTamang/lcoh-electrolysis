"""Technology and project parameters for the LCOH model.

All monetary values are in one currency of your choice (defaults are USD, 2024/25).
Defaults describe an installed, non-Chinese (Europe/North America) MW-scale system
and are meant as a sensible starting point, not as vendor quotes. Replace them with
your own data wherever you have it.

Default sources (see README for links):
  * IEA Global Hydrogen Review 2025 / IEA commentary 2026: installed electrolyser
    CAPEX outside China ~USD 1 900-2 600 /kW; China ~USD 500-1 200 /kW.
  * BNEF 2026 via John Cockerill: Western system SEC ~54.6 kWh/kg (ALK) vs
    ~55.1 kWh/kg (PEM); degradation ~0.1-0.25 %/1000 h (ALK) vs ~0.2-0.5 %/1000 h
    (PEM); PEM stack lifetimes quoted at just under ~8 years.
  * NREL (2019) manufacturing-cost study: minimum load 20-40 % (ALK) vs 3-10 % (PEM).
  * Stack replacement cost ~340 EUR/kW (ALK) and ~420 EUR/kW (PEM), literature values.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace, asdict


@dataclass(frozen=True)
class TechParams:
    """Electrolyser technology parameters (per kW of rated electrical input)."""

    name: str
    capex_per_kw: float          # installed system CAPEX incl. EPC [cur/kW]
    sec_kwh_per_kg: float        # system specific energy consumption at BoL [kWh/kg H2]
    degradation_pct_per_1000h: float  # SEC increase per 1000 operating hours [%]
    stack_lifetime_h: float      # operating hours until stack replacement [h]
    stack_replacement_per_kw: float   # stack replacement cost [cur/kW]
    min_load: float              # minimum stable load as fraction of rated power [-]
    fixed_om_frac: float = 0.025  # fixed O&M per year as fraction of CAPEX [-/yr]
    water_l_per_kg: float = 15.0  # process + cooling water demand [L/kg H2]

    def with_(self, **changes) -> "TechParams":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProjectParams:
    """Project / financial parameters shared by both technologies."""

    rated_power_mw: float = 10.0
    lifetime_years: int = 25
    wacc: float = 0.07                   # real discount rate [-]
    electricity_price_per_mwh: float = 60.0  # used when no hourly price profile is given
    capacity_factor: float = 0.55        # used when no hourly availability profile is given
    water_price_per_m3: float = 2.0
    # Skip a stack replacement if less than this fraction of a stack life remains.
    skip_replacement_if_remaining_frac: float = 0.25
    # What counts toward stack life and degradation in hourly mode:
    # "operating" = every hour with load > 0 (conservative, penalises part load),
    # "full_load" = full-load-equivalent hours (energy / rated power).
    stack_wear_basis: str = "operating"
    currency: str = "USD"

    def with_(self, **changes) -> "ProjectParams":
        return replace(self, **changes)

    def to_dict(self) -> dict:
        return asdict(self)


ALKALINE = TechParams(
    name="Alkaline",
    capex_per_kw=2000.0,
    sec_kwh_per_kg=54.6,
    degradation_pct_per_1000h=0.15,
    stack_lifetime_h=80_000,
    stack_replacement_per_kw=400.0,
    min_load=0.20,
)

PEM = TechParams(
    name="PEM",
    capex_per_kw=2300.0,
    sec_kwh_per_kg=55.1,
    degradation_pct_per_1000h=0.35,
    stack_lifetime_h=60_000,
    stack_replacement_per_kw=500.0,
    min_load=0.05,
)

DEFAULT_TECHS: dict[str, TechParams] = {"alkaline": ALKALINE, "pem": PEM}
