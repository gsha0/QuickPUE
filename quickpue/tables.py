"""Core output tables OUT-1 to OUT-12 (requirements 13.2)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import end_use_label
from .weather import MONTH_NAMES, monthly_summary

TABLE_TITLES = {
    "OUT-1": "Scenario summary",
    "OUT-2": "End-use breakdown (base scenario)",
    "OUT-2c": "End-use breakdown, coarse (base scenario)",
    "OUT-3": "End-use breakdown per scenario (MWh/yr)",
    "OUT-4": "Monthly energy by end use (base scenario, MWh)",
    "OUT-5a": "Weather file parameters",
    "OUT-5b": "Monthly weather summary",
    "OUT-6a": "Input overview",
    "OUT-6b": "Input register",
    "OUT-6c": "Assumptions applied and pending items",
    "OUT-7a": "UPS efficiency tables",
    "OUT-7b": "Electrical loss summary",
    "OUT-8a": "Chiller configuration and data",
    "OUT-8b": "Plant operation and adiabatic summary",
    "OUT-9a": "CDU, FWU and room unit tables",
    "OUT-9b": "Fan and pump part-load models",
    "OUT-10": "Generator testing, jacket heaters, lifts, other loads and PV",
    "OUT-11": "Floor areas, internal loads, profiles and setpoints",
    "OUT-12a": "Design check: peak powers by end use",
    "OUT-12b": "Design check: installed vs required capacity",
    "OUT-12c": "Design check: unmet, minimum-speed and mode hours",
    "GHG": "Optional GHG estimate (user factors)",
}


def scenario_summary(res) -> pd.DataFrame:
    rows = []
    for s in res.scenarios:
        m = s.metrics
        pk = s.peaks["worst_hour"]
        r = {"Scenario": s.name, "Description": s.description, "IT energy (MWh)": m["it_kwh"] / 1e3,
             "Infrastructure electricity, net (MWh)": m["infra_net_kwh"] / 1e3,
             "Contingency (MWh)": m["contingency_kwh"] / 1e3, "PV credit (MWh)": m["pv_kwh"] / 1e3,
             "Diesel (MWh)": m["diesel_kwh"] / 1e3, "Diesel (L)": m["diesel_l"], "PUE": m["pue"],
             "pPUE cooling": m["ppue_cooling"], "Water (kL)": m["water_l"] / 1e3, "WUE (L/kWh)": m["wue"],
             "Peak hourly PUE": pk["pue"],
             "Peak hour": f"{pk['month']:02d}-{pk['day']:02d} h{pk['hour']:02d} ({pk['t_db']:.1f} C DB)",
             "Peak facility power (kW)": s.peaks["peak_facility_kw"]}
        if "ghg_total_t" in m:
            r["GHG (t CO2-e)"] = m["ghg_total_t"]
        rows.append(r)
    return pd.DataFrame(rows)


def end_use_table(s, coarse=False) -> pd.DataFrame:
    df = s.end_uses.copy()
    m = s.metrics
    df["MWh/yr"] = df.kwh / 1e3
    inf = df[df.boundary == "infrastructure"]
    tot_inf = inf.kwh.sum()
    if coarse:
        g = inf.groupby("group", sort=False).kwh.sum() / 1e3
        out = pd.DataFrame({"End use group": g.index, "Electricity (MWh/yr)": g.values})
        out["% of infrastructure"] = 100 * out["Electricity (MWh/yr)"] * 1e3 / tot_inf if tot_inf else 0
    else:
        out = pd.DataFrame({"End use": df.label, "Key": df.key, "Group": df.group, "Boundary": df.boundary,
                            "Electricity (MWh/yr)": df["MWh/yr"], "Peak (kW)": df.peak_kw})
        out["% of infrastructure"] = np.where(df.boundary == "infrastructure", 100 * df.kwh / tot_inf if tot_inf
                                              else 0, np.nan)
        out = out[out["Electricity (MWh/yr)"].abs() > 1e-9].reset_index(drop=True)
    extra = pd.DataFrame([
        {"End use" if not coarse else "End use group": "Total infrastructure electricity (gross + contingency)",
         "Electricity (MWh/yr)": (m["infra_gross_kwh"] + m["contingency_kwh"]) / 1e3},
        {"End use" if not coarse else "End use group": "PV generation (credit)", "Electricity (MWh/yr)": -m["pv_kwh"] / 1e3},
        {"End use" if not coarse else "End use group": "Infrastructure electricity, net",
         "Electricity (MWh/yr)": m["infra_net_kwh"] / 1e3},
        {"End use" if not coarse else "End use group": f"Diesel, generator testing ({m['diesel_l']:,.0f} L)",
         "Electricity (MWh/yr)": np.nan, "Diesel (MWh/yr)": m["diesel_kwh"] / 1e3, "Diesel (L/yr)": m["diesel_l"]},
        {"End use" if not coarse else "End use group": "IT electricity", "Electricity (MWh/yr)": m["it_kwh"] / 1e3},
        {"End use" if not coarse else "End use group": "PUE (energy ratio)", "Electricity (MWh/yr)": m["pue"]},
    ])
    return pd.concat([out, extra], ignore_index=True)


def per_scenario_table(res) -> pd.DataFrame:
    keys = []
    labels = {}
    for s in res.scenarios:
        for _, r in s.end_uses.iterrows():
            if r.key not in labels:
                keys.append(r.key)
                labels[r.key] = r.label
    data = {"End use": [labels[k] for k in keys]}
    for s in res.scenarios:
        e = dict(zip(s.end_uses.key, s.end_uses.kwh / 1e3))
        data[s.name] = [e.get(k, 0.0) for k in keys]
    df = pd.DataFrame(data)
    df = df[df.drop(columns="End use").abs().sum(axis=1) > 1e-9]
    tail = {"End use": ["Total infrastructure (net)", "PV credit", "Diesel (MWh)", "IT electricity", "PUE"]}
    for s in res.scenarios:
        m = s.metrics
        tail[s.name] = [m["infra_net_kwh"] / 1e3, -m["pv_kwh"] / 1e3, m["diesel_kwh"] / 1e3, m["it_kwh"] / 1e3,
                        m["pue"]]
    return pd.concat([df, pd.DataFrame(tail)], ignore_index=True)


def monthly_table(s) -> pd.DataFrame:
    h = s.hourly
    cols = [c for c in h.columns if c.startswith("eu:")]
    df = h.groupby("month")[cols + ["it_kw", "pv_kw"]].sum() / 1e3
    df.columns = [end_use_label(c[3:])[0] if c.startswith("eu:") else ("IT" if c == "it_kw" else "PV")
                  for c in df.columns]
    df.index = [MONTH_NAMES[i - 1] for i in df.index]
    df = df.loc[:, df.abs().sum() > 1e-9]
    return df.reset_index().rename(columns={"index": "Month"})


def weather_tables(res):
    w = res.weather
    info = pd.DataFrame([
        ("File", w.path.split("/")[-1]), ("Station", w.station_label()), ("Source", w.source),
        ("Latitude", w.latitude), ("Longitude", w.longitude), ("Elevation (m)", w.elevation_m),
        ("Time zone", w.timezone), ("Distance to site (km)", res.project.weather.distance_km),
        ("Design condition used for sizing", res.design_label),
        ("EPW design conditions", ", ".join(f"{k} {v}" for k, v in w.design.items() if k != "source")),
        ("Comments", " | ".join(w.comments)),
    ], columns=["Parameter", "Value"])
    return info, monthly_summary(w).round(1).reset_index().rename(columns={"index": "Month"})


def input_overview(res) -> pd.DataFrame:
    p = res.project
    rows = [("Project", p.project.name), ("Location", p.project.location), ("Preset", p.preset or "none"),
            ("Water system", p.water_system or ""), ("Workflow", p.project.workflow),
            ("Reference documents", "; ".join(p.project.reference_documents)),
            ("IT metering point", p.project.metering_point),
            ("Installed IT (kW)", sum(h.count * h.it_kw for h in p.halls)),
            ("Scenarios", ", ".join(s.name for s in p.scenario_list())),
            ("Contingency (%)", p.contingency.percent), ("UPS / PDU loss convention", p.electrical.loss_convention),
            ("Designer PUE estimate", p.project.designer_pue)]
    for h in p.halls:
        rows.append((f"Hall type {h.name}", f"{h.count} x {h.it_kw:,.0f} kW, liquid fraction {h.liquid_fraction:g}, "
                     f"cold aisle {h.cold_aisle_c:g} C"))
    for lp in p.loops:
        rows.append((f"Loop {lp.name}", f"{lp.supply_c:g} / {lp.return_c:g} C, {lp.medium} {lp.glycol_pct:g} %, "
                     f"{lp.connection}" + (f" from {lp.from_loop}" if lp.from_loop else "") + f", reset {lp.reset.type}"))
    for pl in p.plants:
        rows.append((f"Plant {pl.name}", f"{pl.type} serving {pl.loop}"))
    return pd.DataFrame(rows, columns=["Item", "Value"])


def register_table(res) -> pd.DataFrame:
    rows = [{"Path": e.path, "Value": e.value if not isinstance(e.value, float) else round(e.value, 6),
             "Unit": e.unit, "Source kind": e.kind, "Reference / basis": e.ref, "Note": e.note, "Origin": e.origin}
            for e in res.register]
    return pd.DataFrame(rows)


def assumptions_table(res) -> pd.DataFrame:
    rows = [{"Type": "Applied", "Item": a} for a in res.assumptions]
    for e in res.register:
        if e.kind in ("assumption", "pending_manufacturer"):
            rows.append({"Type": "pending manufacturer" if e.kind == "pending_manufacturer" else e.origin,
                         "Item": f"{e.path} = {e.value} {e.unit} ({e.ref})".strip()})
    for pl in res.project.plants:
        for c in pl.chillers:
            cs = c.curves
            if not cs.table and not (cs.capft and cs.eirft):
                rows.append({"Type": "pending manufacturer",
                             "Item": f"Chiller {c.name}: library curve analogue used (S-DEF-01); replace with "
                                     f"manufacturer data at project CHW temperatures"})
    return pd.DataFrame(rows)


def ups_tables(res):
    rows = []
    for u in res.project.electrical.ups:
        for x, e in u.efficiency:
            rows.append({"UPS": u.name, "Path": u.path, "Load fraction": x, "Efficiency": e})
    eff = pd.DataFrame(rows)
    loss_rows = []
    for s in res.scenarios:
        for k in ("pdu_loss", "ups_loss_it", "ups_loss_mech", "transformer_mvlv", "transformer_hv",
                  "distribution_loss"):
            v = s.end_uses[s.end_uses.key == k].kwh.sum()
            if v:
                loss_rows.append({"Scenario": s.name, "Element": end_use_label(k)[0], "MWh/yr": v / 1e3,
                                  "% of IT": 100 * v / s.metrics["it_kwh"]})
        for name, d in s.sim.detail.items():
            if name.startswith("loss:") and "load_frac" in d:
                loss_rows.append({"Scenario": s.name, "Element": f"{name[5:]} mean load fraction",
                                  "MWh/yr": np.nan, "% of IT": 100 * float(np.mean(d["load_frac"]))})
    return eff, pd.DataFrame(loss_rows)


def chiller_tables(res):
    rows = []
    eng = res.engine
    for pl in res.project.plants:
        rt = eng.plant_rt[pl.name]
        for c in rt["chillers"]:
            sp, m = c["spec"], c["model"]
            fc = c["fc"]
            rows.append({"Plant": pl.name, "Type": pl.type, "Chiller": m.name, "Kind": m.kind,
                         "Quantity": sp.quantity, "Duty": m.n_duty, "Standby": m.n_standby,
                         "Capacity (kW)": m.q_ref, "COP": m.cop_ref, "Rated LWT (C)": m.lwt_ref,
                         "Rated ECT (C)": m.ect_ref, "Min PLR": m.min_plr, "Below min": m.below_min,
                         "Curves": m.curves.source, "CAPFT": m.curves.capft.describe(),
                         "EIRFT": m.curves.eirft.describe(), "EIRFPLR": m.curves.eirfplr.describe(),
                         "Recirculation (K)": sp.recirculation_k, "Recirculation order": sp.recirculation_order,
                         "Adiabatic": (f"T_db {'>=' if sp.adiabatic.activation_inclusive else '>'} "
                                       f"{sp.adiabatic.activation_c:g} C, eff {sp.adiabatic.efficiency:g}"
                                       if sp.adiabatic and sp.adiabatic.enabled else "no"),
                         "Free cooling": (f"{fc['coil'].rated_q:,.0f} kW at {fc['coil'].rated_dt:g} K, fans "
                                          f"{fc['fan'].p_des_kw:g} kW" if fc else "no"),
                         "Integral pump": (f"{c['pump'].p_des_kw:g} kW x {c['pump'].n_energised}, "
                                           f"{c['pump'].describe()}" if c["pump"] else "no")})
        for d in rt["dry"]:
            rows.append({"Plant": pl.name, "Type": pl.type, "Chiller": f"Dry cooler {d['spec'].name}",
                         "Quantity": d["spec"].quantity, "Duty": d["spec"].duty,
                         "Capacity (kW)": d["spec"].rated_capacity_kw,
                         "Curves": f"UA {d['coil'].ua_des:.1f} kW/K, n {d['coil'].n_exp:g} (S-EQ-11)",
                         "Integral pump": f"fans {d['fan'].p_des_kw:g} kW/unit, {d['fan'].describe()}"})
        for t in rt["towers"]:
            rows.append({"Plant": pl.name, "Type": pl.type, "Chiller": f"Tower {t['spec'].name}",
                         "Quantity": t["spec"].quantity, "Duty": t["spec"].duty,
                         "Capacity (kW)": t["spec"].rated_capacity_kw,
                         "Curves": f"UA {t['unit'].ua_des:.1f} kW/K (S-EQ-10)",
                         "Integral pump": f"fans {t['fan'].p_des_kw:g} kW/unit, {t['fan'].describe()}"})
    cfg = pd.DataFrame(rows)
    op = []
    for s in res.scenarios:
        for name, d in s.sim.detail.items():
            if name.startswith("plant:"):
                mode = d["mode"]
                op.append({"Scenario": s.name, "Plant": name[6:], "Load (MWh)": d["q"].sum() / 1e3,
                           "Free cooling (MWh)": d["q_free_cooling"].sum() / 1e3,
                           "Full free cooling (h)": int((mode == 1).sum()), "Partial (h)": int((mode == 2).sum()),
                           "Mechanical (h)": int((mode == 3).sum()), "Adiabatic (h)": int(d["adiabatic"].sum()),
                           "Unmet (h)": int((d["unmet"] > 1e-3).sum()), "Water (kL)": d["water_l"].sum() / 1e3})
        cf = s.counterfactual
        if cf:
            op.append({"Scenario": s.name, "Plant": "Adiabatic counterfactual (REQ-C-IFC-4)",
                       "Load (MWh)": np.nan,
                       "Free cooling (MWh)": np.nan,
                       "Full free cooling (h)": np.nan,
                       "Partial (h)": np.nan, "Mechanical (h)": np.nan, "Adiabatic (h)": np.nan, "Unmet (h)": np.nan,
                       "Water (kL)": np.nan,
                       "Chiller MWh with pads": cf["chiller_kwh_with"] / 1e3,
                       "Chiller MWh dry": cf["chiller_kwh_dry"] / 1e3,
                       "Chiller reduction (%)": cf["chiller_reduction_pct"]})
    return cfg, pd.DataFrame(op)


def equipment_tables(res):
    p = res.project
    eng = res.engine
    rows = []
    for c in p.cdus:
        g = eng.cdu_groups.get(c.name)
        rows.append({"Type": "CDU", "Name": c.name, "Serves": ", ".join(c.serves), "Loop": c.loop,
                     "Quantity": c.quantity, "Active / duty": c.active, "Capacity (kW)": c.capacity_kw,
                     "Power per unit (kW)": g.p_des_kw if g else 0, "Part-load model": g.describe() if g else "",
                     "On UPS": c.pump.on_ups if c.pump else False})
    for f in p.fwus:
        g = eng.fwu_groups.get(f.name)
        rows.append({"Type": "FWU", "Name": f.name, "Serves": ", ".join(f.serves), "Loop": f.loop,
                     "Quantity": f.quantity, "Active / duty": f.duty, "Capacity (kW)": f.coil_capacity_kw,
                     "Airflow (L/s)": f.airflow_l_s, "Power per unit (kW)": f.fan_power_kw,
                     "Part-load model": g.describe() if g else "", "On UPS": f.on_ups})
    for r in p.room_units:
        g = eng.ru_groups.get(r.name)
        rows.append({"Type": r.type, "Name": r.name,
                     "Serves": ", ".join(s if isinstance(s, str) else f"{s.zone} ({s.share:g})" for s in r.serves),
                     "Loop": r.loop or "", "Quantity": r.quantity, "Active / duty": r.duty,
                     "Capacity (kW)": r.capacity_kw, "Airflow (L/s)": r.airflow_l_s,
                     "Power per unit (kW)": r.fan_power_kw or r.power_kw, "COP": r.cop if r.type in (
                         "CRAC", "PAC", "VRF", "split") else None,
                     "Part-load model": g.describe() if g else ("activation " + r.activation), "On UPS": r.on_ups})
    t1 = pd.DataFrame(rows)
    rows = []
    from .runner import _all_groups

    groups = _all_groups(eng)
    for rt in eng.plant_rt.values():
        for c in rt["chillers"]:
            if c["fc"]:
                groups.append(c["fc"]["fan"])
        for d in rt["dry"]:
            groups.append(d["fan"])
        for t in rt["towers"]:
            groups.append(t["fan"])
        if rt["cw_pump"]:
            groups.append(rt["cw_pump"])
    for g in groups:
        rows.append({"Group": g.name, "End use": end_use_label(g.end_use)[0], "P_des per unit (kW)": g.p_des_kw,
                     "Design flow per unit (L/s)": g.v_des_m3s * 1000 if g.v_des_m3s else None,
                     "Duty": g.n_duty, "Standby": g.n_standby, "Redundancy": g.redundancy, "Method": g.method,
                     "Curve": g.curve.describe(), "f_min": g.f_min, "Running rule": g.rule,
                     "M1 design load (kW)": g.design_load_kw if g.method == "M1" else None,
                     "k_drive": "yes" if g.drive else "no", "On UPS": g.on_ups})
    return t1, pd.DataFrame(rows)


def other_tables(res) -> pd.DataFrame:
    o = res.project.other
    rows = []
    s0 = res.scenarios[0]
    if o.generators and o.generators.count:
        g = o.generators
        rows.append({"Item": "Generator testing", "Inputs": f"Format {g.format}: {g.count} gens, "
                     f"{g.fuel_l_per_h} L/h, {g.hours_per_test} h x {g.tests_per_year}/yr",
                     "Annual": f"{s0.sim.diesel_l:,.0f} L = {s0.sim.diesel_kwh / 1e3:,.1f} MWh "
                               f"({g.diesel_mwh_per_l} MWh/L)"})
    if o.jacket_heaters and o.jacket_heaters.kw_per_generator:
        j = o.jacket_heaters
        e = s0.sim.eu.get("jacket_heaters")
        cnt = j.count if j.count is not None else (o.generators.count if o.generators else 0)
        eflh = e.sum() / (cnt * j.kw_per_generator) if e is not None and cnt else 0
        rows.append({"Item": "Jacket heaters", "Inputs": f"{j.kw_per_generator} kW x {cnt}; on below {j.t_on_c} C, "
                     f"off at {j.t_off_c} C" + (f"; EFLH override {j.eflh_hours} h" if j.eflh_hours else ""),
                     "Annual": f"EFLH {eflh:,.0f} h; {e.sum() / 1e3 if e is not None else 0:,.1f} MWh"})
    for k, v in s0.sim.annual_items.items():
        rows.append({"Item": k, "Inputs": "", "Annual": f"{v:,.0f} kWh"})
    for ld in o.loads:
        rows.append({"Item": f"Load {ld.name} ({ld.end_use})", "Inputs": f"{ld.kw} kW" if ld.kw is not None
                     else f"{ld.annual_kwh:,.0f} kWh/yr", "Annual": ""})
    if o.pv:
        rows.append({"Item": "PV", "Inputs": str(o.pv.model_dump(exclude_none=True)),
                     "Annual": f"{s0.metrics['pv_kwh']:,.0f} kWh (hourly shape from EPW GHI)"})
    return pd.DataFrame(rows)


def space_table(res) -> pd.DataFrame:
    rows = []
    p = res.project
    for h in p.halls:
        rows.append({"Space": h.name, "Category": "data hall", "Count": h.count, "Area each (m2)": h.area_m2,
                     "Total area (m2)": (h.area_m2 or 0) * h.count, "Setpoint (C)": h.cold_aisle_c,
                     "Lighting (W/m2)": h.lighting_w_m2, "Lighting profile": str(h.lighting_profile),
                     "m2/person": h.occupancy_m2_per_person, "Equipment (W/m2)": 0,
                     "Infiltration (ACH)": 0, "Losses received": ", ".join(f"{k} {v:g}" for k, v in h.losses.items())})
    for z in p.zones:
        rows.append({"Space": z.name, "Category": z.category, "Count": z.count, "Area each (m2)": z.area_m2,
                     "Total area (m2)": z.area_m2 * z.count, "Setpoint (C)": z.setpoint_c,
                     "Lighting (W/m2)": z.lighting_w_m2, "Lighting profile": str(z.lighting_profile),
                     "m2/person": z.occupancy_m2_per_person, "Equipment (W/m2)": z.equipment_w_m2,
                     "Infiltration (ACH)": z.infiltration_ach if z.infiltration_ach is not None else
                     ("0 (pressurised)" if z.pressurised else "default"),
                     "Losses received": ", ".join(f"{k} {v:g}" for k, v in z.losses.items())})
    return pd.DataFrame(rows)


def design_check_tables(res):
    peaks = []
    caps = []
    hours = []
    for s in res.scenarios:
        for _, r in s.end_uses.iterrows():
            if r.peak_kw > 0:
                peaks.append({"Scenario": s.name, "End use": r.label, "Peak (kW)": r.peak_kw})
    s0 = max(res.scenarios, key=lambda s: s.metrics["it_kwh"])
    p = res.project
    dl = res.design_loads.sizing
    for pl in p.plants:
        q = dl.get(f"plant:{pl.name}", 0.0)
        db, wb = res.design_db_wb
        for c in pl.chillers:
            m = next(x["model"] for x in res.engine.plant_rt[pl.name]["chillers"] if x["model"].name == c.name)
            lp = next(x for x in p.loops if x.name == pl.loop)
            tc = db + c.recirculation_k if c.kind == "air_cooled" else m.ect_ref
            avail = float(m.capacity(lp.supply_c, tc))
            inst_n = c.duty * c.capacity_kw
            inst_n1 = (c.duty + c.standby) * c.capacity_kw
            caps.append({"Equipment": f"Chillers {c.name}", "Required at design (kW)": q,
                         "Installed N (kW)": inst_n, "Installed N+x (kW)": inst_n1,
                         "Available N at design (kW)": c.duty * avail,
                         "Margin N (%)": 100 * (c.duty * avail / q - 1) if q else np.nan,
                         "Note": f"available = N x Q_ref x CAPFT({lp.supply_c:g} C, {tc:.1f} C) at the design "
                                 f"ambient (dry, incl. recirculation)"})
    for c in p.cdus:
        q = dl.get(f"cdu:{c.name}", 0.0)
        caps.append({"Equipment": f"CDU {c.name}", "Required at design (kW)": q,
                     "Installed N (kW)": (c.active or 0) * (c.capacity_kw or 0),
                     "Installed N+x (kW)": (c.quantity or 0) * (c.capacity_kw or 0),
                     "Margin N (%)": 100 * ((c.active or 0) * (c.capacity_kw or 0) / q - 1) if q else np.nan})
    for f in p.fwus:
        q = dl.get(f"fwu:{f.name}", 0.0)
        caps.append({"Equipment": f"FWU {f.name}", "Required at design (kW)": q,
                     "Installed N (kW)": (f.duty or 0) * (f.coil_capacity_kw or 0),
                     "Installed N+x (kW)": (f.quantity or 0) * (f.coil_capacity_kw or 0),
                     "Margin N (%)": 100 * ((f.duty or 0) * (f.coil_capacity_kw or 0) / q - 1) if q else np.nan})
    for r in p.room_units:
        q = dl.get(f"room_unit:{r.name}")
        if q is None or not r.capacity_kw:
            continue
        caps.append({"Equipment": f"{r.type} {r.name}", "Required at design (kW)": q,
                     "Installed N (kW)": (r.duty or 0) * r.capacity_kw,
                     "Installed N+x (kW)": (r.quantity or 0) * r.capacity_kw,
                     "Margin N (%)": 100 * ((r.duty or 0) * r.capacity_kw / q - 1) if q else np.nan})
    for s in res.scenarios:
        for name, d in s.sim.detail.items():
            row = None
            if "unmet" in d and isinstance(d["unmet"], np.ndarray):
                row = {"Scenario": s.name, "Item": name, "Unmet (h)": int((d["unmet"] > 1e-3).sum()),
                       "Unmet (MWh)": float(d["unmet"].sum() / 1e3)}
            if "f" in d and "f_eff" in d and "n_run" in d:
                on = d["n_run"] > 0
                row = row or {"Scenario": s.name, "Item": name}
                row["At minimum speed (h)"] = int(((d["f"] < d["f_eff"] - 1e-9) & on).sum())
                row["Running (h)"] = int(on.sum())
            if "mode" in d:
                row = row or {"Scenario": s.name, "Item": name}
                for k, lab in ((1, "Full FC (h)"), (2, "Partial (h)"), (3, "Mechanical (h)")):
                    row[lab] = int((d["mode"] == k).sum())
            if row:
                hours.append(row)
        for k, v in s.sim.cols.items():
            if k.startswith("zone_unmet_kw:"):
                hours.append({"Scenario": s.name, "Item": f"zone:{k.split(':', 1)[1]}",
                              "Unmet (h)": int((v > 1e-3).sum()), "Unmet (MWh)": float(v.sum() / 1e3)})
    return pd.DataFrame(peaks), pd.DataFrame(caps), pd.DataFrame(hours)


def ghg_table(res) -> pd.DataFrame:
    rows = []
    for s in res.scenarios:
        m = s.metrics
        if "ghg_total_t" not in m:
            continue
        rows.append({"Scenario": s.name, "Electricity incl. IT, net (MWh)": (m["it_kwh"] + m["infra_net_kwh"]) / 1e3,
                     "Diesel (L)": m["diesel_l"], "Electricity factor (kg/kWh)": res.project.ghg.electricity_kg_per_kwh,
                     "Diesel factor (kg/L)": res.project.ghg.diesel_kg_per_l,
                     "Electricity GHG (t)": m["ghg_electricity_t"], "Diesel GHG (t)": m["ghg_diesel_t"],
                     "Total GHG (t CO2-e)": m["ghg_total_t"]})
    return pd.DataFrame(rows)


def all_tables(res) -> dict[str, pd.DataFrame]:
    base = res.scenarios[0]
    t = {"OUT-1": scenario_summary(res), "OUT-2": end_use_table(base), "OUT-2c": end_use_table(base, coarse=True),
         "OUT-3": per_scenario_table(res), "OUT-4": monthly_table(base)}
    t["OUT-5a"], t["OUT-5b"] = weather_tables(res)
    t["OUT-6a"] = input_overview(res)
    t["OUT-6b"] = register_table(res)
    t["OUT-6c"] = assumptions_table(res)
    t["OUT-7a"], t["OUT-7b"] = ups_tables(res)
    t["OUT-8a"], t["OUT-8b"] = chiller_tables(res)
    t["OUT-9a"], t["OUT-9b"] = equipment_tables(res)
    t["OUT-10"] = other_tables(res)
    t["OUT-11"] = space_table(res)
    t["OUT-12a"], t["OUT-12b"], t["OUT-12c"] = design_check_tables(res)
    t["GHG"] = ghg_table(res)
    return t
