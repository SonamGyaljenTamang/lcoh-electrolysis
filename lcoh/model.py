"""Discounted cash-flow LCOH model.

    LCOH = sum_t C_t / (1+r)^t  /  sum_t M_t / (1+r)^t

C_t: all costs in year t (CAPEX at t=0, then electricity, fixed O&M, water,
stack replacements); M_t: kg of H2 produced in year t.

Operation
---------
Two modes:
  * Simple: constant capacity factor, electrolyser runs at rated power.
  * Hourly: an 8760-h availability profile (fraction of rated power the power
    source can deliver) and/or an hourly price profile. The electrolyser follows
    the available power, but shuts down below its minimum load (this is where
    PEM's wider operating window matters) and, optionally, when the price is
    above a cap. The same year is repeated over the project lifetime.

Degradation
-----------
Electrical input is fixed by the power source, so degradation shows up as lower
H2 output: SEC(h) = SEC_BoL * (1 + d/100 * h/1000), with h the operating hours
on the current stack. Stacks are replaced once their lifetime is reached, which
resets h. Part-load efficiency effects are not modelled (SEC is load-independent).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .params import ProjectParams, TechParams

HOURS_PER_YEAR = 8760


@dataclass
class Dispatch:
    """One year of operation (repeated every year)."""

    energy_mwh: float          # electricity drawn by the electrolyser
    operating_hours: float     # hours with load > 0 (drives stack wear)
    electricity_cost: float    # cost of that electricity
    full_load_hours: float     # energy / rated power

    @property
    def capacity_factor(self) -> float:
        return self.full_load_hours / HOURS_PER_YEAR


@dataclass
class LCOHResult:
    tech: str
    lcoh: float                         # [cur/kg]
    breakdown: dict[str, float]         # [cur/kg] per component, sums to lcoh
    annual_h2_t: np.ndarray             # tonnes H2 per year (years 1..N)
    stack_replacement_years: list[int]
    dispatch: Dispatch
    currency: str = "USD"
    cashflows: dict[str, np.ndarray] = field(repr=False, default_factory=dict)

    @property
    def avg_h2_t_per_year(self) -> float:
        return float(self.annual_h2_t.mean())

    def summary(self) -> str:
        cur = self.currency
        lines = [
            f"{self.tech}: LCOH = {self.lcoh:.2f} {cur}/kg",
            f"  full-load hours {self.dispatch.full_load_hours:,.0f} h/yr "
            f"(CF {self.dispatch.capacity_factor:.1%}), "
            f"operating hours {self.dispatch.operating_hours:,.0f} h/yr",
            f"  avg production {self.avg_h2_t_per_year:,.1f} t H2/yr, "
            f"stack replacements in years {self.stack_replacement_years or 'none'}",
        ]
        for k, v in self.breakdown.items():
            lines.append(f"    {k:<20s} {v:6.2f} {cur}/kg  ({v / self.lcoh:5.1%})")
        return "\n".join(lines)


def dispatch_year(
    tech: TechParams,
    project: ProjectParams,
    availability: np.ndarray | None = None,
    price_per_mwh: np.ndarray | None = None,
    price_cap_per_mwh: float | None = None,
) -> Dispatch:
    """Compute one year of electrolyser operation."""
    p_mw = project.rated_power_mw

    if availability is None and price_per_mwh is None:
        flh = project.capacity_factor * HOURS_PER_YEAR
        energy = p_mw * flh
        return Dispatch(
            energy_mwh=energy,
            operating_hours=flh,
            electricity_cost=energy * project.electricity_price_per_mwh,
            full_load_hours=flh,
        )

    n = len(availability) if availability is not None else len(price_per_mwh)
    if availability is None:
        availability = np.ones(n)
    if price_per_mwh is None:
        price_per_mwh = np.full(n, project.electricity_price_per_mwh)
    availability = np.asarray(availability, dtype=float)
    price_per_mwh = np.asarray(price_per_mwh, dtype=float)
    if availability.shape != price_per_mwh.shape:
        raise ValueError("availability and price profiles must have the same length")

    load = np.clip(availability, 0.0, 1.0)
    load[load < tech.min_load] = 0.0
    if price_cap_per_mwh is not None:
        load[price_per_mwh > price_cap_per_mwh] = 0.0

    # Scale a non-8760 profile to a full year.
    scale = HOURS_PER_YEAR / n
    energy = float(load.sum()) * p_mw * scale
    return Dispatch(
        energy_mwh=energy,
        operating_hours=float((load > 0).sum()) * scale,
        electricity_cost=float((load * price_per_mwh).sum()) * p_mw * scale,
        full_load_hours=energy / p_mw,
    )


def compute_lcoh(
    tech: TechParams,
    project: ProjectParams,
    availability: np.ndarray | None = None,
    price_per_mwh: np.ndarray | None = None,
    price_cap_per_mwh: float | None = None,
) -> LCOHResult:
    """Levelised cost of hydrogen for one technology."""
    d = dispatch_year(tech, project, availability, price_per_mwh, price_cap_per_mwh)
    n_years = project.lifetime_years
    p_kw = project.rated_power_mw * 1000.0

    capex = tech.capex_per_kw * p_kw
    years = np.arange(n_years + 1)
    disc = (1.0 + project.wacc) ** -years

    cf = {k: np.zeros(n_years + 1) for k in
          ("CAPEX", "Electricity", "Fixed O&M", "Stack replacement", "Water")}
    h2_kg = np.zeros(n_years + 1)
    cf["CAPEX"][0] = capex

    stack_hours = 0.0
    replacements: list[int] = []
    deg = tech.degradation_pct_per_1000h / 100.0 / 1000.0  # per hour
    if project.stack_wear_basis == "operating":
        hours_per_year = d.operating_hours
    elif project.stack_wear_basis == "full_load":
        hours_per_year = d.full_load_hours
    else:
        raise ValueError("stack_wear_basis must be 'operating' or 'full_load'")
    energy_kwh_per_op_hour = (d.energy_mwh * 1000.0 / hours_per_year) if hours_per_year else 0.0

    life = tech.stack_lifetime_h  # set to inf once a late replacement is skipped
    for t in range(1, n_years + 1):
        remaining_h = hours_per_year
        produced = 0.0
        # Walk through the year, splitting it at stack replacements.
        while remaining_h > 1e-9:
            seg = min(remaining_h, life - stack_hours)
            # Average SEC over the segment (linear degradation).
            h_mid = stack_hours + seg / 2.0
            sec = tech.sec_kwh_per_kg * (1.0 + deg * h_mid)
            produced += seg * energy_kwh_per_op_hour / sec
            stack_hours += seg
            remaining_h -= seg
            if stack_hours >= life - 1e-9:
                project_hours_left = remaining_h + (n_years - t) * hours_per_year
                if project_hours_left > project.skip_replacement_if_remaining_frac * life:
                    cf["Stack replacement"][t] += tech.stack_replacement_per_kw * p_kw
                    replacements.append(t)
                    stack_hours = 0.0
                else:
                    # Not worth a new stack this close to end of project:
                    # keep running the old one (and keep degrading).
                    life = float("inf")
        h2_kg[t] = produced
        cf["Electricity"][t] = d.electricity_cost
        cf["Fixed O&M"][t] = tech.fixed_om_frac * capex
        cf["Water"][t] = produced * tech.water_l_per_kg / 1000.0 * project.water_price_per_m3

    pv_h2 = float((h2_kg * disc).sum())
    if pv_h2 <= 0:
        raise ValueError(f"{tech.name}: no hydrogen produced (check min load / profile)")
    breakdown = {k: float((v * disc).sum()) / pv_h2 for k, v in cf.items()}
    return LCOHResult(
        tech=tech.name,
        lcoh=sum(breakdown.values()),
        breakdown=breakdown,
        annual_h2_t=h2_kg[1:] / 1000.0,
        stack_replacement_years=replacements,
        dispatch=d,
        currency=project.currency,
        cashflows=cf | {"H2 [kg]": h2_kg},
    )


def compare(
    techs: list[TechParams],
    project: ProjectParams,
    **profile_kwargs,
) -> list[LCOHResult]:
    return [compute_lcoh(t, project, **profile_kwargs) for t in techs]
