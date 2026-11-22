"""Command-line interface.

Examples
--------
    python -m lcoh                                  # defaults, constant CF
    python -m lcoh --config config/example.toml --plots out/
    python -m lcoh --profile hybrid --plots out/    # synthetic PV+wind, min-load effects
    python -m lcoh --availability-csv re.csv:pu --price-csv prices.csv:eur_mwh
    python -m lcoh --set project.wacc=0.05 --set pem.capex_per_kw=1800
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

import numpy as np

from . import profiles
from .model import compare
from .params import DEFAULT_TECHS, ProjectParams
from .sensitivity import breakeven_capex, sweep, tornado


def load_config(path: str | None):
    techs = dict(DEFAULT_TECHS)
    project = ProjectParams()
    if path:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
        project = project.with_(**cfg.get("project", {}))
        for key in list(techs):
            if key in cfg:
                techs[key] = techs[key].with_(**cfg[key])
    return techs, project


def apply_overrides(techs, project, overrides: list[str]):
    for item in overrides:
        lhs, val = item.split("=", 1)
        section, field = lhs.split(".", 1)
        v = json.loads(val)
        if section == "project":
            project = project.with_(**{field: v})
        elif section in techs:
            techs[section] = techs[section].with_(**{field: v})
        else:
            raise SystemExit(f"unknown section '{section}' in --set {item}")
    return techs, project


def _csv_arg(spec: str) -> np.ndarray:
    path, _, col = spec.rpartition(":")
    if not path:
        raise SystemExit("CSV argument must be 'file.csv:column'")
    return profiles.load_csv(path, col)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lcoh", description="LCOH: PEM vs alkaline electrolysis")
    ap.add_argument("--config", help="TOML file with [project], [pem], [alkaline] sections")
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.FIELD=VALUE",
                    help="override a parameter, e.g. pem.capex_per_kw=1800")
    ap.add_argument("--profile", choices=["none", "solar", "wind", "hybrid"], default="none",
                    help="synthetic hourly availability profile")
    ap.add_argument("--oversize", type=float, default=1.5,
                    help="RE capacity / electrolyser power for synthetic profiles")
    ap.add_argument("--availability-csv", metavar="FILE:COLUMN",
                    help="hourly available power as fraction of electrolyser rating")
    ap.add_argument("--price-csv", metavar="FILE:COLUMN", help="hourly electricity price [cur/MWh]")
    ap.add_argument("--price-cap", type=float, help="shut down when price exceeds this [cur/MWh]")
    ap.add_argument("--plots", metavar="DIR", help="write figures to this directory")
    ap.add_argument("--json", metavar="FILE", help="write results to JSON")
    args = ap.parse_args(argv)

    techs, project = load_config(args.config)
    techs, project = apply_overrides(techs, project, args.set)
    tech_list = [techs["alkaline"], techs["pem"]]

    availability = price = None
    if args.availability_csv:
        availability = _csv_arg(args.availability_csv)
    elif args.profile != "none":
        solar, wind = profiles.synthetic_solar(), profiles.synthetic_wind()
        share = {"solar": 1.0, "wind": 0.0, "hybrid": 0.5}[args.profile]
        availability = profiles.hybrid(solar, wind, share, args.oversize)
    if args.price_csv:
        price = _csv_arg(args.price_csv)
    kw = dict(availability=availability, price_per_mwh=price, price_cap_per_mwh=args.price_cap)

    results = compare(tech_list, project, **kw)
    cur = project.currency
    print(f"Project: {project.rated_power_mw} MW, {project.lifetime_years} yr, "
          f"WACC {project.wacc:.1%}, currency {cur}")
    if availability is None and price is None:
        print(f"Operation: constant CF {project.capacity_factor:.0%} at "
              f"{project.electricity_price_per_mwh} {cur}/MWh")
    else:
        print("Operation: hourly profile"
              + (f", price cap {args.price_cap} {cur}/MWh" if args.price_cap else ""))
    print()
    for r in results:
        print(r.summary())
        print()

    alk, pem = results
    diff = pem.lcoh - alk.lcoh
    cheaper = "Alkaline" if diff > 0 else "PEM"
    print(f"{cheaper} is cheaper by {abs(diff):.2f} {cur}/kg ({abs(diff) / max(alk.lcoh, pem.lcoh):.1%}).")
    be = breakeven_capex(techs["pem"], techs["alkaline"], project, **kw)
    if np.isfinite(be):
        print(f"PEM matches alkaline LCOH at a PEM CAPEX of {be:,.0f} {cur}/kW "
              f"(currently {techs['pem'].capex_per_kw:,.0f}).")

    if args.plots:
        from . import plots

        out = Path(args.plots)
        out.mkdir(parents=True, exist_ok=True)
        files = [plots.breakdown_bar(results, out / "lcoh_breakdown.png")]
        if price is None:
            x = np.linspace(20, 150, 27)
            files.append(plots.sweep_plot(
                x, sweep(tech_list, project, "electricity_price_per_mwh", x, **kw),
                f"Electricity price [{cur}/MWh]", cur, out / "sweep_electricity_price.png",
                "LCOH vs electricity price"))
        if availability is None:
            x = np.linspace(0.15, 0.95, 33)
            files.append(plots.sweep_plot(
                x * 8760, sweep(tech_list, project, "capacity_factor", x, **kw),
                "Full-load hours [h/yr]", cur, out / "sweep_full_load_hours.png",
                "LCOH vs utilisation"))
        for t in tech_list:
            base, bars = tornado(t, project, **kw)
            files.append(plots.tornado_plot(base, bars, t.name, cur,
                                            out / f"tornado_{t.name.lower()}.png"))
        print("\nFigures:", *[str(f) for f in files], sep="\n  ")

    if args.json:
        payload = {
            "project": project.to_dict(),
            "technologies": {t.name: t.to_dict() for t in tech_list},
            "results": {r.tech: {
                "lcoh": r.lcoh, "breakdown": r.breakdown,
                "full_load_hours": r.dispatch.full_load_hours,
                "operating_hours": r.dispatch.operating_hours,
                "avg_h2_t_per_year": r.avg_h2_t_per_year,
                "stack_replacement_years": r.stack_replacement_years,
            } for r in results},
        }
        Path(args.json).write_text(json.dumps(payload, indent=2))
    return 0
