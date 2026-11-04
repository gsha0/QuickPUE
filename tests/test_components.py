"""Component verification against analytical solutions (requirements 14.1, V-C-1 to V-C-7)."""

import numpy as np
import pytest

from quickpue import psychro
from quickpue.chiller import ChillerModel, curves_from_library, curves_from_table, dispatch
from quickpue.curves import FFLP_LIBRARY, make_fflp
from quickpue.heatx import (AirWaterCoil, CoolingTowerUnit, adiabatic_temperature, eps_counterflow,
                            eps_crossflow_unmixed)
from quickpue.partload import FanPumpGroup


# V-C-1 chiller at the rated point -------------------------------------------------------------
@pytest.mark.parametrize("lib", ["EP-ACC-SCROLL-434", "EP-ACC-SCREW-1609", "EP-WCC-CENT-VSD-1495"])
def test_chiller_rated_point(lib):
    cv = curves_from_library(lib, 24.0, 32.0)
    m = ChillerModel("c", "air_cooled", 1, 0, 2200.0, 4.8, 24.0, 32.0, cv)
    assert m.capacity(24.0, 32.0) == pytest.approx(2200.0, rel=1e-9)
    p, plr = m.unit_power(2200.0, 24.0, 32.0)
    assert plr == pytest.approx(1.0, rel=1e-9)
    assert 2200.0 / p == pytest.approx(4.8, rel=1e-9)


def test_chiller_hand_calculation():
    cv = curves_from_library("EP-ACC-SCROLL-434", 24.0, 32.0)
    m = ChillerModel("c", "air_cooled", 1, 0, 2200.0, 4.8, 24.0, 32.0, cv, min_plr=0.15)
    lwt, tc, q = 24.0, 20.0, 1100.0
    cap = 2200.0 * cv.capft(lwt, tc)
    plr = q / cap
    hand = cap / 4.8 * cv.eirft(lwt, tc) * cv.eirfplr(plr)
    p, _ = m.unit_power(q, lwt, tc)
    assert p == pytest.approx(hand, rel=1e-12)
    # cycling below minimum PLR
    q2 = 0.05 * cap
    p2, _ = m.unit_power(q2, lwt, tc)
    hand2 = cap / 4.8 * cv.eirft(lwt, tc) * cv.eirfplr(0.15) * (0.05 / 0.15)
    assert p2 == pytest.approx(hand2, rel=1e-9)


def test_chiller_table_fit_recovers_curves():
    true = curves_from_library("EP-ACC-SCROLL-434", 24.0, 32.0, clamp=False)
    rows = []
    for lwt in (20.0, 24.0, 28.0):
        for tc in (15.0, 25.0, 35.0, 40.0):
            cap = 2200 * float(true.capft(lwt, tc))
            rows.append({"lwt_c": lwt, "ect_c": tc, "capacity_kw": cap,
                         "power_kw": cap / 4.8 * float(true.eirft(lwt, tc))})
            for plr in (0.3, 0.6):
                rows.append({"lwt_c": lwt, "ect_c": tc, "load_kw": plr * cap, "plr": plr,
                             "power_kw": cap / 4.8 * float(true.eirft(lwt, tc)) * float(true.eirfplr(plr))})
    fit = curves_from_table(rows, 2200.0, 4.8, 24.0, 32.0)
    assert fit.fit_report["CAPFT"]["rms"] < 1e-3
    assert fit.fit_report["EIRFT"]["rms"] < 1e-3
    assert float(fit.eirfplr(0.45)) == pytest.approx(float(true.eirfplr(0.45)), rel=2e-3)


def test_staging_minimum_units_equal_loading():
    cv = curves_from_library("EP-ACC-SCROLL-434", 24.0, 32.0, clamp=False)
    m = ChillerModel("c", "air_cooled", 4, 1, 1000.0, 4.0, 24.0, 32.0, cv, stage_up=0.9)
    r = dispatch([m], np.array([0.0, 850.0, 1850.0, 4500.0, 5200.0]), 24.0, {"c": np.full(5, 32.0)})
    t = r["types"]["c"]
    assert list(t["n_run"]) == [0, 1, 3, 5, 5]
    assert t["plr"][2] == pytest.approx(1850.0 / 3000.0)
    assert r["unmet"][-1] == pytest.approx(200.0)
    assert t["standby_used"][3] == 1


# V-C-2 curves ---------------------------------------------------------------------------------
def test_dp_curve_identity():
    for s in (0.0, 0.3, 0.7, 1.0):
        k = make_fflp(f"K-DP({s})")
        f = np.linspace(0, 1, 11)
        assert np.allclose(k(f), s * f + (1 - s) * f**3)
    assert np.allclose(make_fflp("K-DP(0)")(np.linspace(0, 1, 5)), make_fflp("K-CUBE")(np.linspace(0, 1, 5)))
    assert np.allclose(make_fflp("K-DP(1)")(np.linspace(0, 1, 5)), make_fflp("K-LIN")(np.linspace(0, 1, 5)))


def test_curve_comparison_table_11_3():
    golden = {"K-CUBE": [1.000, 0.512, 0.216, 0.064, 0.027], "K-DP(0.3)": [1.000, 0.598, 0.331, 0.165, 0.109],
              "K-LIN": [1.000, 0.800, 0.600, 0.400, 0.300], "K-VSM": [0.999, 0.656, 0.379, 0.174, 0.100],
              "K-90.1G": [0.999, 0.676, 0.410, 0.206, 0.128]}
    f = np.array([1.0, 0.8, 0.6, 0.4, 0.3])
    for cid, vals in golden.items():
        k = make_fflp(cid)
        assert np.allclose(np.round(k._raw(f), 3), vals, atol=1e-9), cid
        assert k(np.array([1.0]))[0] == pytest.approx(1.0)  # normalised


def test_all_library_curves_normalised():
    for cid in FFLP_LIBRARY:
        assert make_fflp(cid)(np.array([1.0]))[0] == pytest.approx(1.0)


def test_user_table_curve():
    k = make_fflp({"table": [[0, 0.08], [0.5, 0.29], [1, 1.0]]})
    assert k(np.array([0.75]))[0] == pytest.approx((0.29 + 1.0) / 2)


def test_drive_correction_rejected_for_empirical_curve():
    from quickpue.partload import build_group
    from quickpue.schema import FanPump

    spec = FanPump(power_kw=10, flow_l_s=100, quantity=1, part_load={"curve": "K-VSM", "drive": True})
    with pytest.raises(ValueError):
        build_group("x", "fwu_fans", spec)


# V-C-3 PLR methods and running rules ----------------------------------------------------------
def _g(**kw):
    base = dict(name="g", end_use="e", p_des_kw=10.0, v_des_m3s=1.0, n_duty=4, n_standby=1, redundancy="N+x",
                method="M1", curve=make_fflp("K-CUBE"), f_min=0.3, rule="R-ALL", design_load_kw=400.0)
    base.update(kw)
    return FanPumpGroup(**base)


def test_worked_example_11_5():
    g = _g(p_des_kw=1.0, redundancy="2N_active", design_load_kw=100.0)
    assert np.allclose(g.evaluate(q_served=np.array([90.0, 25.0]))["power"], [1.86624, 0.135])
    g = _g(p_des_kw=1.0, rule="R-STAGE", design_load_kw=100.0)
    assert np.allclose(g.evaluate(q_served=np.array([90.0, 25.0]))["power"], [2.916, 1.0])


def test_methods_m1_to_m6():
    q = np.array([200.0])
    assert _g().evaluate(q_served=q)["f"][0] == pytest.approx(0.5)  # M1: 200/400 * 4/4
    r = _g(method="M2").evaluate(v_req=np.array([2.0]))
    assert r["f"][0] == pytest.approx(0.5) and r["power"][0] == pytest.approx(4 * 10 * 0.125)
    assert _g(method="M3").evaluate(n_hours=1)["power"][0] == pytest.approx(40.0)
    r = _g(method="M5").evaluate(f_direct=np.array([0.6]))
    assert r["power"][0] == pytest.approx(4 * 10 * 0.216)
    r = _g(method="M6", table=[[0, 0], [0.9, 1.0]]).evaluate(it_fraction=np.array([0.45]))
    assert r["f"][0] == pytest.approx(0.5)
    r = _g(method="M2").evaluate(v_req=np.array([0.4]))  # f = 0.1 -> clamped to 0.3
    assert r["f_eff"][0] == pytest.approx(0.3) and r["bypass"][0] == pytest.approx(0.2)


def test_epseq_sequential_loading():
    g = _g(method="M2", rule="R-EPSEQ", curve=make_fflp("K-CUBE"), f_min=0.0)
    r = g.evaluate(v_req=np.array([2.5]))
    assert r["n_run"][0] == 3
    assert r["power"][0] == pytest.approx(10 * (2 * 1.0 + 0.5**3))


# V-C-4 heat exchangers ------------------------------------------------------------------------
def test_dry_cooler_rated_point_and_limits():
    coil = AirWaterCoil.from_rating("dc", 1000.0, 40.0, 32.0, 25.0)
    assert coil.q(1.0, 125.0, 40.0, 25.0) == pytest.approx(1000.0, rel=1e-3)
    assert eps_crossflow_unmixed(np.array([1e-6]), 0.5)[0] == pytest.approx(0.0, abs=1e-5)
    assert eps_crossflow_unmixed(np.array([200.0]), 0.5)[0] == pytest.approx(1.0, abs=2e-3)
    assert eps_counterflow(np.array([1.0]), 1.0)[0] == pytest.approx(0.5)
    f, q, sat = coil.solve_f(np.array([500.0]), np.array([125.0]), np.array([40.0]), np.array([25.0]))
    assert coil.q(f, 125.0, 40.0, 25.0)[0] == pytest.approx(500.0, rel=1e-4) and not sat[0]


def test_tower_rated_point():
    t = CoolingTowerUnit.from_rating("ct", 3000.0, 24.0, 4.0, 5.0)
    assert t.q(1.0, t.m_w_des, np.array([33.0]), np.array([24.0]))[0] == pytest.approx(3000.0, rel=1e-3)
    assert t.leaving_temp(np.array([3000.0]), t.m_w_des, np.array([24.0]), 1.0)[0] == pytest.approx(28.0, abs=0.01)


def test_adiabatic_worked_point_o10():
    """TEST_CASES O-10: recirculation added after the pads."""
    pad = adiabatic_temperature(41.4, 24.0, 0.78, 0.0)
    cond = adiabatic_temperature(41.4, 24.0, 0.78, 5.0, "after_pads")
    assert float(pad) == pytest.approx(27.828, abs=0.01)
    assert float(cond) == pytest.approx(32.828, abs=0.01)
    before = adiabatic_temperature(41.4, 24.0, 0.78, 5.0, "before_pads")
    assert float(before) == pytest.approx(46.4 - 0.78 * (46.4 - 24.0))


# V-C-6 psychrometrics -------------------------------------------------------------------------
@pytest.mark.parametrize("t,p", [(-10.0, 0.25987), (0.0, 0.61121), (20.0, 2.3392), (40.0, 7.3851),
                                 (60.0, 19.947)])
def test_saturation_pressure_ashrae_table(t, p):
    assert float(psychro.p_ws(t)) == pytest.approx(p, rel=0.005)


def test_wet_bulb_consistency():
    p = 101.325
    for t in (5.0, 20.0, 35.0):
        ws = psychro.humidity_ratio_sat(t, p)
        assert float(psychro.wet_bulb(np.array([t]), np.array([ws]), p)[0]) == pytest.approx(t, abs=0.01)
    # ASHRAE chart: 30 C DB, 50 % RH, sea level -> wet bulb about 22.0 C
    w = psychro.humidity_ratio_from_rh(30.0, 50.0, p)
    assert float(psychro.wet_bulb(np.array([30.0]), np.array([w]), p)[0]) == pytest.approx(22.0, abs=0.1)
    assert float(psychro.pressure_at_altitude(0.0)) == pytest.approx(101.325)


# V-C-5 UPS and transformer at table points ----------------------------------------------------
def test_ups_table_points_exact():
    from quickpue.curves import Table1D

    tab = Table1D([0.25, 0.5, 0.75, 1.0], [0.95, 0.96, 0.965, 0.97])
    assert np.allclose(tab(np.array([0.25, 0.5, 0.75, 1.0])), [0.95, 0.96, 0.965, 0.97])
    assert float(tab(0.9)) == pytest.approx(0.968)
