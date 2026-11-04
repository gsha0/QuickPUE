"""Reference test cases DC_O1 and DC_S1 (docs/TEST_CASES.md): W-01, T1 checks O-01 to O-11 and
S-01 to S-06, and T3 robustness.  T2 comparisons are reported by tests/cases/compare_reference.py
(not asserted: they apply once the missing M items are supplied)."""

from pathlib import Path

import numpy as np
import pytest

import quickpue as q
from quickpue.weather import monthly_summary, read_epw

HERE = Path(__file__).parent
EPW = HERE / "data" / "AUS_NSW_Horsley.Equestrian.Centre.947600_TMYx.2011-2025.epw"
SCEN = ["90%", "75%", "50%", "25%"]


@pytest.fixture(scope="module")
def weather():
    return read_epw(EPW)


@pytest.fixture(scope="module")
def o1():
    return q.run(HERE / "cases" / "dc_o1.yaml")


@pytest.fixture(scope="module")
def s1():
    return q.run(HERE / "cases" / "dc_s1.yaml", counterfactual=False)


def mwh(res, name, key):
    s = res.scenario(name)
    return float(s.end_uses[s.end_uses.key == key].kwh.sum()) / 1e3


# W-01 -----------------------------------------------------------------------------------------
W01 = {  # month: DBT max, DBT min, DPT max, DPT min, RH mean
    "Jan": (43.1, 14.4, 20.9, 6.2, 68), "Feb": (34.4, 13.7, 20.9, 11.0, 74), "Mar": (34.5, 9.9, 21.0, 0.0, 72),
    "Apr": (29.3, 9.3, 19.3, 2.5, 72), "May": (24.3, 1.6, 15.6, -2.6, 72), "Jun": (19.4, 2.1, 12.9, -2.7, 72),
    "Jul": (24.1, 0.6, 13.9, -3.5, 68), "Aug": (26.3, 2.8, 11.3, -3.0, 62), "Sep": (28.4, 4.2, 15.5, -5.2, 62),
    "Oct": (29.4, 8.0, 18.1, -1.0, 67), "Nov": (40.0, 9.5, 22.8, 6.5, 68), "Dec": (36.5, 10.1, 22.9, -1.3, 67),
    "Annual": (43.1, 0.6, 22.9, -5.2, 69),
}


def test_w01_monthly_weather(weather):
    t = monthly_summary(weather)
    assert weather.wmo == "947600" and weather.elevation_m == 100.0
    for m, (dmax, dmin, pmax, pmin, rh) in W01.items():
        r = t.loc[m]
        assert r["DBT max (C)"] == pytest.approx(dmax, abs=0.05)
        assert r["DBT min (C)"] == pytest.approx(dmin, abs=0.05)
        assert r["DPT max (C)"] == pytest.approx(pmax, abs=0.05)
        assert r["DPT min (C)"] == pytest.approx(pmin, abs=0.05)
        # RH mean agrees within rounding except April (73.0 vs 72), recorded in docs/VALIDATION.md
        assert r["RH mean (%)"] == pytest.approx(rh, abs=1.05)


# DC_O1 T1 -------------------------------------------------------------------------------------
def test_o01_it_energy(o1):
    for name, ref in zip(SCEN, [488808, 407340, 271560, 135780]):
        assert o1.scenario(name).metrics["it_kwh"] / 1e3 == pytest.approx(ref, rel=1e-9)


def test_o02_diesel(o1):
    m = o1.scenarios[0].metrics
    assert m["diesel_l"] == pytest.approx(133000.0)
    assert m["diesel_kwh"] / 1e3 == pytest.approx(1426.0, abs=0.5)
    assert 133000 * 0.01076 == pytest.approx(1431.08)  # tool default factor gives 1,431 MWh


def test_o03_ups_it_loss_simplified_convention(o1):
    implied = {"75%": 3.47, "50%": 4.00, "25%": 5.20}
    eta = {"90%": 0.968, "75%": 0.965, "50%": 0.960, "25%": 0.950}
    for name in SCEN:
        s = o1.scenario(name)
        frac = 100 * mwh(o1, name, "ups_loss_it") * 1e3 / s.metrics["it_kwh"]
        assert frac == pytest.approx(100 * (1 - eta[name]), abs=1e-6)  # P_out (1 - eta), interpolated
        if name in implied:
            assert abs(frac - implied[name]) <= 0.2 + 1e-6
    # I-O9: the source's 90 % case used the 100 % point (3.00 %); interpolation gives 3.20 %
    assert mwh(o1, "90%", "ups_loss_it") == pytest.approx(488808 * 0.032, rel=1e-6)


def test_o04_cdu_pumps(o1):
    for name, ref in zip(SCEN, [5597.6, 4664, 3110, 1554]):
        assert mwh(o1, name, "cdu_pumps") == pytest.approx(ref, abs=1.0)


def test_o05_integral_pumps(o1):
    for name, ref in zip(SCEN, [10696.0, 7427, 5241, 5241]):
        assert mwh(o1, name, "chw_pumps_integral") == pytest.approx(ref, rel=1e-3)


def test_o06_transformer_and_switchboard(o1):
    ref = {"transformer_mvlv": [6543.7, 5453, 3636, 1817], "distribution_loss": [6543.7, 5453, 3636, 1817],
           "transformer_hv": [5234.9, 4363, 2909, 1454]}
    for key, vals in ref.items():
        for name, v in zip(SCEN, vals):
            assert mwh(o1, name, key) == pytest.approx(v, abs=1.0)


def test_o07_jacket_heaters(o1, weather):
    # stated EFLH (input) reproduces the reference energy
    assert mwh(o1, "90%", "jacket_heaters") == pytest.approx(1119.0, rel=5e-3)
    # the stated ramp (on below 10 C, off at 32 C) gives 5,777 h from this EPW, not 3,680 h (see VALIDATION.md)
    eflh = np.clip((32.0 - weather.t_db) / 22.0, 0, 1).sum()
    assert eflh == pytest.approx(5777.2, abs=0.5)


def test_o08_lifts(o1):
    assert mwh(o1, "90%", "lifts") * 1e3 == pytest.approx(11458, rel=5e-3)


def test_o09_contingency(o1):
    for s in o1.scenarios:
        others = s.metrics["infra_gross_kwh"]
        assert s.metrics["contingency_kwh"] == pytest.approx(0.025 * others, rel=1e-12)
    assert 0.025 * 107985.4 == pytest.approx(2699.6, abs=0.05)


def test_o10_adiabatic_engine_hour(o1, weather):
    s = o1.scenario("90%")
    h = 420  # 18 January, hour ending 13:00, T_db 41.4 C
    assert weather.t_db[h] == pytest.approx(41.4)
    d = s.sim.detail["chiller:ACC"]
    expected = weather.t_db[h] - 0.78 * (weather.t_db[h] - weather.t_wb[h]) + 5.0
    assert d["t_cond"][h] == pytest.approx(expected, abs=1e-9)
    # EPW psychrometric wet bulb is 23.2 C (source used 24.0 C): 32.2 C vs 32.9 C condenser inlet


def test_o11_adiabatic_hours(o1, weather):
    assert int((weather.t_db > 31.0).sum()) == 157
    assert int((weather.t_db >= 31.0).sum()) == 160  # three hours at exactly 31.0 C
    s = o1.scenario("90%")
    assert int(s.sim.detail["plant:Chiller plant"]["adiabatic"].sum()) <= 157


def test_o_adiabatic_counterfactual_reported(o1):
    cf = o1.scenarios[0].counterfactual
    assert cf is not None and cf["chiller_kwh_dry"] > cf["chiller_kwh_with"]
    assert 0.0 < cf["chiller_reduction_pct"] < 10.0


# DC_S1 T1 -------------------------------------------------------------------------------------
def test_s01_it_energy(s1):
    for name, ref in zip(SCEN, [1513728, 1261440, 840960, 420480]):
        assert s1.scenario(name).metrics["it_kwh"] / 1e3 == pytest.approx(ref, rel=1e-9)


def test_s02_ups_table_points(s1):
    tab = s1.engine.ups_tables["UPS-IT"]
    xs = [0.25 + 0.05 * i for i in range(16)]
    ys = [0.880, 0.895, 0.910, 0.920, 0.925, 0.927, 0.931, 0.936, 0.940, 0.942, 0.945, 0.949, 0.953, 0.955, 0.957,
          0.960]
    assert np.allclose(tab(np.array(xs)), ys, atol=1e-12)


def test_s03_chw_reset(s1):
    from quickpue.weather import Weather

    w = Weather.synthetic([20.0, 26.0, 33.5, 41.0, 45.0], rh=40.0)
    t = s1.engine.tsup(s1.engine.loops["CHW"], w)
    assert np.allclose(t, [24.0, 24.0, 26.0, 28.0, 28.0])


def test_s04_dry_condenser_entering_air(s1, weather):
    d = s1.scenario("90%").sim.detail
    mode = d["plant:Chiller plant"]["mode"]
    tc = d["chiller:ACC-FC"]["t_cond"]
    mech = mode == 3
    assert mech.any()
    assert np.allclose(tc[mech], weather.t_db[mech] + 2.7)


def test_s05_jacket_heaters(s1):
    assert mwh(s1, "90%", "jacket_heaters") == pytest.approx(944 * 3680 / 1e3, rel=1e-6)
    assert mwh(s1, "90%", "jacket_heaters") == pytest.approx(3474, abs=0.5)


def test_s06_loop_capacity_design_check(s1):
    from quickpue.tables import design_check_tables

    caps = design_check_tables(s1)[1]
    row = caps[caps.Equipment == "Chillers ACC-FC"].iloc[0]
    per_loop_duty = row["Installed N (kW)"] / 8
    assert per_loop_duty == pytest.approx(24000.0)
    assert row["Required at design (kW)"] / 8 > 0.9 * 21600  # IT plus air-side gains, fan and pump heat
    assert np.isfinite(row["Margin N (%)"])  # margin at design ambient + 2.7 K is reported


# T3 robustness --------------------------------------------------------------------------------
@pytest.mark.parametrize("fixture", ["o1", "s1"])
def test_t3_runs_balance_and_register(fixture, request):
    res = request.getfixturevalue(fixture)
    for s in res.scenarios:
        assert s.metrics["balance_max_rel_error"] < 0.005
        assert s.metrics["nonconverged_hours"] == 0
        assert np.isfinite(s.metrics["pue"]) and 1.0 < s.metrics["pue"] < 2.0
    kinds = {e.kind for e in res.register}
    assert "assumption" in kinds and "document" in kinds
    assert any(e.origin == "auto" for e in res.register)
    from quickpue.tables import assumptions_table

    t = assumptions_table(res)
    assert any("library curve analogue" in x for x in t.Item)
