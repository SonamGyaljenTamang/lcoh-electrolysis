"""Hourly profiles: load from CSV or generate synthetic ones for testing.

Synthetic profiles are rough, reproducible stand-ins (seeded) for demonstrating
how minimum load and variability affect PEM vs alkaline. For real studies use
measured or reanalysis data (e.g. renewables.ninja, PVGIS, ENTSO-E prices).
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

HOURS = 8760


def load_csv(path: str | Path, column: str) -> np.ndarray:
    """Read one numeric column from a CSV with a header row."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or column not in reader.fieldnames:
            raise KeyError(f"column '{column}' not found in {path}; have {reader.fieldnames}")
        return np.array([float(row[column]) for row in reader])


def synthetic_solar(lat_deg: float = 49.0, seed: int = 0) -> np.ndarray:
    """Normalised PV output (0..1) for a mid-latitude site, ~11-13 % CF at 49 N."""
    rng = np.random.default_rng(seed)
    h = np.arange(HOURS)
    day = h // 24
    hour = h % 24 + 0.5
    lat = np.radians(lat_deg)
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + day + 1) / 365)
    hour_angle = np.radians(15 * (hour - 12))
    sin_alt = np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(hour_angle)
    clear = np.clip(sin_alt, 0, None) ** 1.15
    # Daily cloudiness, persistent over a few days.
    c = np.empty(365)
    c[0] = 0.5
    for i in range(1, 365):
        c[i] = 0.7 * c[i - 1] + 0.3 * rng.uniform(0, 1)
    seasonal = 0.55 + 0.25 * np.cos(2 * np.pi * (np.arange(365) - 172) / 365)
    cloud_factor = np.clip(1.0 - 0.9 * c * (1.3 - seasonal), 0.08, 1.0)
    out = clear * np.repeat(cloud_factor, 24) * 1.05
    return np.clip(out, 0, 1)


def synthetic_wind(mean_speed: float = 7.5, seed: int = 1) -> np.ndarray:
    """Normalised wind turbine output (0..1) from an AR(1) Weibull-like speed series."""
    rng = np.random.default_rng(seed)
    z = np.empty(HOURS)
    z[0] = 0.0
    phi = 0.97
    eps = rng.normal(0, np.sqrt(1 - phi**2), HOURS)
    for t in range(1, HOURS):
        z[t] = phi * z[t - 1] + eps[t]
    # Map Gaussian -> Weibull(k=2) via the uniform CDF.
    from math import erf, sqrt

    u = 0.5 * (1 + np.vectorize(erf)(z / sqrt(2)))
    u = np.clip(u, 1e-9, 1 - 1e-9)
    k = 2.0
    scale = mean_speed / 0.8862  # Gamma(1 + 1/k) for k=2
    v = scale * (-np.log(1 - u)) ** (1 / k)
    v *= 1 + 0.12 * np.cos(2 * np.pi * (np.arange(HOURS) / 24 - 15) / 365)  # winter-heavy
    return power_curve(v)


def power_curve(v: np.ndarray, v_in=3.0, v_rated=12.0, v_out=25.0) -> np.ndarray:
    p = np.where(v < v_in, 0.0, ((v - v_in) / (v_rated - v_in)) ** 3)
    p = np.where(v >= v_rated, 1.0, p)
    p = np.where(v >= v_out, 0.0, p)
    return np.clip(p, 0, 1)


def hybrid(solar: np.ndarray, wind: np.ndarray, solar_share: float = 0.5,
           oversize: float = 1.5) -> np.ndarray:
    """Combine PV and wind; `oversize` = installed RE capacity / electrolyser power."""
    return np.clip(oversize * (solar_share * solar + (1 - solar_share) * wind), 0, 1)


def synthetic_price(mean: float = 70.0, seed: int = 2,
                    solar: np.ndarray | None = None) -> np.ndarray:
    """Day-ahead-like hourly price with daily/seasonal shape and solar cannibalisation."""
    rng = np.random.default_rng(seed)
    h = np.arange(HOURS)
    hour = h % 24
    daily = 1 + 0.2 * np.cos(2 * np.pi * (hour - 19) / 24)  # evening peak, night trough
    seasonal = 1 + 0.2 * np.cos(2 * np.pi * (h / 24 - 15) / 365)
    noise = np.exp(rng.normal(0, 0.25, HOURS))
    p = mean * daily * seasonal * noise
    if solar is not None:
        p = p * (1 - 0.6 * solar)
    return p * mean / p.mean()
