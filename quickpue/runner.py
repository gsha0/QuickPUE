"""Run orchestration and metrics (REQ-UI-1, Section 10.12)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .engine import COOLING_GROUPS, DesignLoads, Engine, SimResult, end_use_label
from .inputs import LoadedProject, RegisterEntry, load_project
from .scenarios import ITInput, build_it_input
from .schema import SCHEMA_VERSION, Project
from .sizing import SizingLog, size_project
from .weather import Weather, read_epw


@dataclass
class ScenarioResult:
    name: str
    description: str
    it: ITInput
    sim: SimResult
    hourly: pd.DataFrame
    end_uses: pd.DataFrame  # key, label, group, boundary, kwh, peak_kw
    metrics: dict
    peaks: dict
    warnings: list[str]
    counterfactual: dict | None = None
    runtime_s: float = 0.0


@dataclass
class Results:
    project: Project  # sized project
    loaded: LoadedProject
    weather: Weather
    scenarios: list[ScenarioResult]
    design_loads: DesignLoads
    design_label: str
    register: list[RegisterEntry]
    warnings: list[str]
    assumptions: list[str]
    design_pass: SimResult | None = None
    version: str = __version__
    schema_version: str = SCHEMA_VERSION
    engine: Engine | None = None

    def scenario(self, name: str) -> ScenarioResult:
        for s in self.scenarios:
            if s.name == name:
                return s
        raise KeyError(name)

    def summary(self) -> pd.DataFrame:
        rows = []
        for s in self.scenarios:
            m = s.metrics
            rows.append({"Scenario": s.name, "IT (MWh)": m["it_kwh"] / 1e3,
                         "Infrastructure (MWh)": m["infra_net_kwh"] / 1e3, "Diesel (MWh)": m["diesel_kwh"] / 1e3,
                         "PUE": m["pue"], "pPUE cooling": m["ppue_cooling"], "WUE (L/kWh)": m["wue"],
                         "Peak PUE": s.peaks["worst_hour"]["pue"]})
        return pd.DataFrame(rows)


def prepare(lp: LoadedProject):
    p = lp.project
    epw = Path(p.weather.epw)
    if not epw.is_absolute():
        epw = lp.base_dir / epw
    w = read_epw(epw)
    log = SizingLog()
    sized, design, label, log, dres = size_project(p, w, lp.base_dir, log)
    eng = Engine(sized, lp.base_dir, design, w)
    return w, sized, design, label, log, eng, dres


def run(project, scenarios: list[str] | None = None, *, counterfactual: bool | None = None) -> Results:
    """Load (if needed), auto-size, simulate every scenario for 8,760 h and compute metrics."""
    lp = project if isinstance(project, LoadedProject) else load_project(project)
    w, sized, design, label, log, eng, dres = prepare(lp)
    register = _build_register(lp, sized, log)
    warnings = list(w.warnings)
    assumptions = list(lp.assumptions)
    scs = sized.scenario_list()
    if scenarios:
        scs = [s for s in scs if s.name in scenarios]
    do_cf = sized.settings.adiabatic_counterfactual if counterfactual is None else counterfactual
    has_adiabatic = any((c.adiabatic and c.adiabatic.enabled) for pl in sized.plants for c in pl.chillers) or any(
        (d.adiabatic and d.adiabatic.enabled) for pl in sized.plants for d in pl.dry_coolers)
    out = []
    for sc in scs:
        t0 = time.perf_counter()
        it = build_it_input(sc, sized.halls, lp.base_dir)
        sim = eng.simulate(w, it)
        sr = _scenario_result(sc.name, it, sim, sized, w)
        if do_cf and has_adiabatic:
            cf = eng.simulate(w, it, disable_adiabatic=True)
            sr.counterfactual = _counterfactual(sim, cf)
        sr.runtime_s = time.perf_counter() - t0
        out.append(sr)
    _missing_m1 = [g.name for g in _all_groups(eng) if g.auto_sized.get("design_load_missing")]
    if _missing_m1:
        warnings.append(f"M1 design load missing for {', '.join(_missing_m1)}; set part_load.design_load_kw")
    return Results(sized, lp, w, out, design, label, register, warnings + eng.warn_static, assumptions, dres,
                   engine=eng)


def _all_groups(eng: Engine):
    gs = list(eng.cdu_groups.values()) + list(eng.fwu_groups.values()) + list(eng.ru_groups.values())
    for d in eng.loop_pumps.values():
        gs += [g for g in d.values() if g is not None]
    for rt in eng.plant_rt.values():
        for c in rt["chillers"]:
            if c["pump"] is not None:
                gs.append(c["pump"])
    return [g for g in gs if g is not None]


# ---------------------------------------------------------------------------
def _scenario_result(name, it: ITInput, sim: SimResult, p: Project, w: Weather) -> ScenarioResult:
    n = sim.n
    excluded = set(p.boundary.excluded)
    rows = []
    infra_hourly = np.zeros(n)
    for key, arr in sim.eu.items():
        label, group = end_use_label(key)
        boundary = "excluded" if (key in excluded or sim.eu_boundary.get(key) == "excluded") else "infrastructure"
        rows.append({"key": key, "label": label, "group": group, "boundary": boundary, "kwh": float(arr.sum()),
                     "peak_kw": float(arr.max()) if len(arr) else 0.0})
        if boundary == "infrastructure":
            infra_hourly += arr
    it_kw = sum(it.it_kw.values())
    e_it = float(it_kw.sum())
    gross = float(infra_hourly.sum())
    pv_kwh = float(sim.pv_kw.sum())
    c = p.contingency
    base = gross if c.basis == "gross" else gross - pv_kwh
    cont_kwh = base * c.percent / 100.0
    cont_hourly = (infra_hourly if c.basis == "gross" else infra_hourly - sim.pv_kw) * c.percent / 100.0
    rows.append({"key": "contingency", "label": f"Design contingency ({c.percent:g} %)", "group": "Contingency",
                 "boundary": "infrastructure", "kwh": cont_kwh, "peak_kw": float(cont_hourly.max())})
    df = pd.DataFrame(rows)
    infra_net = gross + cont_kwh - pv_kwh
    diesel = sim.diesel_kwh
    pue = (e_it + infra_net + diesel) / e_it if e_it > 0 else float("nan")
    cooling = float(df[df.group.isin(COOLING_GROUPS) & (df.boundary == "infrastructure")].kwh.sum())
    ppue = (e_it + cooling) / e_it if e_it > 0 else float("nan")
    water = float(sim.water_l.sum())
    metrics = {
        "it_kwh": e_it, "infra_gross_kwh": gross, "contingency_kwh": cont_kwh, "pv_kwh": pv_kwh,
        "infra_net_kwh": infra_net, "diesel_kwh": diesel, "diesel_l": sim.diesel_l,
        "facility_kwh": e_it + infra_net + diesel, "pue": pue, "ppue_cooling": ppue, "cooling_kwh": cooling,
        "water_l": water, "wue": water / e_it if e_it > 0 else float("nan"),
        "excluded_kwh": float(df[df.boundary == "excluded"].kwh.sum()),
        "iterations": sim.iterations, "nonconverged_hours": int(sim.nonconverged.sum()),
    }
    if p.ghg.electricity_kg_per_kwh is not None or p.ghg.diesel_kg_per_l is not None:
        ef_e = p.ghg.electricity_kg_per_kwh or 0.0
        ef_d = p.ghg.diesel_kg_per_l or 0.0
        metrics["ghg_electricity_t"] = (e_it + infra_net) * ef_e / 1000.0
        metrics["ghg_diesel_t"] = sim.diesel_l * ef_d / 1000.0
        metrics["ghg_total_t"] = metrics["ghg_electricity_t"] + metrics["ghg_diesel_t"]
    # hourly PUE (REQ-C-M-2): annual-only diesel spread evenly or kept separate
    diesel_h = np.full(n, diesel / n) if p.settings.annual_items_hourly == "spread" else np.zeros(n)
    infra_h_net = infra_hourly + cont_hourly - sim.pv_kw
    with np.errstate(divide="ignore", invalid="ignore"):
        pue_h = np.where(it_kw > 0, (it_kw + infra_h_net + diesel_h) / it_kw, np.nan)
    # energy balance closure (REQ-C-5)
    hin, rem = sim.ledger["heat_in"], sim.ledger["removed"]
    with np.errstate(divide="ignore", invalid="ignore"):
        bal = np.where(np.abs(hin) > 1e-6, (hin - rem) / np.abs(hin), 0.0)
    bad = np.abs(bal) > p.settings.balance_tolerance
    metrics["balance_max_rel_error"] = float(np.nanmax(np.abs(bal))) if n else 0.0
    metrics["balance_flagged_hours"] = int(bad.sum())
    # peaks (REQ-C-M-3)
    i = int(np.nanargmax(pue_h))
    peaks = {"worst_hour": {"hour_index": i, "month": int(w.month[i]), "day": int(w.day[i]), "hour": int(w.hour[i]),
                            "pue": float(pue_h[i]), "t_db": float(w.t_db[i]), "t_wb": float(w.t_wb[i]),
                            "it_kw": float(it_kw[i]), "infra_kw": float(infra_h_net[i])},
             "peak_infra_kw": float(infra_h_net.max()), "peak_facility_kw": float((it_kw + infra_h_net).max())}
    hourly = _hourly_frame(sim, w, it_kw, infra_h_net, pue_h, bal, it)
    warns = list(sim.warnings) + it.warnings + _derived_warnings(sim, p, bad)
    return ScenarioResult(name, it.description, it, sim, hourly, df, metrics, peaks, warns)


def _counterfactual(sim: SimResult, cf: SimResult) -> dict:
    keys = ("chillers", "free_cooling_fans", "heat_rejection_fans")
    a = sum(float(sim.eu.get(k, np.zeros(1)).sum()) for k in keys)
    b = sum(float(cf.eu.get(k, np.zeros(1)).sum()) for k in keys)
    ach = float(sim.eu.get("chillers", np.zeros(1)).sum())
    bch = float(cf.eu.get("chillers", np.zeros(1)).sum())
    tot_a = sum(float(v.sum()) for v in sim.eu.values())
    tot_b = sum(float(v.sum()) for v in cf.eu.values())
    return {"chiller_kwh_with": ach, "chiller_kwh_dry": bch,
            "chiller_reduction_pct": 100.0 * (bch - ach) / bch if bch > 0 else 0.0,
            "plant_kwh_with": a, "plant_kwh_dry": b, "infra_kwh_with": tot_a, "infra_kwh_dry": tot_b,
            "water_l": float(sim.water_l.sum())}


def _hourly_frame(sim, w, it_kw, infra, pue_h, bal, it):
    data = {"month": w.month, "day": w.day, "hour": w.hour, "t_db": w.t_db, "t_wb": w.t_wb, "t_dp": w.t_dp,
            "rh": w.rh, "it_fraction": it.it_fraction, "it_kw": it_kw}
    for k, v in sim.eu.items():
        data[f"eu:{k}"] = v
    data["infra_net_kw"] = infra
    data["pv_kw"] = sim.pv_kw
    data["pue"] = pue_h
    data["water_l_h"] = sim.water_l
    data.update(sim.cols)
    for name, d in sim.detail.items():
        for k, v in d.items():
            if isinstance(v, np.ndarray) and v.shape == (sim.n,):
                data[f"{name}:{k}"] = v.astype(float) if v.dtype == bool else v
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, np.ndarray) and vv.shape == (sim.n,):
                        data[f"{name}:{k}:{kk}"] = vv
    data["balance_rel_error"] = bal
    data["nonconverged"] = sim.nonconverged.astype(int)
    return pd.DataFrame(data)


def _derived_warnings(sim: SimResult, p: Project, bad) -> list[str]:
    out = []
    n = sim.n
    S = p.settings
    for name, d in sim.detail.items():
        kind, _, nm = name.partition(":")
        if kind == "plant":
            um = d["unmet"]
            if (um > 1e-3).any():
                out.append(f"Plant {nm}: unmet load in {int((um > 1e-3).sum())} h, {um.sum() / 1e3:,.1f} MWh; "
                           f"supply temperature drifts above setpoint (REQ-C-3)")
        if kind == "chiller":
            if d["out_of_range"].any():
                out.append(f"Chiller {nm}: curves evaluated outside validity in {int(d['out_of_range'].sum())} h "
                           f"(inputs clamped; REQ-C-CH-6)")
            run_h = int((d["n_run"] > 0).sum())
            bm = int(d["below_min"].sum())
            if run_h and bm / run_h > S.chiller_below_min_warning_share:
                out.append(f"Chiller {nm}: below minimum PLR in {bm} of {run_h} running hours")
            su = int((d["standby_used"] > 0).sum())
            if su:
                out.append(f"Chiller {nm}: standby units needed in {su} h (capacity shortfall on duty units)")
        if kind in ("pump", "fwu", "room_unit", "cdu") and "f" in d and "f_eff" in d and "n_run" in d:
            on = d["n_run"] > 0
            if on.any():
                at_min = (d["f"] < d["f_eff"] - 1e-9) & on
                share = at_min.sum() / on.sum()
                if share > S.min_speed_warning_share:
                    out.append(f"{kind} {nm}: at minimum flow fraction in {100 * share:.0f} % of running hours "
                               f"(bypass / surplus flow reported)")
        if kind == "fwu" and "overload" in d and d["overload"].any():
            out.append(f"FWU {nm}: coil load above running coil capacity in {int(d['overload'].sum())} h")
        if kind == "cdu":
            if "overload" in d and d["overload"].any():
                out.append(f"CDU {nm}: load above active capacity in {int(d['overload'].sum())} h")
            if "tcs_drift" in d and (d["tcs_drift"] > 0.05).any():
                out.append(f"CDU {nm}: TCS supply above setpoint in {int((d['tcs_drift'] > 0.05).sum())} h "
                           f"(max {d['tcs_drift'].max():.1f} K; REQ-C-CDU-5)")
        if kind == "room_unit" and "unmet" in d and (d["unmet"] > 1e-3).any():
            out.append(f"Room unit {nm}: unmet load in {int((d['unmet'] > 1e-3).sum())} h "
                       f"({d['unmet'].sum() / 1e3:,.1f} MWh)")
        if kind == "tower" and d["saturated"].any():
            out.append(f"Tower {nm}: at full fan without reaching target in {int(d['saturated'].sum())} h")
    for k, v in sim.cols.items():
        if k.startswith("zone_unmet_kw:") and (v > 1e-3).any():
            out.append(f"Zone {k.split(':', 1)[1]}: unmet cooling in {int((v > 1e-3).sum())} h")
        if k.startswith("zone_heating_kw:") and (v > 1e-3).any():
            out.append(f"Zone {k.split(':', 1)[1]}: net heat loss (heating not modelled) in {int((v > 1e-3).sum())} h")
    if bad.any():
        out.append(f"Energy balance closure above tolerance in {int(bad.sum())} h (REQ-C-5)")
    # glycol check: loops whose water passes outdoor coils (dry coolers, free cooling coils)
    from .fluids import freezing_point
    outdoor_loops = {pl.loop for pl in p.plants
                     if pl.dry_coolers or any(c.free_cooling is not None and c.free_cooling.enabled
                                              for c in pl.chillers)}
    t_min = float(sim.cols.get("_t_db_min", np.array([np.nan]))[0]) if "_t_db_min" in sim.cols else None
    for lp in p.loops:
        if lp.name in outdoor_loops and t_min is not None and t_min < freezing_point(lp.medium, lp.glycol_pct) + 1.0:
            out.append(f"Loop {lp.name}: outdoor coils see {t_min:.1f} C, below the {lp.medium} "
                       f"({lp.glycol_pct:g} %) freezing point + 1 K; glycol missing or insufficient")
    return out


def _build_register(lp: LoadedProject, sized: Project, log: SizingLog) -> list[RegisterEntry]:
    reg = dict(lp.register)
    for e in log.entries:
        reg[e.path] = e
    # pydantic defaults applied by the tool (REQ-ATTR-2): top-level sections only, to keep it readable
    out = sorted(reg.values(), key=lambda e: e.path)
    return out
