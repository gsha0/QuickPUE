"""System tests: every preset runs from minimum input (P2 exit), loop arrangements (Section 12, V-C-7),
hourly IT profiles (UC-6), outputs, explain, CLI, determinism (NF-2) and input attribution."""

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import quickpue as q
from quickpue.inputs import list_presets

HERE = Path(__file__).parent
EPW = str(HERE / "data" / "AUS_NSW_Horsley.Equestrian.Centre.947600_TMYx.2011-2025.epw")


def minimum(preset, **extra):
    d = {"preset": preset, "project": {"name": f"min {preset}"}, "weather": {"epw": EPW},
         "it": {"installed_kw": 4000, "liquid_fraction": 0.0 if preset.startswith("AIR") else 0.75},
         "scenarios": [{"name": "90%", "it_fraction": 0.9}, {"name": "25%", "it_fraction": 0.25}]}
    d.update(extra)
    return d


@pytest.mark.parametrize("pid", [p["id"] for p in list_presets()])
def test_every_preset_runs_from_minimum_input(pid):
    res = q.run(minimum(pid), counterfactual=False)
    assert len(res.scenarios) == 2
    for s in res.scenarios:
        m = s.metrics
        assert 1.0 < m["pue"] < 2.5, (pid, m["pue"])
        assert m["balance_max_rel_error"] < 0.005, pid
        assert m["nonconverged_hours"] == 0, pid
    assert any(e.origin == "preset" for e in res.register)
    assert any(e.origin == "auto" for e in res.register)


def test_presets_cover_catalog():
    ids = {p["id"] for p in list_presets()}
    assert len(ids) == 18
    assert {"LC-ACC-IFC-AD", "LC-ACC-IFC-DUAL", "LC-W45-DC", "AIR-WCC-WSE", "LC-WSE"} <= ids


def test_override_preset_value_and_register():
    d = minimum("LC-ACC-IFC", loops=[{"name": "CHW", "supply_c": {"value": 26.0, "source": {
        "kind": "designer", "ref": "SOO rev B"}}, "return_c": 36.0}])
    res = q.run(d, ["90%"], counterfactual=False)
    lp = next(x for x in res.project.loops if x.name == "CHW")
    assert lp.supply_c == 26.0 and lp.medium == "pg"  # preset medium kept, user supply applied
    reg = {e.path: e for e in res.register}
    assert reg["loops[CHW].supply_c"].kind == "designer"
    assert reg["loops[CHW].medium"].origin == "preset"


def test_unit_conversion_and_bad_unit():
    d = minimum("LC-ACC", it={"installed_kw": {"value": 4, "unit": "MW"}, "liquid_fraction": 0.7})
    lp = q.load_project(d)
    assert lp.project.halls[0].it_kw == pytest.approx(4000.0)
    with pytest.raises(ValueError):
        q.load_project(minimum("LC-ACC", it={"installed_kw": {"value": 4, "unit": "furlong"}}))


def test_invalid_combination_fails_validation():
    d = minimum("LC-ACC")
    d["plants"] = [{"name": "Plant", "type": "CP-3"}]  # chillers present but CP-3 is dry coolers only
    with pytest.raises(ValueError, match="CP-3"):
        q.run(d, counterfactual=False)


# Section 12 loop arrangements -----------------------------------------------------------------
def _dual(conn, extra_loop=None):
    d = minimum("LC-ACC-IFC-DUAL")
    loops = [{"name": "CHW-HT", "connection": conn, "from_loop": "CHW", "hx_approach_k": 2.0}]
    if extra_loop:
        loops[0].update(extra_loop)
    d["loops"] = loops
    return d


def test_blending_dt_a_mass_energy_balance():
    res = q.run(_dual("blended"), ["90%"], counterfactual=False)
    s = res.scenarios[0]
    h = s.hourly
    eng = res.engine
    # plant load equals MT own load + HT total (energy) and blend ratio is within 0..1
    q_ht = h["loop_load_kw:CHW-HT"].to_numpy()
    q_mt = h["loop_load_kw:CHW"].to_numpy()
    assert (q_mt > q_ht).all()
    t_ret_ht = h["loop_return_c:CHW-HT"].to_numpy()
    draw = q_ht / (eng.loop_rcp["CHW"] * (t_ret_ht - 24.0))
    flow_ht = h["loop_flow_l_s:CHW-HT"].to_numpy() / 1000
    assert (draw <= flow_ht + 1e-9).all() and (draw > 0).all()
    assert s.metrics["balance_max_rel_error"] < 1e-9


def test_hx_cascade_dt_b_drift():
    # HT setpoint below MT supply + approach -> unmet drift reported
    res = q.run(_dual("hx", {"supply_c": 25.0, "return_c": 35.0}), ["90%"], counterfactual=False)
    h = res.scenarios[0].hourly
    assert np.allclose(h["loop_supply_c:CHW-HT"], 26.0)  # 24 + 2 K approach


def test_split_duty_dt_d():
    d = minimum("LC-ACC-IFC-DUAL")
    d["loops"] = [{"name": "CHW-HT", "connection": "split", "from_loop": "CHW"}]
    d["plants"] = [{"name": "HT dry coolers", "type": "CP-3", "loop": "CHW-HT", "dry_coolers": [{"name": "DC-HT"}]}]
    res = q.run(d, ["90%"], counterfactual=False)
    s = res.scenarios[0]
    assert s.metrics["balance_max_rel_error"] < 1e-6
    assert s.end_uses[s.end_uses.key == "heat_rejection_fans"].kwh.sum() > 0


# UC-6 hourly IT profiles ----------------------------------------------------------------------
def test_hourly_profile_matches_flat(tmp_path):
    p = tmp_path / "it.csv"
    pd.DataFrame({"it": np.full(8760, 0.6)}).to_csv(p, index=False)
    d = minimum("LC-ACC-IFC")
    d["scenarios"] = [{"name": "flat", "it_fraction": 0.6}, {"name": "profile", "profile": str(p)}]
    res = q.run(d, counterfactual=False)
    a, b = res.scenario("flat").metrics, res.scenario("profile").metrics
    assert b["pue"] == pytest.approx(a["pue"], rel=1e-12)


def test_profile_repeat_and_kw(tmp_path):
    p = tmp_path / "week.csv"
    week = 2000 + 1000 * np.sin(np.arange(168) / 168 * 2 * np.pi)
    pd.DataFrame({"hour": np.arange(168), "kw": week}).to_csv(p, index=False)
    d = minimum("LC-ACC")
    d["scenarios"] = [{"name": "week", "profile": str(p), "units": "kW", "column": "kw", "repeat": True}]
    res = q.run(d, counterfactual=False)
    s = res.scenarios[0]
    assert s.metrics["it_kwh"] == pytest.approx(np.tile(week, 53)[:8760].sum(), rel=1e-12)
    assert any("repeated" in w for w in s.warnings)
    # annual PUE is energy weighted (REQ-C-M-1), not the mean of hourly PUE
    assert s.metrics["pue"] != pytest.approx(float(s.hourly.pue.mean()), rel=1e-6)
    with pytest.raises(ValueError):
        d["scenarios"][0]["repeat"] = False
        q.run(d, counterfactual=False)


# Outputs and transparency ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def res_small():
    return q.run(minimum("LC-ACC-IFC-AD", ghg={"electricity_kg_per_kwh": 0.66, "diesel_kg_per_l": 2.7},
                         other={"generators": {"count": 4, "fuel_l_per_h": 300, "tests_per_year": 12}}))


@pytest.mark.parametrize("oset", ["nabers", "leed", "ssda", "design-check", "full"])
def test_export_output_sets(res_small, tmp_path, oset):
    w = q.export(res_small, tmp_path, formats=("csv", "md", "json", "xlsx"), output_set=oset, hourly=True,
                 charts=(oset == "nabers"))
    assert Path(w["md"]).exists() and Path(w["json"]).exists() and Path(w["xlsx"]).exists()
    assert (tmp_path / "calculation_report.md").read_text().count("S-EQ-03") >= 1
    assert (tmp_path / "input_register.csv").exists()
    hourly = pd.read_csv(tmp_path / "hourly" / "hourly_90pct.csv")
    assert len(hourly) == 8760 and "pue" in hourly.columns
    if oset == "ssda":
        assert "GHG" in Path(w["md"]).read_text()


def test_ghg_and_diesel(res_small):
    m = res_small.scenarios[0].metrics
    assert m["diesel_l"] == pytest.approx(4 * 300 * 12)
    assert m["ghg_diesel_t"] == pytest.approx(4 * 300 * 12 * 2.7 / 1000)
    assert m["pue"] == pytest.approx((m["it_kwh"] + m["infra_net_kwh"] + m["diesel_kwh"]) / m["it_kwh"])


def test_explain(res_small):
    txt = q.explain(res_small, "chillers", hour=4000)
    assert "S-EQ-03" in txt and "CAPFT" in txt
    assert "FFLP" in q.explain(res_small, "fwu_fans", hour=10)
    assert "PUE" in q.explain(res_small, "pue", hour=10)
    assert "UPS" in q.explain(res_small, "ups_loss_it", hour=10)


def test_determinism():
    d = minimum("LC-ACC-IFC")
    a = q.run(copy.deepcopy(d), ["90%"], counterfactual=False).scenarios[0].metrics
    b = q.run(copy.deepcopy(d), ["90%"], counterfactual=False).scenarios[0].metrics
    assert a == b


def test_cli(tmp_path):
    from click.testing import CliRunner

    from quickpue.cli import main

    import yaml

    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(minimum("LC-ACC")))
    r = CliRunner().invoke(main, ["validate", str(p)])
    assert r.exit_code == 0, r.output
    r = CliRunner().invoke(main, ["run", str(p), "--out", str(tmp_path / "o"), "--no-charts", "-f", "csv",
                                  "-o", "design-check"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "o" / "tables" / "OUT-12b.csv").exists()
    r = CliRunner().invoke(main, ["presets"])
    assert "LC-ACC-IFC-DUAL" in r.output
    r = CliRunner().invoke(main, ["export-eplus", str(p)])
    assert r.exit_code == 2


def test_python_input_file(tmp_path):
    p = tmp_path / "study.py"
    p.write_text(f"PROJECT = {minimum('LC-ACC')!r}\n")
    lp = q.load_project(p)
    assert lp.project.preset == "LC-ACC"
