import numpy as np
import pytest

from lcoh import ALKALINE, PEM, ProjectParams, compute_lcoh, dispatch_year
from lcoh.sensitivity import breakeven_capex, tornado


def ideal(tech):
    """No degradation, no stack replacement, no O&M, no water: closed-form check."""
    return tech.with_(degradation_pct_per_1000h=0.0, stack_lifetime_h=1e12,
                      fixed_om_frac=0.0, water_l_per_kg=0.0)


def crf(r, n):
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


def test_closed_form_matches_annuity():
    proj = ProjectParams(wacc=0.07, lifetime_years=20, capacity_factor=0.5,
                         electricity_price_per_mwh=50.0)
    t = ideal(ALKALINE)
    res = compute_lcoh(t, proj)
    kg_per_kw_year = proj.capacity_factor * 8760 / t.sec_kwh_per_kg
    expected = (t.capex_per_kw * crf(proj.wacc, proj.lifetime_years) / kg_per_kw_year
                + proj.electricity_price_per_mwh / 1000 * t.sec_kwh_per_kg)
    assert res.lcoh == pytest.approx(expected, rel=1e-9)


def test_breakdown_sums_to_total():
    res = compute_lcoh(PEM, ProjectParams())
    assert sum(res.breakdown.values()) == pytest.approx(res.lcoh)


def test_stack_replacement_timing():
    proj = ProjectParams(capacity_factor=0.5, lifetime_years=25)  # 4380 h/yr
    t = ALKALINE.with_(stack_lifetime_h=4380 * 10)
    res = compute_lcoh(t, proj)
    assert res.stack_replacement_years == [10, 20]


def test_late_replacement_skipped():
    proj = ProjectParams(capacity_factor=0.5, lifetime_years=21,
                         skip_replacement_if_remaining_frac=0.25)
    t = ALKALINE.with_(stack_lifetime_h=4380 * 10)
    # Replacement at year 20 would leave only 1 year (10 % of stack life) -> skip.
    assert compute_lcoh(t, proj).stack_replacement_years == [10]


def test_degradation_reduces_output_and_raises_lcoh():
    proj = ProjectParams()
    base = compute_lcoh(ideal(PEM), proj)
    deg = compute_lcoh(ideal(PEM).with_(degradation_pct_per_1000h=0.5), proj)
    assert deg.annual_h2_t[-1] < deg.annual_h2_t[0]
    assert deg.lcoh > base.lcoh


def test_min_load_cuts_operation():
    avail = np.full(8760, 0.15)
    avail[:4380] = 1.0
    proj = ProjectParams()
    d_alk = dispatch_year(ALKALINE, proj, availability=avail)  # min 20 %
    d_pem = dispatch_year(PEM, proj, availability=avail)       # min 5 %
    assert d_alk.full_load_hours == pytest.approx(4380)
    assert d_pem.full_load_hours == pytest.approx(4380 + 0.15 * 4380)


def test_price_cap_and_constant_profile_consistency():
    proj = ProjectParams(electricity_price_per_mwh=60.0, capacity_factor=1.0)
    flat = compute_lcoh(ALKALINE, proj, availability=np.ones(8760))
    simple = compute_lcoh(ALKALINE, proj)
    assert flat.lcoh == pytest.approx(simple.lcoh)

    price = np.where(np.arange(8760) % 2 == 0, 20.0, 200.0)
    d = dispatch_year(ALKALINE, proj, price_per_mwh=price, price_cap_per_mwh=100.0)
    assert d.full_load_hours == pytest.approx(4380)
    assert d.electricity_cost == pytest.approx(4380 * 20.0 * proj.rated_power_mw)


def test_breakeven_capex_equalises_lcoh():
    proj = ProjectParams()
    be = breakeven_capex(PEM, ALKALINE, proj)
    assert compute_lcoh(PEM.with_(capex_per_kw=be), proj).lcoh == pytest.approx(
        compute_lcoh(ALKALINE, proj).lcoh, rel=1e-6)


def test_tornado_runs_and_is_sorted():
    base, bars = tornado(ALKALINE, ProjectParams())
    swings = [b.swing for b in bars]
    assert swings == sorted(swings, reverse=True)
    # SEC scales output (input power is fixed), so it moves every cost per kg
    # and can outrank the electricity price.
    assert {bars[0].param, bars[1].param} == {"sec_kwh_per_kg", "electricity_price_per_mwh"}


def test_no_production_raises():
    with pytest.raises(ValueError):
        compute_lcoh(ALKALINE, ProjectParams(), availability=np.full(8760, 0.1))
