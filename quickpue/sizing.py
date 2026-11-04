"""Default auto-sizing rules (requirements 8.4.2, S-DEF-05) driven by engine design passes.

Procedure: (1) provisional sizes from IT-proportional estimates; (2) design pass at the design
ambient (hour 0: installed IT; hour 1: sizing IT fraction); (3) final sizes from the design-pass
loads; (4) design pass again to obtain M1 group design loads.  Only fields left empty by the user
or the preset are sized; every sized value is recorded in the input register as an assumption.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np

from . import fluids, psychro
from .engine import DesignLoads, Engine
from .inputs import RegisterEntry
from .scenarios import ITInput
from .schema import FanPump, Project
from .weather import Weather, design_point

PUMP_W_PER_M3S = 348701.1  # S-DEF-02
FAN_W_PER_M3S_PA = 1.66667  # S-DEF-03
DEFAULT_PRESSURE_PA = {"FWU": 500.0, "CRAH": 400.0, "FCU": 300.0, "dry_cooler": 150.0}
DEFAULT_PUMP_HEAD_NOTE = "S-DEF-02: 348,701.1 W per m3/s (EnergyPlus Pump:VariableSpeed default, 22 W/gpm)"
RHO_CP_AIR = 1.2 * 1.006


@dataclass
class SizingLog:
    entries: list[RegisterEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def set(self, path, value, unit, rule):
        self.entries.append(RegisterEntry(path, value, unit, "assumption", rule, "auto-sized", "auto"))


def design_weather(w: Weather, spec) -> tuple[Weather, str]:
    db, wb, label = design_point(w, spec)
    p = float(psychro.pressure_at_altitude(w.elevation_m))
    dw = Weather.synthetic([db, db], t_wb=[wb, wb], p_kpa=p, start_weekday=1)
    dw.hour = np.array([12, 12])  # midday, weekday: peak lighting and occupancy
    return dw, f"{label}: {db:.1f} C DB / {wb:.1f} C WB"


def _design_it(project: Project, frac_list) -> ITInput:
    halls = project.halls
    it = {h.name: np.array([f * h.count * h.it_kw for f in frac_list]) for h in halls}
    lf = {h.name: np.full(len(frac_list), h.liquid_fraction) for h in halls}
    return ITInput("design", it, lf, np.array(frac_list), None)


def size_project(project: Project, weather: Weather, base_dir, log: SizingLog | None = None):
    """Return (sized project, design loads, design label, log)."""
    log = log or SizingLog()
    dw, label = design_weather(weather, project.weather.design_condition)
    sf = project.settings.sizing_it_fraction
    it_in = _design_it(project, [1.0, sf])
    # pass 1: provisional sizes from estimates
    est = _estimate_loads(project)
    p1 = _apply_sizes(project, est, dw, SizingLog(), provisional=True)
    eng = Engine(p1, base_dir, DesignLoads(served=est.served), weather)
    r1 = eng.simulate(dw, it_in)
    loads = _loads_from(r1)
    # pass 2: final sizes from design pass loads
    p2 = _apply_sizes(project, loads, dw, log, provisional=False)
    eng2 = Engine(p2, base_dir, DesignLoads(served=loads.served), weather)
    r2 = eng2.simulate(dw, it_in)
    loads2 = _loads_from(r2)
    # M1 design loads are taken at installed IT (hour 0) from the final design pass
    return p2, DesignLoads(served=loads2.served, sizing=loads2.sizing, extra={"design_label": label}), label, log, r2


def _loads_from(r) -> DesignLoads:
    served = {k: float(v[0]) for k, v in r.served.items()}
    sizing = {k: float(v[1]) for k, v in r.sizing_loads.items()}
    return DesignLoads(served=served, sizing=sizing)


def _estimate_loads(p: Project) -> DesignLoads:
    sz: dict[str, float] = {}
    served: dict[str, float] = {}
    for h in p.halls:
        it = h.count * h.it_kw
        sz[f"hall_liquid:{h.name}"] = it * h.liquid_fraction
        sz[f"hall_air:{h.name}"] = it * (1 - h.liquid_fraction) * 1.05
    for c in p.cdus:
        q = sum(sz[f"hall_liquid:{h}"] / max(1, sum(1 for x in p.cdus if h in x.serves)) for h in c.serves)
        sz[f"cdu:{c.name}"] = q
        served[f"{c.name} pump"] = q
    for f in p.fwus:
        q = sum(sz[f"hall_air:{h}"] / max(1, sum(1 for x in p.fwus if h in x.serves)) for h in f.serves)
        sz[f"fwu:{f.name}"] = q
        served[f"{f.name} fans"] = q
    it_tot = sum(h.count * h.it_kw for h in p.halls)
    for z in p.zones:
        sz[f"zone:{z.name}"] = max(0.01 * it_tot / max(len(p.zones), 1), 10.0)
    for r in p.room_units:
        sz[f"room_unit:{r.name}"] = sum(sz.get(f"zone:{(s if isinstance(s, str) else s.zone)}", 10.0)
                                        for s in r.serves)
        served[f"{r.name} fans"] = sz[f"room_unit:{r.name}"]
    for lp in p.loops:
        q = sum(sz[f"cdu:{c.name}"] for c in p.cdus if c.loop == lp.name)
        q += sum(sz[f"fwu:{f.name}"] for f in p.fwus if f.loop == lp.name) * 1.03
        sz[f"loop:{lp.name}"] = q * 1.02
    # children to parents
    tot = {lp.name: sz[f"loop:{lp.name}"] for lp in p.loops}
    for lp in p.loops:
        if lp.from_loop and lp.connection in ("blended", "hx"):
            tot[lp.from_loop] += tot[lp.name]
    for lp in p.loops:
        sz[f"loop:{lp.name}"] = tot[lp.name]
        rcp = fluids.rho_cp(lp.medium, lp.glycol_pct)
        sz[f"loop_flow:{lp.name}"] = tot[lp.name] / (rcp * (lp.return_c - lp.supply_c))
        served[f"{lp.name} primary pump"] = tot[lp.name]
        served[f"{lp.name} secondary pump"] = tot[lp.name]
    for pl in p.plants:
        sz[f"plant:{pl.name}"] = tot[pl.loop] * 1.02
        for c in pl.chillers:
            served[f"{c.name} integral pump"] = tot[pl.loop]
    sz["mech_ups"] = 0.05 * it_tot
    return DesignLoads(served=served, sizing=sz)


def _ceil(x):
    return int(math.ceil(x - 1e-9))


def _apply_sizes(project: Project, loads: DesignLoads, dw: Weather, log: SizingLog, provisional: bool) -> Project:
    p = copy.deepcopy(project)
    L = loads.sizing
    db = float(dw.t_db[0])
    wb = float(dw.t_wb[0])
    S = p.settings

    def g(key, default=0.0):
        return max(float(L.get(key, default)), 0.0)

    for h in p.halls:
        if h.area_m2 is None:
            h.area_m2 = h.it_kw / S.density_kw_per_m2
            log.set(f"halls[{h.name}].area_m2", h.area_m2, "m2",
                    f"IT density {S.density_kw_per_m2} kW/m2 (settings.density_kw_per_m2, assumption)")
    it_tot = sum(h.count * h.it_kw for h in p.halls)
    for z in p.zones:
        if z.area_m2 is None:
            z.area_m2 = max(0.02 * it_tot / z.count, 10.0)
            log.set(f"zones[{z.name}].area_m2", z.area_m2, "m2", "0.02 m2 per kW of installed IT (assumption)")
    loops = {lp.name: lp for lp in p.loops}
    # ---- FWUs
    for f in p.fwus:
        q = g(f"fwu:{f.name}")
        dt = f.air_dt_k
        if f.coil_capacity_kw is None and f.airflow_l_s:
            f.coil_capacity_kw = RHO_CP_AIR * dt * f.airflow_l_s / 1000.0
            log.set(f"fwus[{f.name}].coil_capacity_kw", f.coil_capacity_kw, "kW", "rho*cp*dT_air*airflow")
        if f.airflow_l_s is None:
            if f.coil_capacity_kw:
                f.airflow_l_s = f.coil_capacity_kw / (RHO_CP_AIR * dt) * 1000.0
                log.set(f"fwus[{f.name}].airflow_l_s", f.airflow_l_s, "L/s", "coil capacity / (rho*cp*dT_air)")
            else:
                f.airflow_l_s = 15000.0
                f.coil_capacity_kw = RHO_CP_AIR * dt * 15.0
                log.set(f"fwus[{f.name}].airflow_l_s", 15000.0, "L/s", "default unit airflow 15,000 L/s (assumption)")
                log.set(f"fwus[{f.name}].coil_capacity_kw", f.coil_capacity_kw, "kW", "rho*cp*dT_air*airflow")
        if f.duty is None:
            f.duty = max(1, _ceil(q / f.coil_capacity_kw)) if q > 0 else 1
            f.standby = f.standby or 1
            f.quantity = f.duty + f.standby
            log.set(f"fwus[{f.name}].quantity", f.quantity, "", f"N+1: duty = ceil(design air load {q:,.0f} kW / "
                    f"coil capacity) = {f.duty}, plus 1 standby (8.4.2)")
        if f.fan_power_kw is None:
            pa = f.static_pa or DEFAULT_PRESSURE_PA["FWU"]
            f.fan_power_kw = FAN_W_PER_M3S_PA * (f.airflow_l_s / 1000.0) * pa / 1000.0
            log.set(f"fwus[{f.name}].fan_power_kw", f.fan_power_kw, "kW",
                    f"S-DEF-03 1.66667 W/(m3/s Pa) x airflow x {pa:g} Pa"
                    + ("" if f.static_pa else " (default FWU pressure rise, assumption, Q6)"))
    # ---- CDUs
    for c in p.cdus:
        q = g(f"cdu:{c.name}")
        if c.capacity_kw is None:
            c.capacity_kw = 1500.0
            log.set(f"cdus[{c.name}].capacity_kw", 1500.0, "kW", "default CDU net capacity 1,500 kW (assumption)")
        if c.active is None:
            c.active = max(1, _ceil(q / c.capacity_kw)) if q > 0 else 1
            log.set(f"cdus[{c.name}].active", c.active, "", f"ceil(design liquid load {q:,.0f} kW / capacity)")
        if c.quantity is None:
            c.quantity = c.active + 1
            log.set(f"cdus[{c.name}].quantity", c.quantity, "", "N+1 (8.4.2)")
        if c.pump is None:
            c.pump = FanPump(power_kw=None)
        if c.pump.power_kw is None:
            flow = c.capacity_kw / (fluids.rho_cp("water") * 10.0)
            c.pump.flow_l_s = c.pump.flow_l_s or flow * 1000.0
            c.pump.power_kw = PUMP_W_PER_M3S * flow / 1000.0
            log.set(f"cdus[{c.name}].pump.power_kw", c.pump.power_kw, "kW",
                    f"{DEFAULT_PUMP_HEAD_NOTE} x TCS flow at 10 K")
        c.pump.duty = c.active
        c.pump.quantity = c.quantity
        c.pump.standby = c.quantity - c.active
    # ---- zones / room units
    for r in p.room_units:
        if r.type in ("OAF", "EAF", "DX_dehumidifier", "humidifier"):
            if r.duty is None:
                r.duty, r.quantity = 1, 1 + r.standby
            continue
        q = g(f"room_unit:{r.name}")
        if r.duty is None:
            r.duty = 1
            r.standby = r.standby or 1
            r.quantity = r.duty + r.standby
            log.set(f"room_units[{r.name}].quantity", r.quantity, "", "N+1 (assumption)")
        if r.capacity_kw is None:
            r.capacity_kw = max(q * 1.1 / max(r.duty, 1), 1.0)
            log.set(f"room_units[{r.name}].capacity_kw", r.capacity_kw, "kW",
                    f"design load {q:,.1f} kW x 1.1 / duty units (assumption)")
        if r.type in ("CRAH", "FCU") and r.fan_power_kw == 0 and r.airflow_l_s is None:
            r.airflow_l_s = r.capacity_kw / (RHO_CP_AIR * 10.0) * 1000.0
            pa = DEFAULT_PRESSURE_PA[r.type]
            r.fan_power_kw = FAN_W_PER_M3S_PA * (r.airflow_l_s / 1000.0) * pa / 1000.0
            log.set(f"room_units[{r.name}].fan_power_kw", r.fan_power_kw, "kW",
                    f"S-DEF-03 x airflow (capacity at 10 K) x {pa:g} Pa (assumption)")
    # ---- loop pumps
    for lp in p.loops:
        rcp = fluids.rho_cp(lp.medium, lp.glycol_pct)
        flow = g(f"loop_flow:{lp.name}") or g(f"loop:{lp.name}") / (rcp * (lp.return_c - lp.supply_c))
        for kind in ("primary_pump", "secondary_pump"):
            pump = getattr(lp, kind)
            if pump is None:
                continue
            if pump.flow_l_s is None:
                pump.flow_l_s = max(flow * 1000.0 / max(pump.duty, 1), 1e-3)
                log.set(f"loops[{lp.name}].{kind}.flow_l_s", pump.flow_l_s, "L/s",
                        "design loop flow at design dT / duty pumps")
            if pump.power_kw is None:
                pump.power_kw = PUMP_W_PER_M3S * pump.flow_l_s / 1000.0 / 1000.0
                log.set(f"loops[{lp.name}].{kind}.power_kw", pump.power_kw, "kW", DEFAULT_PUMP_HEAD_NOTE)
    # ---- plants
    for pl in p.plants:
        lp = loops[pl.loop]
        rcp = fluids.rho_cp(lp.medium, lp.glycol_pct)
        q = g(f"plant:{pl.name}") or g(f"loop:{pl.loop}")
        for c in pl.chillers:
            if c.duty is None:
                c.duty = 4
                c.standby = c.standby or 1
                c.quantity = c.duty + c.standby
                log.set(f"plants[{pl.name}].chillers[{c.name}].quantity", c.quantity, "", "N+1 with N = 4 (8.4.2)")
            share = c.duty / max(sum(x.duty or 4 for x in pl.chillers), 1)
            if c.capacity_kw is None:
                c.capacity_kw = max(q * share / c.duty, 1.0)
                log.set(f"plants[{pl.name}].chillers[{c.name}].capacity_kw", c.capacity_kw, "kW",
                        f"design plant load {q:,.0f} kW / N duty (8.4.2)")
            if c.rated_lwt_c is None:
                c.rated_lwt_c = lp.supply_c
                log.set(f"plants[{pl.name}].chillers[{c.name}].rated_lwt_c", c.rated_lwt_c, "C", "loop design supply")
            if c.rated_ect_c is None:
                c.rated_ect_c = (db + c.recirculation_k) if c.kind == "air_cooled" else 29.4
                log.set(f"plants[{pl.name}].chillers[{c.name}].rated_ect_c", c.rated_ect_c, "C",
                        "design ambient + recirculation" if c.kind == "air_cooled" else "29.4 C entering condenser "
                        "water (AHRI 550/590 standard rating, assumption)")
            if c.cop is None and c.power_kw is None:
                c.cop = 4.0 if c.kind == "air_cooled" else 6.5
                log.set(f"plants[{pl.name}].chillers[{c.name}].cop", c.cop, "",
                        "rated COP assumption to replace with manufacturer data (8.4.2)")
            if c.integral_pump is not None:
                ip = c.integral_pump
                if ip.flow_l_s is None:
                    ip.flow_l_s = c.capacity_kw / (rcp * (lp.return_c - lp.supply_c)) * 1000.0
                    log.set(f"plants[{pl.name}].chillers[{c.name}].integral_pump.flow_l_s", ip.flow_l_s, "L/s",
                            "chiller capacity at loop design dT")
                if ip.power_kw is None:
                    ip.power_kw = PUMP_W_PER_M3S * ip.flow_l_s / 1e6
                    log.set(f"plants[{pl.name}].chillers[{c.name}].integral_pump.power_kw", ip.power_kw, "kW",
                            DEFAULT_PUMP_HEAD_NOTE)
                ip.duty, ip.standby, ip.quantity = c.duty, c.standby, c.duty + c.standby
        cop = next((c.cop or (c.capacity_kw / c.power_kw) for c in pl.chillers), 5.0)
        q_rej = q * (1 + 1 / cop) if pl.chillers else q
        for d in pl.dry_coolers:
            if d.duty is None:
                d.duty = max(2, _ceil(q_rej / 1500.0))
                d.standby = d.standby or 1
                d.quantity = d.duty + d.standby
                log.set(f"plants[{pl.name}].dry_coolers[{d.name}].quantity", d.quantity, "",
                        "duty = max(2, ceil(design heat / 1,500 kW)) + 1 standby (assumption)")
            if d.rated_capacity_kw is None:
                d.rated_capacity_kw = max(q_rej / d.duty, 1.0)
                log.set(f"plants[{pl.name}].dry_coolers[{d.name}].rated_capacity_kw", d.rated_capacity_kw, "kW",
                        "design heat rejection / duty units")
            if d.rated_air_c is None:
                d.rated_air_c = db
                d.rated_water_out_c = db + 5.0
                dt = (lp.return_c - lp.supply_c) if pl.type != "CP-10" else 5.5
                d.rated_water_in_c = d.rated_water_out_c + dt
                log.set(f"plants[{pl.name}].dry_coolers[{d.name}].rated_air_c", db, "C",
                        "rated at design ambient with 5 K approach; UA back-calculated (8.4.2)")
            if d.fan_power_kw is None:
                c_w = d.rated_capacity_kw / (d.rated_water_in_c - d.rated_water_out_c)
                v = d.air_to_water_capacity_ratio * c_w / (1.2 * 1.006)
                d.fan_power_kw = FAN_W_PER_M3S_PA * v * DEFAULT_PRESSURE_PA["dry_cooler"] / 1000.0
                log.set(f"plants[{pl.name}].dry_coolers[{d.name}].fan_power_kw", d.fan_power_kw, "kW",
                        "S-DEF-03 x airflow x 150 Pa (assumption)")
        for t in pl.towers:
            if t.duty is None:
                t.duty = max(2, _ceil(q_rej / 3000.0))
                t.standby = t.standby or 1
                t.quantity = t.duty + t.standby
                log.set(f"plants[{pl.name}].towers[{t.name}].quantity", t.quantity, "",
                        "duty = max(2, ceil(design heat / 3,000 kW)) + 1 standby (assumption)")
            if t.rated_capacity_kw is None:
                t.rated_capacity_kw = max(q_rej / t.duty, 1.0)
                log.set(f"plants[{pl.name}].towers[{t.name}].rated_capacity_kw", t.rated_capacity_kw, "kW",
                        "design heat rejection / duty cells")
            if t.design_wb_c is None:
                t.design_wb_c = wb
                log.set(f"plants[{pl.name}].towers[{t.name}].design_wb_c", wb, "C", "design condition wet bulb")
        cw = pl.condenser_water
        if cw is not None and cw.pump is not None and pl.chillers:
            ch = pl.chillers[0]
            if cw.pump.flow_l_s is None:
                cw.pump.flow_l_s = ch.capacity_kw * (1 + 1 / (ch.cop or 6.5)) / (4.186 * cw.design_dt_k)
                log.set(f"plants[{pl.name}].condenser_water.pump.flow_l_s", cw.pump.flow_l_s, "L/s",
                        "condenser heat per chiller / (cp x design dT)")
            if cw.pump.power_kw is None:
                cw.pump.power_kw = PUMP_W_PER_M3S * cw.pump.flow_l_s / 1e6
                log.set(f"plants[{pl.name}].condenser_water.pump.power_kw", cw.pump.power_kw, "kW",
                        DEFAULT_PUMP_HEAD_NOTE)
            cw.pump.duty = sum(c.duty for c in pl.chillers)
            cw.pump.standby = sum(c.standby for c in pl.chillers)
            cw.pump.quantity = cw.pump.duty + cw.pump.standby
    # ---- UPS
    for u in p.electrical.ups:
        if u.module_kw is None:
            if u.path == "it":
                halls = [h for h in p.halls if "all" in u.serves or h.name in u.serves]
                load = sum(h.count * h.it_kw for h in halls)
                pdu = p.electrical.pdu.loss_fraction or (0.03 if p.project.metering_point == "B" else 0.0)
                load *= 1 + pdu
                rule = "installed IT of served halls (+PDU) / modules: UPS load fraction = IT fraction"
            else:
                load = max(g("mech_ups"), 1.0)
                rule = "design mechanical load on UPS / modules"
            u.module_kw = load / (u.modules * u.systems)
            log.set(f"electrical.ups[{u.name}].module_kw", u.module_kw, "kW", rule)
    return p
