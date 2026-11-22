"""Sensitivity tools: one-at-a-time tornado, 1-D sweeps and break-even search."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .model import compute_lcoh
from .params import ProjectParams, TechParams

TECH_FIELDS = {"capex_per_kw", "sec_kwh_per_kg", "degradation_pct_per_1000h",
               "stack_lifetime_h", "stack_replacement_per_kw", "min_load",
               "fixed_om_frac", "water_l_per_kg"}
PROJECT_FIELDS = {"rated_power_mw", "lifetime_years", "wacc", "electricity_price_per_mwh",
                  "capacity_factor", "water_price_per_m3"}


def _apply(tech: TechParams, project: ProjectParams, param: str, value: float):
    if param in TECH_FIELDS:
        return tech.with_(**{param: value}), project
    if param in PROJECT_FIELDS:
        if param == "lifetime_years":
            value = int(round(value))
        return tech, project.with_(**{param: value})
    raise KeyError(f"unknown parameter '{param}'")


def _get(tech: TechParams, project: ProjectParams, param: str) -> float:
    return getattr(tech, param) if param in TECH_FIELDS else getattr(project, param)


@dataclass
class TornadoBar:
    param: str
    low_value: float
    high_value: float
    lcoh_low: float
    lcoh_high: float

    @property
    def swing(self) -> float:
        return abs(self.lcoh_high - self.lcoh_low)


def tornado(tech: TechParams, project: ProjectParams,
            params: list[str] | None = None, rel_change: float = 0.2,
            **profile_kwargs) -> tuple[float, list[TornadoBar]]:
    """Vary each parameter by +/- rel_change; return base LCOH and bars sorted by swing."""
    params = params or ["electricity_price_per_mwh", "capacity_factor", "capex_per_kw",
                        "sec_kwh_per_kg", "wacc", "stack_lifetime_h",
                        "stack_replacement_per_kw", "fixed_om_frac",
                        "degradation_pct_per_1000h"]
    if profile_kwargs.get("availability") is not None:
        params = [p for p in params if p != "capacity_factor"]
    if profile_kwargs.get("price_per_mwh") is not None:
        params = [p for p in params if p != "electricity_price_per_mwh"]
    base = compute_lcoh(tech, project, **profile_kwargs).lcoh
    bars = []
    for p in params:
        v0 = _get(tech, project, p)
        lo, hi = v0 * (1 - rel_change), v0 * (1 + rel_change)
        if p == "capacity_factor":
            hi = min(hi, 1.0)
        res = []
        for v in (lo, hi):
            t, pr = _apply(tech, project, p, v)
            res.append(compute_lcoh(t, pr, **profile_kwargs).lcoh)
        bars.append(TornadoBar(p, lo, hi, res[0], res[1]))
    bars.sort(key=lambda b: b.swing, reverse=True)
    return base, bars


def sweep(techs: list[TechParams], project: ProjectParams, param: str,
          values: np.ndarray, **profile_kwargs) -> dict[str, np.ndarray]:
    """LCOH of each technology as a function of one parameter.

    For tech-specific parameters (e.g. capex_per_kw) the same absolute value is
    applied to every technology, which is usually only meaningful for shared
    project parameters (electricity price, capacity factor, WACC)."""
    out = {}
    for tech in techs:
        ys = []
        for v in values:
            t, pr = _apply(tech, project, param, float(v))
            ys.append(compute_lcoh(t, pr, **profile_kwargs).lcoh)
        out[tech.name] = np.array(ys)
    return out


def breakeven_capex(tech: TechParams, reference: TechParams, project: ProjectParams,
                    **profile_kwargs) -> float:
    """CAPEX [cur/kW] at which `tech` matches the LCOH of `reference` (bisection)."""
    target = compute_lcoh(reference, project, **profile_kwargs).lcoh

    def f(capex):
        return compute_lcoh(tech.with_(capex_per_kw=capex), project, **profile_kwargs).lcoh - target

    lo, hi = 0.0, 20_000.0
    if f(lo) > 0:
        return float("nan")  # cannot break even even at zero CAPEX
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
