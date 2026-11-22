"""Matplotlib figures for LCOH comparisons."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .model import LCOHResult
from .sensitivity import TornadoBar

TECH_COLORS = {"Alkaline": "#2a6f97", "PEM": "#d1495b"}
COMPONENT_COLORS = {
    "CAPEX": "#3d5a80",
    "Electricity": "#ee9b00",
    "Fixed O&M": "#98c1d9",
    "Stack replacement": "#9b2226",
    "Water": "#94d2bd",
}
PRETTY = {
    "electricity_price_per_mwh": "Electricity price",
    "capacity_factor": "Capacity factor",
    "capex_per_kw": "System CAPEX",
    "sec_kwh_per_kg": "Specific energy (SEC)",
    "wacc": "WACC",
    "stack_lifetime_h": "Stack lifetime",
    "stack_replacement_per_kw": "Stack replacement cost",
    "fixed_om_frac": "Fixed O&M",
    "degradation_pct_per_1000h": "Degradation rate",
}


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3, linewidth=0.6)
    ax.set_axisbelow(True)


def breakdown_bar(results: list[LCOHResult], path: str | Path) -> Path:
    fig, ax = plt.subplots(figsize=(6, 4.5))
    names = [r.tech for r in results]
    bottom = np.zeros(len(results))
    for comp, color in COMPONENT_COLORS.items():
        vals = np.array([r.breakdown.get(comp, 0.0) for r in results])
        ax.bar(names, vals, bottom=bottom, color=color, label=comp, width=0.55,
               edgecolor="white", linewidth=0.8)
        bottom += vals
    for i, r in enumerate(results):
        ax.text(i, r.lcoh * 1.01, f"{r.lcoh:.2f}", ha="center", va="bottom", fontweight="bold")
    cur = results[0].currency
    ax.set_ylabel(f"LCOH [{cur}/kg H$_2$]")
    ax.set_title("LCOH breakdown")
    ax.set_ylim(0, bottom.max() * 1.12)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0))
    _style(ax)
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def sweep_plot(x: np.ndarray, curves: dict[str, np.ndarray], xlabel: str,
               currency: str, path: str | Path, title: str = "") -> Path:
    fig, ax = plt.subplots(figsize=(6, 4))
    for name, y in curves.items():
        ax.plot(x, y, lw=2, color=TECH_COLORS.get(name), label=name)
        ax.annotate(name, (x[-1], y[-1]), xytext=(4, 0), textcoords="offset points",
                    va="center", color=TECH_COLORS.get(name), fontweight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(f"LCOH [{currency}/kg H$_2$]")
    if title:
        ax.set_title(title)
    _style(ax)
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def tornado_plot(base: float, bars: list[TornadoBar], tech: str, currency: str,
                 path: str | Path, rel_change: float = 0.2) -> Path:
    fig, ax = plt.subplots(figsize=(6.5, 0.45 * len(bars) + 1.2))
    ys = np.arange(len(bars))[::-1]
    for y, b in zip(ys, bars):
        ax.barh(y, b.lcoh_low - base, left=base, color="#94d2bd", height=0.6)
        ax.barh(y, b.lcoh_high - base, left=base, color="#ee9b00", height=0.6)
    ax.axvline(base, color="black", lw=1)
    ax.set_yticks(ys, [PRETTY.get(b.param, b.param) for b in bars])
    ax.set_xlabel(f"LCOH [{currency}/kg H$_2$]")
    pct = int(rel_change * 100)
    ax.set_title(f"{tech}: sensitivity (±{pct} %), base {base:.2f}")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#94d2bd", label=f"−{pct} %"),
                       Patch(color="#ee9b00", label=f"+{pct} %")],
              frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = Path(path)
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path
