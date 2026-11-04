"""Quasi-steady hourly engine (requirements 5.1, 10.2).

All 8,760 hours are solved as numpy vectors.  Hours are independent; the coupling between
infrastructure power, electrical losses, room heat gains and cooling power is resolved by a
fixed-point iteration over the whole year (relaxation and tolerance from the settings).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import fluids, psychro, schedules
from .chiller import (ChillerModel, DEFAULT_LIBRARY, curves_from_coefficients, curves_from_library,
                      curves_from_table, dispatch)
from .curves import PolyPLR, Table1D, make_fflp
from .heatx import (AirWaterCoil, CoolingTowerUnit, adiabatic_temperature, bisect, evaporative_water_kg_s,
                    tower_evaporation_kg_s)
from .partload import FanPumpGroup, build_group
from .scenarios import ITInput
from .schema import FanPump, PartLoad, Project
from .weather import Weather

CP_AIR = 1.006

END_USES: dict[str, tuple[str, str]] = {
    # key: (label, coarse group)
    "chillers": ("Chillers (compressors and condenser fans)", "Cooling plant"),
    "free_cooling_fans": ("Free cooling fans (integrated free cooling)", "Cooling plant"),
    "heat_rejection_fans": ("Dry cooler / cooling tower fans", "Cooling plant"),
    "chw_pumps_integral": ("Chilled water pumps (chiller integral)", "Pumps"),
    "chw_pumps_primary": ("Loop primary pumps", "Pumps"),
    "chw_pumps_secondary": ("Loop secondary pumps", "Pumps"),
    "cw_pumps": ("Condenser water pumps", "Pumps"),
    "cdu_pumps": ("CDU pumps", "Pumps"),
    "fwu_fans": ("FWU fans", "Fans"),
    "crah_fans": ("CRAH fans", "Fans"),
    "fcu_fans": ("FCU / outdoor air unit fans", "Fans"),
    "dx_water_cooled": ("Water-cooled DX units (PAC)", "Room units"),
    "dx_air_cooled": ("Air-cooled DX units, VRF and split", "Room units"),
    "office_hvac": ("Office VRF and split units", "Room units"),
    "ventilation_fans": ("Ventilation / outdoor air fans", "Fans"),
    "exhaust_fans": ("Exhaust fans", "Fans"),
    "dehumidifiers": ("Dehumidifiers", "Room units"),
    "humidifiers": ("Humidifiers", "Room units"),
    "pdu_loss": ("PDU losses", "Electrical losses"),
    "ups_loss_it": ("UPS losses, IT path", "Electrical losses"),
    "ups_loss_mech": ("UPS losses, mechanical path", "Electrical losses"),
    "transformer_hv": ("Transformer losses HV", "Electrical losses"),
    "transformer_mvlv": ("Transformer losses MV/LV", "Electrical losses"),
    "distribution_loss": ("Switchboard and cable losses", "Electrical losses"),
    "lighting_dc": ("Data hall lighting", "Lighting"),
    "lighting_non_office": ("Non-office lighting", "Lighting"),
    "lighting_office": ("Office lighting", "Lighting"),
    "equipment_office": ("Office equipment", "Other"),
    "equipment_other": ("Other equipment", "Other"),
    "dhw": ("Domestic hot water", "Other"),
    "lifts": ("Lifts", "Other"),
    "ancillary": ("Ancillary / miscellaneous house power", "Other"),
    "jacket_heaters": ("Generator jacket heaters", "Other"),
}

COOLING_GROUPS = {"Cooling plant", "Pumps", "Fans", "Room units"}


def end_use_label(key: str) -> tuple[str, str]:
    if key in END_USES:
        return END_USES[key]
    return key.replace("_", " ").capitalize(), "Other"


@dataclass
class DesignLoads:
    """Group loads from a design pass (hour 0 = installed IT at the design ambient)."""

    served: dict[str, float] = field(default_factory=dict)  # group name -> served load kW (M1 basis)
    sizing: dict[str, float] = field(default_factory=dict)  # item -> load kW at sizing IT fraction
    extra: dict[str, float] = field(default_factory=dict)


@dataclass
class SimResult:
    n: int
    cols: dict[str, np.ndarray]
    eu: dict[str, np.ndarray]
    eu_boundary: dict[str, str]
    detail: dict[str, dict[str, np.ndarray]]
    served: dict[str, np.ndarray]
    sizing_loads: dict[str, np.ndarray]
    iterations: int
    nonconverged: np.ndarray
    warnings: list[str]
    annual_items: dict[str, float]
    diesel_l: float
    diesel_kwh: float
    pv_kw: np.ndarray
    water_l: np.ndarray
    ledger: dict[str, np.ndarray]


def _ac(arr, n):
    return np.broadcast_to(np.asarray(arr, dtype=float), (n,)).astype(float)


class Engine:
    """Runtime model built from a fully sized project."""

    def __init__(self, project: Project, base_dir: Path | None = None, design: DesignLoads | None = None,
                 weather: Weather | None = None):
        self.p = project
        self.base_dir = base_dir or Path(".")
        self.design = design or DesignLoads()
        self.weather = weather
        self.warn_static: list[str] = []
        self.halls = {h.name: h for h in project.halls}
        self.loops = {lp.name: lp for lp in project.loops}
        self.zones = {z.name: z for z in project.zones}
        self._check_links()
        self._build()

    # ------------------------------------------------------------------
    def _check_links(self):
        p = self.p
        for c in p.cdus:
            for h in c.serves:
                if h not in self.halls:
                    raise ValueError(f"CDU {c.name}: unknown hall {h!r}")
            if c.loop not in self.loops:
                raise ValueError(f"CDU {c.name}: unknown loop {c.loop!r}")
        for f in p.fwus:
            for h in f.serves:
                if h not in self.halls:
                    raise ValueError(f"FWU {f.name}: unknown hall {h!r}")
            if f.loop not in self.loops:
                raise ValueError(f"FWU {f.name}: unknown loop {f.loop!r}")
        for r in p.room_units:
            for s in r.serves:
                z = s if isinstance(s, str) else s.zone
                if z not in self.zones and z not in self.halls:
                    raise ValueError(f"room unit {r.name}: unknown zone {z!r}")
            if r.loop and r.loop not in self.loops:
                raise ValueError(f"room unit {r.name}: unknown loop {r.loop!r}")
        plant_loops = {}
        for pl in p.plants:
            if pl.loop not in self.loops:
                raise ValueError(f"plant {pl.name}: unknown loop {pl.loop!r}")
            if pl.loop in plant_loops:
                raise ValueError(f"loop {pl.loop}: served by two plants ({plant_loops[pl.loop]}, {pl.name})")
            plant_loops[pl.loop] = pl.name
            _validate_plant_type(pl)
        self.plant_of_loop = plant_loops
        for lp in p.loops:
            if lp.connection in ("blended", "hx", "split"):
                if lp.from_loop not in self.loops:
                    raise ValueError(f"loop {lp.name}: from_loop {lp.from_loop!r} unknown")
                if lp.connection == "split" and lp.name not in plant_loops:
                    raise ValueError(f"loop {lp.name}: split duty (DT-D) needs its own free-cooling plant")
            elif lp.name not in plant_loops:
                used = any(c.loop == lp.name for c in p.cdus) or any(f.loop == lp.name for f in p.fwus) or any(
                    r.loop == lp.name for r in p.room_units)
                if used:
                    raise ValueError(f"loop {lp.name}: no plant serves it (REQ-DM-4)")
        # orphan halls (no FWU) are allowed only with zero air load paths -> warning
        for h in p.halls:
            if h.liquid_fraction > 0 and not any(h.name in c.serves for c in p.cdus):
                raise ValueError(f"hall {h.name}: liquid fraction > 0 but no CDU serves it")
            if h.liquid_fraction < 1 and not any(h.name in f.serves for f in p.fwus) and not any(
                    h.name in [s if isinstance(s, str) else s.zone for s in r.serves] for r in p.room_units):
                self.warn_static.append(f"hall {h.name}: air-side heat has no FWU or room unit; reported as unmet")

    # ------------------------------------------------------------------
    def _group(self, name, end_use, spec: FanPump | None, **defaults) -> FanPumpGroup | None:
        if spec is None or not spec.power_kw:
            return None
        g = build_group(name, end_use, spec, **defaults)
        if g.method == "M1" and not g.design_load_kw:
            g.design_load_kw = self.design.served.get(name) or None
            if not g.design_load_kw:
                g.design_load_kw = 1.0
                g.auto_sized["design_load_missing"] = True
        return g

    def _build(self):
        p = self.p
        # loop properties
        self.loop_rcp = {lp.name: fluids.rho_cp(lp.medium, lp.glycol_pct) for lp in p.loops}  # kJ/m3K
        self.loop_dt = {lp.name: lp.return_c - lp.supply_c for lp in p.loops}
        self.loop_children = {lp.name: [] for lp in p.loops}
        for lp in p.loops:
            if lp.connection in ("blended", "hx", "split"):
                self.loop_children[lp.from_loop].append(lp.name)
        self.loop_order = self._topo_loops()
        # pumps on loops
        self.loop_pumps = {}
        for lp in p.loops:
            self.loop_pumps[lp.name] = {
                "primary": self._group(f"{lp.name} primary pump", "chw_pumps_primary", lp.primary_pump,
                                       default_method="M2", default_curve="K-DP(0.3)", default_f_min=0.3),
                "secondary": self._group(f"{lp.name} secondary pump", "chw_pumps_secondary", lp.secondary_pump,
                                         default_method="M2", default_curve="K-DP(0.3)", default_f_min=0.3),
            }
        # CDUs
        self.cdu_groups = {}
        for c in p.cdus:
            spec = c.pump
            if spec is not None:
                g = self._group(f"{c.name} pump", "cdu_pumps", spec, default_method="M3", default_curve="K-CONST",
                                default_f_min=0.0, n_duty=c.active, n_standby=(c.quantity or c.active) - c.active)
                self.cdu_groups[c.name] = g
        # FWUs
        self.fwu_groups = {}
        for f in p.fwus:
            spec = FanPump(power_kw=f.fan_power_kw or 0.0, flow_l_s=f.airflow_l_s, quantity=f.quantity, duty=f.duty,
                           standby=f.standby, redundancy=f.redundancy, part_load=f.part_load, on_ups=f.on_ups)
            self.fwu_groups[f.name] = self._group(f"{f.name} fans", "fwu_fans", spec, default_method="M2",
                                                  default_curve="K-VSM", default_f_min=0.3)
        # room units fans
        self.ru_groups = {}
        for r in p.room_units:
            if r.type in ("OAF", "EAF", "DX_dehumidifier", "humidifier"):
                continue
            if r.fan_power_kw > 0:
                default_method = "M2" if (r.type in ("CRAH", "FCU") and r.airflow_l_s) else "M3"
                default_curve = "K-VSM" if default_method == "M2" else "K-CONST"
                spec = FanPump(power_kw=r.fan_power_kw, flow_l_s=r.airflow_l_s, quantity=r.quantity, duty=r.duty,
                               standby=r.standby, redundancy=r.redundancy, part_load=r.fan_part_load,
                               on_ups=r.on_ups)
                self.ru_groups[r.name] = self._group(f"{r.name} fans", _ru_end_use(r, self.zones), spec,
                                                     default_method=default_method, default_curve=default_curve,
                                                     default_f_min=0.3 if default_method == "M2" else 0.0)
        # plants
        self.plant_rt = {pl.name: self._build_plant(pl) for pl in p.plants}
        # electrical
        e = p.electrical
        self.loss_conv = e.loss_convention
        pdu = e.pdu.loss_fraction
        if pdu is None:
            pdu = 0.03 if p.project.metering_point == "B" else 0.0
        self.pdu_frac = pdu
        self.ups_tables = {}
        for u in e.ups:
            xs = [float(a) for a, _ in u.efficiency]
            ys = [float(b) for _, b in u.efficiency]
            self.ups_tables[u.name] = Table1D(xs, ys, u.name)
        self._loss_alloc_static()

    def _topo_loops(self):
        order = []
        seen = set()

        def visit(n):
            if n in seen:
                return
            seen.add(n)
            for c in self.loop_children[n]:
                visit(c)
            order.append(n)

        for n in self.loop_children:
            visit(n)
        return order  # children before parents

    def _build_plant(self, pl):
        rt = {"plant": pl, "chillers": [], "dry": [], "towers": [], "cw_pump": None}
        lp = self.loops[pl.loop]
        for c in pl.chillers:
            if c.capacity_kw is None or c.duty is None:
                raise ValueError(f"chiller {c.name}: capacity and quantity must be set (or auto-sized)")
            cop = c.cop if c.cop else (c.capacity_kw / c.power_kw if c.power_kw else None)
            if cop is None:
                raise ValueError(f"chiller {c.name}: give cop or power_kw")
            lwt = c.rated_lwt_c if c.rated_lwt_c is not None else lp.supply_c
            ect = c.rated_ect_c if c.rated_ect_c is not None else (35.0 if c.kind == "air_cooled" else 29.4)
            cs = c.curves
            if cs.table:
                curves = curves_from_table(cs.table, c.capacity_kw, cop, lwt, ect, cs.clamp_inputs)
            elif cs.capft and cs.eirft and cs.eirfplr:
                curves = curves_from_coefficients(cs.model_dump(), lwt, ect, cs.clamp_inputs, cs.normalize)
            else:
                curves = curves_from_library(cs.library or DEFAULT_LIBRARY[c.kind], lwt, ect, cs.clamp_inputs)
            lib_min = 0.15
            model = ChillerModel(c.name, c.kind, c.duty, c.standby, c.capacity_kw, cop, lwt, ect, curves,
                                 min_plr=c.min_plr if c.min_plr is not None else lib_min, below_min=c.below_min,
                                 stage_up=c.stage_up_plr, standby_on_shortfall=c.standby_on_shortfall,
                                 priority=c.priority, lwt_range=c.lwt_range_c, tcond_range=c.tcond_range_c)
            ip = None
            if c.integral_pump is not None and c.integral_pump.power_kw:
                spec = c.integral_pump
                ip = self._group(f"{c.name} integral pump", "chw_pumps_integral", spec, default_method="M2",
                                 default_curve="K-DP(0.3)", default_f_min=0.3, n_duty=c.duty, n_standby=c.standby)
            fc = None
            if c.free_cooling is not None and c.free_cooling.enabled:
                f = c.free_cooling
                q_r = f.rated_capacity_kw or 0.5 * c.capacity_kw
                flow_unit = (c.capacity_kw / (self.loop_rcp[lp.name] * self.loop_dt[lp.name]))  # m3/s at design dT
                c_w = flow_unit * self.loop_rcp[lp.name]
                t_w_in = lp.return_c
                t_air = t_w_in - f.rated_dt_k
                t_w_out = t_w_in - q_r / c_w
                coil = AirWaterCoil.from_rating(f"{c.name} free cooling coil", q_r, t_w_in, t_w_out, t_air,
                                                c_air_ratio=f.air_to_water_capacity_ratio, n_exp=f.ua_exponent)
                fan_kw = f.fan_power_kw if f.fan_power_kw is not None else 0.02 * c.capacity_kw
                fspec = FanPump(power_kw=fan_kw, quantity=c.duty + c.standby, duty=c.duty, standby=c.standby,
                                part_load=f.part_load)
                fan = build_group(f"{c.name} free cooling fans", "free_cooling_fans", fspec, default_method="M5",
                                  default_curve="K-CUBE", default_f_min=0.2)
                fc = {"coil": coil, "fan": fan, "spec": f}
            rt["chillers"].append({"spec": c, "model": model, "pump": ip, "fc": fc})
        for d in pl.dry_coolers:
            if d.rated_capacity_kw is None or d.duty is None:
                raise ValueError(f"dry cooler {d.name}: capacity and quantity must be set (or auto-sized)")
            airflow = d.airflow_l_s / 1000.0 if d.airflow_l_s else None
            coil = AirWaterCoil.from_rating(d.name, d.rated_capacity_kw, d.rated_water_in_c, d.rated_water_out_c,
                                            d.rated_air_c, c_air_ratio=d.air_to_water_capacity_ratio,
                                            airflow_m3s=airflow, n_exp=d.ua_exponent)
            fspec = FanPump(power_kw=d.fan_power_kw or 0.0, quantity=d.quantity, duty=d.duty, standby=d.standby,
                            part_load=d.part_load)
            fan = build_group(f"{d.name} fans", "heat_rejection_fans", fspec, default_method="M5",
                              default_curve="K-CUBE", default_f_min=0.2)
            rt["dry"].append({"spec": d, "coil": coil, "fan": fan})
        for t in pl.towers:
            if t.rated_capacity_kw is None or t.duty is None:
                raise ValueError(f"tower {t.name}: capacity and quantity must be set (or auto-sized)")
            unit = CoolingTowerUnit.from_rating(t.name, t.rated_capacity_kw, t.design_wb_c, t.approach_k, t.range_k,
                                                airflow_m3s=t.airflow_l_s / 1000.0 if t.airflow_l_s else None)
            fan_kw = t.fan_power_kw if t.fan_power_kw is not None else 0.0105 * t.rated_capacity_kw
            fspec = FanPump(power_kw=fan_kw, quantity=t.quantity, duty=t.duty, standby=t.standby, part_load=t.part_load)
            fan = build_group(f"{t.name} fans", "heat_rejection_fans", fspec, default_method="M5",
                              default_curve="K-CUBE", default_f_min=0.2)
            rt["towers"].append({"spec": t, "unit": unit, "fan": fan})
        cw = pl.condenser_water
        if cw is not None and cw.pump is not None and cw.pump.power_kw:
            rt["cw_pump"] = self._group(f"{pl.name} condenser water pump", "cw_pumps", cw.pump, default_method="M3",
                                        default_curve="K-CONST", default_f_min=0.0)
        return rt

    # ------------------------------------------------------------------
    def _loss_alloc_static(self):
        """Map loss elements to receiving zones / halls (IN-Z-7)."""
        e = self.p.electrical
        self.elements = [("PDU", "pdu")]
        for u in e.ups:
            self.elements.append((u.name, "ups_it" if u.path == "it" else "ups_mech"))
        for t in e.transformers:
            self.elements.append((t.name, "transformer_hv" if t.level == "HV" else "transformer_mvlv"))
        if e.distribution is not None:
            self.elements.append((e.distribution.name, "distribution"))
        aliases = {"pdu": {"pdu"}, "ups": {"ups_it", "ups_mech"}, "ups_it": {"ups_it"}, "ups_mech": {"ups_mech"},
                   "transformer": {"transformer_hv", "transformer_mvlv"}, "transformer_hv": {"transformer_hv"},
                   "transformer_mvlv": {"transformer_mvlv"}, "distribution": {"distribution"}}
        names = {n for n, _ in self.elements}
        self.alloc: dict[str, dict[str, float]] = {n: {} for n, _ in self.elements}
        receivers = [(h.name, h.losses) for h in self.p.halls] + [(z.name, z.losses) for z in self.p.zones]
        receivers.append(("__outdoors__", e.heat_outdoors))
        for rname, losses in receivers:
            for key, frac in losses.items():
                if key in names:
                    targets = [key]
                elif key.lower() in aliases:
                    targets = [n for n, k in self.elements if k in aliases[key.lower()]]
                else:
                    raise ValueError(f"{rname}: loss allocation key {key!r} is not a loss element or alias "
                                     f"({', '.join(sorted(names | set(aliases)))})")
                for t in targets:
                    self.alloc[t][rname] = self.alloc[t].get(rname, 0.0) + float(frac)
        self.pdu_default_to_halls = not self.alloc["PDU"]
        for n, d in self.alloc.items():
            s = sum(d.values())
            if s > 1.0 + 1e-6:
                raise ValueError(f"loss element {n}: allocated fractions sum to {s:.3f} > 1")
            if s < 1.0 - 1e-6 and not (n == "PDU" and self.pdu_default_to_halls):
                self.warn_static.append(f"loss element {n}: {100 * (1 - s):.1f} % of its heat is not allocated to a "
                                        f"zone; treated as released outdoors (REQ-C-E-4)")

    # ------------------------------------------------------------------
    def tsup(self, loop, w: Weather) -> np.ndarray:
        r = loop.reset
        n = w.n
        if r.type == "fixed":
            return np.full(n, loop.supply_c)
        if r.type == "ambient_linear":
            lo, hi = r.supply_low_c, r.supply_high_c
            a1, a2 = r.t_amb_low_c, r.t_amb_high_c
            return np.interp(w.t_db, [a1, a2], [lo, hi])
        if r.type == "wetbulb_offset":
            return np.clip(w.t_wb + r.offset_k, r.min_c, r.max_c)
        if r.type == "drybulb_offset":
            return np.clip(w.t_db + r.offset_k, r.min_c, r.max_c)
        raise ValueError(r.type)

    # ------------------------------------------------------------------
    def simulate(self, w: Weather, it: ITInput, *, disable_adiabatic: bool = False) -> SimResult:
        p = self.p
        n = w.n
        S = p.settings
        hod, wkend = w.hour_of_day, w.is_weekend
        p_kpa = w.p_kpa
        warnings: list[str] = list(self.warn_static)
        eu: dict[str, np.ndarray] = {}
        eu_boundary: dict[str, str] = {}
        detail: dict[str, dict[str, np.ndarray]] = {}
        served: dict[str, np.ndarray] = {}
        sizing: dict[str, np.ndarray] = {}
        cols: dict[str, np.ndarray] = {}

        def add(key, arr, boundary="infrastructure"):
            eu[key] = eu.get(key, np.zeros(n)) + arr
            if key not in eu_boundary or boundary == "infrastructure":
                eu_boundary[key] = boundary

        it_h = {h: _ac(v, n) for h, v in it.it_kw.items()}
        lf_h = {h: _ac(v, n) for h, v in it.liquid_fraction.items()}
        P_IT = sum(it_h.values()) if it_h else np.zeros(n)
        it_frac = _ac(it.it_fraction, n)

        # ---------------- static gains (lighting, people, equipment, envelope) -------------
        static_eu: dict[str, np.ndarray] = {}
        hall_static = {}
        zone_gain: dict[str, np.ndarray] = {}
        zone_lat: dict[str, np.ndarray] = {}
        zone_amb: dict[str, np.ndarray] = {}  # ambient (envelope + infiltration + OA) part, signed
        boundary_of: dict[str, str] = {}
        for h in p.halls:
            area = (h.area_m2 or h.it_kw / S.density_kw_per_m2) * h.count
            light = area * h.lighting_w_m2 / 1000.0 * schedules.profile(h.lighting_profile, hod, wkend, self.base_dir)
            ppl = 0.0
            if h.occupancy_m2_per_person:
                ppl = area / h.occupancy_m2_per_person * 0.070 * schedules.profile(h.occupancy_profile, hod, wkend,
                                                                                   self.base_dir)
            hall_static[h.name] = light + ppl + h.fixed_gain_kw
            static_eu[h.lighting_end_use] = static_eu.get(h.lighting_end_use, 0) + light
            boundary_of[h.lighting_end_use] = "infrastructure"

        oa_by_zone = self._oa_by_zone()
        for z in p.zones:
            area = z.area_m2 * z.count
            light = area * z.lighting_w_m2 / 1000.0 * schedules.profile(z.lighting_profile, hod, wkend, self.base_dir)
            eqp = area * z.equipment_w_m2 / 1000.0 * schedules.profile(z.equipment_profile, hod, wkend, self.base_dir)
            occ = schedules.profile(z.occupancy_profile, hod, wkend, self.base_dir)
            people = area / z.occupancy_m2_per_person if z.occupancy_m2_per_person else 0.0
            ppl_s = people * 0.070 * occ
            ppl_l = people * 0.060 * occ
            ua = z.count * (z.external_wall_m2 * z.u_wall + (z.area_m2 * z.u_roof if z.roof_exposed else 0.0)) / 1000
            env = ua * (w.t_db - z.setpoint_c)
            ach = z.infiltration_ach
            oa_flow = oa_by_zone.get(z.name, 0.0)  # m3/s total
            if ach is None:
                ach = 0.0 if z.pressurised else (0.7 if oa_flow <= 0 else 0.35)
            vol = area * z.height_m
            inf_flow = ach * vol / 3600.0
            rho = psychro.density(w.t_db, w.w, p_kpa)
            air = (inf_flow + oa_flow) * rho
            sens_amb = air * CP_AIR * (w.t_db - z.setpoint_c)
            w_zone = psychro.humidity_ratio_from_rh(z.setpoint_c, z.rh_max_pct or 50.0, p_kpa)
            lat_amb = air * psychro.h_fg(z.setpoint_c) * np.maximum(w.w - w_zone, 0.0)
            zone_gain[z.name] = light + eqp + ppl_s + z.fixed_gain_kw
            zone_amb[z.name] = env + sens_amb
            zone_lat[z.name] = ppl_l + lat_amb
            static_eu[z.lighting_end_use] = static_eu.get(z.lighting_end_use, 0) + light
            boundary_of[z.lighting_end_use] = z.boundary if z.boundary == "excluded" else boundary_of.get(
                z.lighting_end_use, "infrastructure")
            if z.equipment_w_m2 > 0:
                static_eu[z.equipment_end_use] = static_eu.get(z.equipment_end_use, 0) + eqp
                boundary_of[z.equipment_end_use] = z.boundary

        # other end uses (independent of iteration)
        other_eu, other_heat, annual_items, diesel_l, diesel_kwh, pv = self._other_end_uses(w, warnings)
        for k, v in other_heat.items():
            if k in zone_gain:
                zone_gain[k] = zone_gain[k] + v
            elif k in hall_static:
                hall_static[k] = hall_static[k] + v
        for k, (arr, b) in other_eu.items():
            static_eu[k] = static_eu.get(k, 0) + arr
            boundary_of[k] = b

        # ---------------- iteration state -------------------------------------------
        prev = {"mech_ups": np.zeros(n), "infra": np.zeros(n), "mech": np.zeros(n), "zone_fanheat": {}}
        static_total = sum(_ac(v, n) for v in static_eu.values()) if static_eu else np.zeros(n)
        conv = np.zeros(n, dtype=bool)
        cyc = np.zeros(n, dtype=bool)
        last_infra = None
        history: list[np.ndarray] = []
        iters = 0
        for iters in range(1, S.max_iterations + 1):
            st = self._iterate(w, it_h, lf_h, P_IT, it_frac, prev, hall_static, zone_gain, zone_amb, zone_lat,
                               static_total, disable_adiabatic)
            infra = st["infra_total"]
            if last_infra is not None:
                rel = np.abs(infra - last_infra) / np.maximum(np.abs(infra), 1e-6)
                conv = rel <= S.tolerance
                # limit cycle of period 2 to 4: discrete staging flips between states with no fixed point
                cyc = np.zeros(n, dtype=bool)
                for old in history[-4:-1]:
                    cyc |= np.abs(infra - old) / np.maximum(np.abs(infra), 1e-6) <= S.tolerance
                cyc &= ~conv
                if (conv | cyc).all():
                    break
            history.append(infra)
            r = S.relaxation
            new = {"mech_ups": st["mech_ups"], "infra": st["infra_for_dist"], "mech": st["mech_total"],
                   "zone_fanheat": st["zone_fanheat"], "facility_other": st["facility_other"]}
            if last_infra is not None and r < 1.0:
                for k in ("mech_ups", "infra", "mech"):
                    new[k] = r * new[k] + (1 - r) * prev[k]
            prev = new
            last_infra = infra
        nonconv = ~(conv | cyc) if iters > 1 else np.zeros(n, dtype=bool)
        if cyc.any():
            hrs = np.flatnonzero(cyc)[:10].tolist()
            gap = float(np.max(np.abs(infra - last_infra)[cyc] / np.maximum(infra[cyc], 1e-6)))
            warnings.append(f"Discrete staging limit cycle in {int(cyc.sum())} h (equipment count flips between states "
                            f"with no fixed point; max infrastructure difference {100 * gap:.1f} %); last state kept. Hours: {hrs}")
        if nonconv.any():
            hrs = np.flatnonzero(nonconv)[:10].tolist()
            warnings.append(f"Coupling iteration not converged in {int(nonconv.sum())} h after {iters} iterations "
                            f"(REQ-C-7); first hours: {hrs}")

        cols["_t_db_min"] = np.full(n, float(np.min(w.t_db)))
        eu.update(st["eu"])
        detail.update(st["detail"])
        served.update(st["served"])
        sizing.update(st["sizing"])
        cols.update(st["cols"])
        warnings += st["warnings"]
        for k, v in static_eu.items():
            add(k, _ac(v, n), boundary_of.get(k, "infrastructure"))
        for k in st["eu"]:
            eu_boundary.setdefault(k, "infrastructure")
        for k, b in st.get("eu_boundary", {}).items():
            eu_boundary[k] = b
        # ledger: heat into building vs heat removed (REQ-C-5)
        ledger = st["ledger"]
        return SimResult(n, cols, eu, eu_boundary, detail, served, sizing, iters, nonconv, warnings, annual_items,
                         diesel_l, diesel_kwh, pv, st["water_l"], ledger)

    # ------------------------------------------------------------------
    def _oa_by_zone(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self.p.room_units:
            n_e = _energised(r)
            if r.type == "OAF":
                flow = (r.oa_l_s or r.airflow_l_s or 0.0) / 1000.0 * n_e
            elif r.type == "EAF":
                flow = (r.oa_l_s or 0.0) / 1000.0 * n_e
            else:
                flow = r.oa_l_s / 1000.0 * n_e
            if flow <= 0:
                continue
            for zname, share in _shares(r):
                out[zname] = out.get(zname, 0.0) + flow * share
        return out

    # ------------------------------------------------------------------
    def _electrical(self, it_h, P_IT, prev):
        p = self.p
        e = p.electrical
        n = len(P_IT)
        conv = self.loss_conv
        res = {}  # element name -> dict(loss, kind, end_use, load_frac)
        x = self.pdu_frac
        pdu_h = {h: (v * x / (1 - x) if conv == "physical" else v * x) for h, v in it_h.items()}
        pdu = sum(pdu_h.values()) if pdu_h else np.zeros(n)
        res["PDU"] = {"loss": pdu, "kind": "pdu", "end_use": "pdu_loss", "by_hall": pdu_h}
        it_ups = [u for u in e.ups if u.path == "it"]
        mech_ups = [u for u in e.ups if u.path == "mechanical"]
        # IT UPS: split each hall's load among the IT UPS types serving it
        serving = {h: [u for u in it_ups if "all" in u.serves or h in u.serves] for h in it_h}
        ups_it_total = np.zeros(n)
        for u in it_ups:
            pout = np.zeros(n)
            for h, us in serving.items():
                if u in us:
                    pout = pout + (it_h[h] + pdu_h[h]) / len(us)
            loss, frac = self._ups_loss(u, pout)
            ups_it_total += loss
            res[u.name] = {"loss": loss, "kind": "ups_it", "end_use": "ups_loss_it", "load_frac": frac, "pout": pout}
        ups_mech_total = np.zeros(n)
        if mech_ups:
            caps = np.array([_ups_cap(u) for u in mech_ups])
            for u, c in zip(mech_ups, caps):
                pout = prev["mech_ups"] * c / caps.sum()
                loss, frac = self._ups_loss(u, pout)
                ups_mech_total += loss
                res[u.name] = {"loss": loss, "kind": "ups_mech", "end_use": "ups_loss_mech", "load_frac": frac,
                               "pout": pout}
        it_path = P_IT + pdu + ups_it_total
        mech = prev["mech"] + ups_mech_total
        infra_other = prev["infra"]  # all infrastructure excl. transformers / distribution / contingency
        tx_mvlv = np.zeros(n)
        for level in ("MVLV", "HV"):
            for t in [t for t in e.transformers if t.level == level]:
                b = t.basis
                if b == "it":
                    thr = P_IT
                elif b == "it_path":
                    thr = it_path
                elif b == "mechanical":
                    thr = mech
                elif b == "infrastructure":
                    thr = infra_other + pdu + ups_it_total + ups_mech_total + (tx_mvlv if level == "HV" else 0)
                else:  # facility
                    thr = P_IT + infra_other + pdu + ups_it_total + ups_mech_total + (tx_mvlv if level == "HV" else 0)
                if t.loss_model == "percent":
                    loss = thr * t.percent / 100.0
                else:
                    if not t.rating_kva:
                        raise ValueError(f"transformer {t.name}: no_load_load model needs rating_kva")
                    s = thr / t.power_factor / max(t.quantity, 1)
                    loss = t.quantity * (t.no_load_kw + t.full_load_kw * (s / t.rating_kva) ** 2)
                kind = "transformer_hv" if level == "HV" else "transformer_mvlv"
                res[t.name] = {"loss": loss, "kind": kind, "end_use": kind, "throughput": thr}
                if level == "MVLV":
                    tx_mvlv = tx_mvlv + loss
        d = e.distribution
        if d is not None and d.percent > 0:
            losses_so_far = sum(v["loss"] for v in res.values())
            if d.basis == "infrastructure":
                base = infra_other + losses_so_far
            elif d.basis == "it":
                base = P_IT
            else:
                base = P_IT + infra_other + losses_so_far
            res[d.name] = {"loss": base * d.percent / 100.0, "kind": "distribution", "end_use": "distribution_loss",
                           "base": base}
        return res

    def _ups_loss(self, u, pout):
        cap = _ups_cap(u)
        frac = pout / cap if cap > 0 else np.zeros_like(pout)
        eta = self.ups_tables[u.name](frac)
        conv = u.loss_convention or self.loss_conv
        loss = pout * (1.0 / eta - 1.0) if conv == "physical" else pout * (1.0 - eta)
        return np.where(pout > 0, loss, 0.0), frac

    # ------------------------------------------------------------------
    def _iterate(self, w, it_h, lf_h, P_IT, it_frac, prev, hall_static, zone_gain, zone_amb, zone_lat, static_total,
                 disable_adiabatic):
        p = self.p
        n = w.n
        eu: dict[str, np.ndarray] = {}
        detail: dict[str, dict] = {}
        served: dict[str, np.ndarray] = {}
        sizing: dict[str, np.ndarray] = {}
        cols: dict[str, np.ndarray] = {}
        warnings: list[str] = []
        ups_loads = np.zeros(n)
        heat_in = np.zeros(n)  # ledger: heat entering cooled spaces and loops
        removed = np.zeros(n)  # ledger: heat removed to outdoors by plant / DX / unmet

        def add(key, arr):
            eu[key] = eu.get(key, np.zeros(n)) + arr

        # ---- 4 electrical loss chain ----
        elec = self._electrical(it_h, P_IT, prev)
        recv = {h: np.zeros(n) for h in self.halls}
        recv.update({z: np.zeros(n) for z in self.zones})
        for name, r in elec.items():
            add(r["end_use"], r["loss"])
            detail[f"loss:{name}"] = {k: v for k, v in r.items() if isinstance(v, np.ndarray)}
            if name == "PDU" and self.pdu_default_to_halls:
                for h, v in r["by_hall"].items():
                    recv[h] += v
                continue
            for zname, frac in self.alloc.get(name, {}).items():
                if zname != "__outdoors__":
                    recv[zname] += r["loss"] * frac
        # ---- 5 halls ----
        q_air_h = {}
        q_liq_h = {}
        for h in p.halls:
            q_liq_h[h.name] = lf_h[h.name] * it_h[h.name]
            q_air_h[h.name] = (1 - lf_h[h.name]) * it_h[h.name] + hall_static[h.name] + recv[h.name]
            heat_in += it_h[h.name] + hall_static[h.name] + recv[h.name]
            sizing[f"hall_air:{h.name}"] = q_air_h[h.name]
            sizing[f"hall_liquid:{h.name}"] = q_liq_h[h.name]
        loop_q = {lp.name: np.zeros(n) for lp in p.loops}
        loop_v = {lp.name: np.zeros(n) for lp in p.loops}  # terminal flow demand m3/s

        # ---- 6a CDUs ----
        tsup = {lp.name: self.tsup(lp, w) for lp in p.loops}
        cdu_shares = _shares_for(p.cdus, self.halls)
        for c in p.cdus:
            q = sum(q_liq_h[h] * cdu_shares[(c.name, h)] for h in c.serves)
            served[f"{c.name} pump"] = q
            sizing[f"cdu:{c.name}"] = q
            g = self.cdu_groups.get(c.name)
            pump = np.zeros(n)
            res = None
            if g is not None:
                v_req = None
                if g.method in ("M2", "M4") and g.v_des_m3s:
                    dt_des = (c.capacity_kw or 1.0) / (fluids.rho_cp("water") * g.v_des_m3s)
                    v_req = q / (fluids.rho_cp("water") * dt_des)
                res = g.evaluate(q_served=q, v_req=v_req, it_fraction=it_frac, n_hours=n)
                pump = res["power"]
                add("cdu_pumps", pump)
                if g.on_ups:
                    ups_loads += pump
            q_tcs = q + pump * (g.heat_to_stream if g else 1.0)
            heat_in += q_tcs - q
            loop_q[c.loop] += q_tcs
            loop_v[c.loop] += q_tcs / (self.loop_rcp[c.loop] * self.loop_dt[c.loop])
            d = {"q": q, "q_tcs": q_tcs, "power": pump}
            if res is not None:
                d.update({"f": res["f"], "f_eff": res["f_eff"], "n_run": res["n_run"]})
            if c.capacity_kw and c.active:
                plr = q_tcs / (c.active * c.capacity_kw)
                d["plr"] = plr
                d["overload"] = plr > 1.0 + 1e-6
                app = c.approach_k * (plr if c.approach_model == "load_scaled" else 1.0)
                d["approach"] = app
                if c.tcs_supply_c is not None:
                    d["t_loop_required"] = c.tcs_supply_c - app
            detail[f"cdu:{c.name}"] = d

        # ---- 6b FWUs ----
        fwu_shares = _shares_for(p.fwus, self.halls)
        hall_air_handled = {h: np.zeros(n) for h in self.halls}
        for f in p.fwus:
            q = sum(q_air_h[h] * fwu_shares[(f.name, h)] for h in f.serves)
            for h in f.serves:
                hall_air_handled[h] += q_air_h[h] * fwu_shares[(f.name, h)]
            g = self.fwu_groups.get(f.name)
            served[f"{f.name} fans"] = q
            sizing[f"fwu:{f.name}"] = q
            t_sa = f.supply_air_c if f.supply_air_c is not None else self.halls[f.serves[0]].cold_aisle_c
            rho = psychro.density(t_sa, 0.008, w.p_kpa)
            fan = np.zeros(n)
            res = None
            if g is not None:
                if g.method == "M4":
                    pl = f.part_load
                    air_it = sum((1 - lf_h[h]) * it_h[h] * fwu_shares[(f.name, h)] for h in f.serves)
                    v_req = air_it * (pl.server_airflow_l_s_per_kw or 0.0) / 1000.0 * (1 + pl.bypass_fraction)
                else:
                    v_req = q / (rho * CP_AIR * f.air_dt_k)
                res = g.evaluate(q_served=q, v_req=v_req, it_fraction=it_frac, n_hours=n)
                fan = res["power"]
                add("fwu_fans", fan)
                if g.on_ups:
                    ups_loads += fan
            fan_heat = fan * (g.heat_to_stream if g else 1.0)
            heat_in += fan_heat
            coil = q + fan_heat
            sizing[f"fwu_coil:{f.name}"] = coil
            for h in f.serves:
                sizing[f"fwu_coil:{f.name}:{h}"] = coil * np.where(q > 0, q_air_h[h] * fwu_shares[(f.name, h)] /
                                                                    np.maximum(q, 1e-9), 0.0)
            loop_q[f.loop] += coil
            loop_v[f.loop] += coil / (self.loop_rcp[f.loop] * self.loop_dt[f.loop])
            d = {"q_room": q, "q_coil": coil, "power": fan}
            if res is not None:
                d.update({"f": res["f"], "f_eff": res["f_eff"], "n_run": res["n_run"], "bypass": res["bypass"]})
                if f.coil_capacity_kw:
                    d["overload"] = coil > res["n_run"] * f.coil_capacity_kw + 1e-6
            detail[f"fwu:{f.name}"] = d

        # ---- 6c supporting zones and room units ----
        zq = {}
        for z in p.zones:
            fan_heat = prev["zone_fanheat"].get(z.name, np.zeros(n))
            q_s = zone_gain[z.name] + zone_amb[z.name] + recv[z.name] + fan_heat
            zq[z.name] = q_s
            heat_in += zone_gain[z.name] + recv[z.name] + fan_heat + zone_amb[z.name]
            sizing[f"zone:{z.name}"] = np.maximum(q_s, 0) + np.maximum(zone_lat[z.name], 0)
        # halls served by room units (air side without FWUs)
        for h in p.halls:
            fh = prev["zone_fanheat"].get(h.name, np.zeros(n))
            rest = q_air_h[h.name] - hall_air_handled[h.name] + fh
            heat_in += fh
            zq[h.name] = rest
        zone_fanheat_new: dict[str, np.ndarray] = {}
        handled_by_zone = {k: np.zeros(n) for k in zq}
        cooling_units = [r for r in p.room_units if r.type in ("CRAH", "CRAC", "PAC", "VRF", "split", "FCU")]
        share_norm = _zone_share_norm(cooling_units)
        for r in p.room_units:
            n_e = _energised(r)
            eu_key = r.end_use or _ru_end_use(r, self.zones)
            if r.type in ("OAF", "EAF", "DX_dehumidifier", "humidifier"):
                active = _activation(r, w)
                pw = n_e * (r.power_kw or r.fan_power_kw) * active
                add(eu_key, pw)
                if r.on_ups:
                    ups_loads += pw
                if r.type != "EAF":
                    for zname, share in _shares(r):
                        zone_fanheat_new[zname] = zone_fanheat_new.get(zname, np.zeros(n)) + pw * share
                detail[f"room_unit:{r.name}"] = {"power": pw, "active": active}
                continue
            q_tot = np.zeros(n)
            lat_tot = np.zeros(n)
            for zname, share in _shares(r):
                sh = share / share_norm.get(zname, 1.0)
                q_tot += np.maximum(zq[zname], 0.0) * sh
                if zname in zone_lat:
                    lat_tot += np.maximum(zone_lat[zname], 0.0) * sh
            dx = r.type in ("CRAC", "PAC", "VRF", "split")
            q_load = q_tot + (lat_tot if dx else 0.0)
            served[f"{r.name} fans"] = q_load
            sizing[f"room_unit:{r.name}"] = q_load
            cap = (r.capacity_kw or 0.0) * n_e
            handled = np.minimum(q_load, cap) if cap > 0 else q_load
            unmet = q_load - handled
            frac_handled = np.where(q_load > 0, handled / np.maximum(q_load, 1e-9), 1.0)
            if dx:
                # ledger: latent picked up by DX units enters the balance; its unmet share stays in the zone
                heat_in += lat_tot
                removed += lat_tot * (1.0 - frac_handled)
            for zname, share in _shares(r):
                sh = share / share_norm.get(zname, 1.0)
                handled_by_zone[zname] += np.maximum(zq[zname], 0.0) * sh * frac_handled
            g = self.ru_groups.get(r.name)
            fan = np.zeros(n)
            res = None
            if g is not None:
                v_req = None
                if g.method in ("M2", "M4"):
                    off = r.off_coil_c
                    z0 = self.zones.get(_shares(r)[0][0])
                    tset = z0.setpoint_c if z0 else 27.0
                    dt = (tset - off) if off is not None else 10.0
                    v_req = handled / (1.2 * CP_AIR * max(dt, 1.0))
                res = g.evaluate(q_served=handled, v_req=v_req, it_fraction=it_frac, n_hours=n)
                fan = res["power"]
                if g.on_ups:
                    ups_loads += fan
            fan_heat = fan * (g.heat_to_stream if g else 1.0)
            for zname, share in _shares(r):
                zone_fanheat_new[zname] = zone_fanheat_new.get(zname, np.zeros(n)) + fan_heat * share
            comp = np.zeros(n)
            plr = np.where(cap > 0, handled / max(cap, 1e-9), 0.0)
            if r.type in ("CRAH", "FCU"):
                loop_q[r.loop] += handled
                loop_v[r.loop] += handled / (self.loop_rcp[r.loop] * self.loop_dt[r.loop])
                add(eu_key, fan)
            else:
                if r.type == "PAC":
                    t_cond = tsup[r.loop]
                else:
                    t_cond = w.t_db + r.recirculation_k
                cop = r.cop * (1.0 + r.cop_ambient_slope_per_k * (t_cond - r.rated_condenser_c))
                cop = np.maximum(cop, 0.5)
                if r.eirfplr and cap > 0:
                    fplr = PolyPLR(list(r.eirfplr))(plr)
                    comp = cap / cop * fplr * (handled > 0)
                else:
                    comp = handled / cop
                if r.type == "PAC":
                    heat_in += comp
                    loop_q[r.loop] += handled + comp
                    loop_v[r.loop] += (handled + comp) / (self.loop_rcp[r.loop] * self.loop_dt[r.loop])
                else:
                    removed += handled
                add(eu_key, comp + fan)
                if r.on_ups:
                    ups_loads += comp
            d = {"q_load": q_load, "handled": handled, "unmet": unmet, "plr": plr, "fan_power": fan,
                 "compressor_power": comp, "power": comp + fan}
            if res is not None:
                d.update({"f": res["f"], "f_eff": res["f_eff"], "n_run": res["n_run"]})
            detail[f"room_unit:{r.name}"] = d
        zone_unmet = {}
        for zname, q in zq.items():
            pos = np.maximum(q, 0.0)
            um = np.maximum(pos - handled_by_zone[zname], 0.0)
            if zname in self.halls:
                if not np.any(pos > 1e-6):
                    continue
            zone_unmet[zname] = um
            removed += um
            if zname in self.zones:
                cols[f"zone_load_kw:{zname}"] = q
                cols[f"zone_unmet_kw:{zname}"] = um
                heating = np.maximum(-q, 0.0)
                if heating.any():
                    cols[f"zone_heating_kw:{zname}"] = heating
                    removed -= heating
        # ---- 7 loops: pumps, flows, temperatures, arrangements ----
        loop_state = {}
        plant_results = {}
        for ln in self.loop_order:
            lp = self.loops[ln]
            rcp = self.loop_rcp[ln]
            q_own = loop_q[ln].copy()
            v_own = loop_v[ln].copy()
            sec = self.loop_pumps[ln]["secondary"]
            # children contributions
            q_child = np.zeros(n)
            v_child = np.zeros(n)
            qt_child = np.zeros(n)  # sum V*T for mixing
            for cn in self.loop_children[ln]:
                cs = loop_state[cn]
                q_child += cs["contrib_q"]
                v_child += cs["contrib_v"]
                qt_child += cs["contrib_v"] * cs["contrib_t"]
            sec_pw = np.zeros(n)
            v_terminal = v_own
            v_act = v_own.copy()
            if sec is not None:
                served[sec.name] = q_own
                res = sec.evaluate(q_served=q_own, v_req=v_own, it_fraction=it_frac, n_hours=n)
                sec_pw = res["power"]
                heat = sec_pw * sec.heat_to_stream
                q_own = q_own + heat
                heat_in += heat
                if sec.v_des_m3s:
                    v_act = np.maximum(v_own, res["n_run"] * res["f_eff"] * sec.v_des_m3s)
                add(sec.end_use, sec_pw)
                if sec.on_ups:
                    ups_loads += sec_pw
                detail[f"pump:{sec.name}"] = {"power": sec_pw, "f": res["f"], "f_eff": res["f_eff"],
                                              "n_run": res["n_run"], "bypass": res["bypass"]}
            t_set = tsup[ln]
            with np.errstate(divide="ignore", invalid="ignore"):
                t_ret_own = np.where(v_act > 0, t_set + q_own / (rcp * np.maximum(v_act, 1e-12)), t_set)
            q_tot = q_own + q_child
            v_tot = v_act + v_child
            t_ret = np.where(v_tot > 0, (v_act * t_ret_own + qt_child) / np.maximum(v_tot, 1e-12), t_set)
            st = {"q": q_tot, "v": v_tot, "t_ret": t_ret, "t_set": t_set, "q_own": q_own}
            loop_state[ln] = st
            if ln in self.plant_of_loop:
                # plant loop: primary + integral pumps, then plant
                pr = self._plant(self.plant_rt[self.plant_of_loop[ln]], st, w, rcp, it_frac, served, sizing, detail,
                                 eu, ups_loads, disable_adiabatic)
                ups_loads = pr["ups_loads"]
                plant_results[ln] = pr
                heat_in += pr["pump_heat"]
                removed += pr["q_delivered"] + pr["unmet"]
                st["t_sup_ach"] = pr["t_sup_ach"]
                st["unmet"] = pr["unmet"]
            # contribution to parent
            if lp.connection in ("blended", "hx", "split"):
                par = self.loops[lp.from_loop]
                prcp = self.loop_rcp[par.name]
                tp = tsup[par.name]
                if lp.connection == "blended":
                    dtp = np.maximum(t_ret - tp, 1e-3)
                    v_draw = np.where(t_set > tp + 1e-6, q_tot / (prcp * dtp), v_tot)
                    st.update(contrib_q=q_tot, contrib_v=v_draw, contrib_t=np.where(v_draw > 0, t_ret, tp))
                    st["mix_ratio"] = np.where(v_tot > 0, v_draw / np.maximum(v_tot, 1e-12), 0)
                elif lp.connection == "hx":
                    t_out = np.maximum(t_ret - lp.hx_approach_k, tp + 0.5)
                    v_p = q_tot / (prcp * np.maximum(t_out - tp, 0.5))
                    st.update(contrib_q=q_tot, contrib_v=v_p, contrib_t=t_out)
                    drift = np.maximum(tp + lp.hx_approach_k - t_set, 0.0)
                    st["hx_drift"] = drift
                else:  # split: residual unmet from the dedicated plant goes to the parent through an HX
                    res_q = st.get("unmet", np.zeros(n))
                    removed -= res_q  # not unmet: transferred
                    st["unmet"] = np.zeros(n)
                    v_p = res_q / (prcp * self.loop_dt[par.name])
                    st.update(contrib_q=res_q, contrib_v=v_p, contrib_t=tp + self.loop_dt[par.name])
                    st["trim_q"] = res_q
            cols[f"loop_load_kw:{ln}"] = q_tot
            cols[f"loop_supply_set_c:{ln}"] = t_set
            cols[f"loop_return_c:{ln}"] = t_ret
            cols[f"loop_flow_l_s:{ln}"] = v_tot * 1000.0
            sizing[f"loop:{ln}"] = q_tot
            sizing[f"loop_flow:{ln}"] = v_tot
        # achieved supply temperatures down the tree
        for ln in reversed(self.loop_order):
            lp = self.loops[ln]
            st = loop_state[ln]
            if "t_sup_ach" not in st:
                par = loop_state.get(lp.from_loop) if lp.from_loop else None
                if par is not None and "t_sup_ach" in par:
                    if lp.connection == "hx":
                        st["t_sup_ach"] = np.maximum(st["t_set"], par["t_sup_ach"] + lp.hx_approach_k)
                    else:
                        st["t_sup_ach"] = np.maximum(st["t_set"], par["t_sup_ach"])
                else:
                    st["t_sup_ach"] = st["t_set"]
            cols[f"loop_supply_c:{ln}"] = st["t_sup_ach"]
        # CDU TCS drift (REQ-C-CDU-5)
        for c in p.cdus:
            d = detail[f"cdu:{c.name}"]
            if "t_loop_required" in d:
                d["tcs_drift"] = np.maximum(loop_state[c.loop]["t_sup_ach"] - d["t_loop_required"], 0.0)
                d["tcs_supply_c"] = loop_state[c.loop]["t_sup_ach"] + d["approach"]
            if c.r_th_k_per_kw and c.units_per_hall and c.tcs_supply_c is not None:
                worst = np.zeros(n)
                for h in c.serves:
                    hall = self.halls[h]
                    per_unit = q_liq_h[h] / max(hall.count * c.units_per_hall, 1)
                    worst = np.maximum(worst, d.get("tcs_supply_c", c.tcs_supply_c) + per_unit * c.r_th_k_per_kw)
                d["t_junction"] = worst
        # ---- totals ----
        mech_keys = set(eu) - {"pdu_loss", "ups_loss_it", "ups_loss_mech", "transformer_hv", "transformer_mvlv",
                               "distribution_loss"}
        mech_total = sum(eu[k] for k in mech_keys) if mech_keys else np.zeros(n)
        loss_keys = {"pdu_loss", "ups_loss_it", "ups_loss_mech", "transformer_hv", "transformer_mvlv",
                     "distribution_loss"}
        infra_total = sum(eu.values()) + static_total
        infra_for_dist = mech_total + static_total  # excludes electrical losses (added inside the chain)
        water = sum(pr["water_l"] for pr in plant_results.values()) if plant_results else np.zeros(n)
        sizing["mech_ups"] = ups_loads
        ledger = {"heat_in": heat_in, "removed": removed}
        return {"eu": eu, "detail": detail, "served": served, "sizing": sizing, "cols": cols, "warnings": warnings,
                "mech_ups": ups_loads, "mech_total": mech_total, "infra_total": infra_total,
                "infra_for_dist": infra_for_dist, "zone_fanheat": zone_fanheat_new, "facility_other": None,
                "water_l": water, "ledger": ledger, "loss_keys": loss_keys}

    # ------------------------------------------------------------------
    def _plant(self, rt, st, w, rcp, it_frac, served, sizing, detail, eu, ups_loads, disable_adiabatic):
        pl = rt["plant"]
        n = w.n
        q = st["q"].copy()
        v = st["v"].copy()
        t_set = st["t_set"]
        t_db, t_wb = w.t_db, w.t_wb
        pump_heat = np.zeros(n)

        def add(key, arr):
            eu[key] = eu.get(key, np.zeros(n)) + arr

        # primary loop pump and integral chiller pumps: flows, min flow, heat to the loop
        lp = self.loops[pl.loop]
        prim = self.loop_pumps[pl.loop]["primary"]
        v_min = np.zeros(n)
        if prim is not None:
            served[prim.name] = q
            res = prim.evaluate(q_served=q, v_req=v, it_fraction=it_frac, n_hours=n)
            add(prim.end_use, res["power"])
            pump_heat += res["power"] * prim.heat_to_stream
            if prim.on_ups:
                ups_loads = ups_loads + res["power"]
            if prim.v_des_m3s:
                v_min = np.maximum(v_min, res["n_run"] * res["f_eff"] * prim.v_des_m3s)
            detail[f"pump:{prim.name}"] = {"power": res["power"], "f": res["f"], "f_eff": res["f_eff"],
                                           "n_run": res["n_run"], "bypass": res["bypass"]}
        chs = rt["chillers"]
        n_units_total = sum(c["model"].n_duty for c in chs) or 1
        int_pumps = []
        for c in chs:
            g = c["pump"]
            if g is None:
                continue
            share = c["model"].n_duty / n_units_total
            served[g.name] = q * share
            int_pumps.append((c, g, share))
        # integral pumps evaluated after staging when they follow running chillers; for 'duty' now
        for c, g, share in int_pumps:
            if c["spec"].integral_pump_units == "duty":
                res = g.evaluate(q_served=q * share, v_req=v * share, it_fraction=it_frac, n_hours=n)
                c["pump_res"] = res
                add(g.end_use, res["power"])
                pump_heat += res["power"] * g.heat_to_stream
                if g.on_ups:
                    ups_loads = ups_loads + res["power"]
                if g.v_des_m3s:
                    v_min = np.maximum(v_min, res["n_run"] * res["f_eff"] * g.v_des_m3s / share)
        q = q + pump_heat
        v_plant = np.maximum(v, v_min)
        t_ret = np.where(v_plant > 0, t_set + q / (rcp * np.maximum(v_plant, 1e-12)), t_set)
        c_w = v_plant * rcp  # kW/K
        mode = np.zeros(n)  # 0 off, 1 full free cooling, 2 partial, 3 mechanical
        adiab_flag = np.zeros(n, dtype=bool)
        q_fc = np.zeros(n)
        unmet = np.zeros(n)
        water = np.zeros(n)
        tcond_extra = {}
        fc_detail = {}
        p_fc_fans = np.zeros(n)

        # ---------------- free cooling stage ----------------
        fc_chs = [c for c in chs if c["fc"] is not None]
        if pl.type == "CP-2" and fc_chs:
            n_tot = sum(c["model"].n_duty for c in fc_chs)
            cw_unit = c_w / max(n_tot, 1)
            t_air = {}
            for c in fc_chs:
                sp = c["spec"]
                ta = t_db.copy()
                if sp.adiabatic and sp.adiabatic.enabled and c["fc"]["spec"].adiabatic_in_free_cooling \
                        and not disable_adiabatic:
                    act = _adiab_active(sp.adiabatic, t_db)
                    ta = np.where(act, adiabatic_temperature(t_db, t_wb, sp.adiabatic.efficiency,
                                                             sp.recirculation_k, sp.recirculation_order),
                                  t_db + sp.recirculation_k)
                else:
                    ta = t_db + sp.recirculation_k
                t_air[sp.name] = ta
            enable = np.ones(n, dtype=bool)
            for c in fc_chs:
                enable &= (t_ret - t_air[c["spec"].name]) > c["fc"]["spec"].enable_dt_k
            qmax = sum(c["model"].n_duty * c["fc"]["coil"].q(1.0, cw_unit, t_ret, t_air[c["spec"].name])
                       for c in fc_chs)
            qmax = np.where(enable, qmax, 0.0)
            full = enable & (qmax >= q - 1e-9) & (q > 0)

            def qtot(f):
                return sum(c["model"].n_duty * c["fc"]["coil"].q(f, cw_unit, t_ret, t_air[c["spec"].name])
                           for c in fc_chs)

            fmin = min(c["fc"]["fan"].f_min for c in fc_chs)
            f_full = bisect(lambda f: qtot(f) - q, np.full(n, fmin), np.ones(n))
            f_full = np.where(qtot(np.full(n, fmin)) >= q, fmin, f_full)
            q_fc = np.where(full, q, qmax)
            mode = np.where(q <= 0, 0, np.where(full, 1, np.where(qmax > 0, 2, 3)))
            for c in fc_chs:
                coil = c["fc"]["coil"]
                cu = coil.q(1.0, cw_unit, t_ret, t_air[c["spec"].name])
                tcond_extra[c["spec"].name] = np.where(mode == 2, cu / coil.c_air_des, 0.0)
            fc_detail = {"f_full": f_full, "qmax": qmax, "t_air": t_air}
        elif pl.dry_coolers and pl.type in ("CP-3", "CP-4", "CP-5", "CP-6"):
            n_tot = sum(d["spec"].duty for d in rt["dry"])
            cw_unit = c_w / max(n_tot, 1)
            t_air = {}
            for d in rt["dry"]:
                sp = d["spec"]
                ta = t_db + sp.recirculation_k
                if sp.adiabatic and sp.adiabatic.enabled and not disable_adiabatic:
                    act = _adiab_active(sp.adiabatic, t_db)
                    adiab_flag |= act
                    ta = np.where(act, adiabatic_temperature(t_db, t_wb, sp.adiabatic.efficiency, sp.recirculation_k,
                                                             sp.recirculation_order), ta)
                t_air[sp.name] = ta

            def qtot(f):
                return sum(d["spec"].duty * d["coil"].q(f, cw_unit, t_ret, t_air[d["spec"].name]) for d in rt["dry"])

            enable = np.ones(n, dtype=bool)
            if chs:
                for d in rt["dry"]:
                    enable &= (t_ret - t_air[d["spec"].name]) > 1.0
            qmax = np.where(enable, qtot(np.ones(n)), 0.0)
            full = enable & (qmax >= q - 1e-9) & (q > 0)
            fmin = min(d["fan"].f_min for d in rt["dry"])
            f_full = bisect(lambda f: qtot(f) - q, np.full(n, fmin), np.ones(n))
            f_full = np.where(qtot(np.full(n, fmin)) >= q, fmin, f_full)
            f_op = np.where(full, f_full, np.where(qmax > 0, 1.0, 0.0))
            q_fc = np.where(full, q, qmax)
            mode = np.where(q <= 0, 0, np.where(full, 1, np.where(qmax > 0, 2, 3)))
            for d in rt["dry"]:
                res = d["fan"].evaluate(f_direct=f_op, n_hours=n)
                pw = np.where(q > 0, res["power"], 0.0)
                add("heat_rejection_fans", pw)
                detail[f"dry_cooler:{d['spec'].name}"] = {"power": pw, "f": f_op, "n_run": res["n_run"],
                                                          "t_air": t_air[d["spec"].name]}
                sp = d["spec"]
                if sp.adiabatic and sp.adiabatic.enabled and not disable_adiabatic:
                    act = _adiab_active(sp.adiabatic, t_db)
                    m_air = d["coil"].c_air_des * f_op / CP_AIR * sp.duty
                    drop = np.where(act, sp.adiabatic.efficiency * (t_db - t_wb), 0.0)
                    net = evaporative_water_kg_s(m_air, drop, t_db) * 3600.0  # L/h
                    water += net * (1 + sp.adiabatic.bleed_ratio)
            if not chs:
                unmet = np.maximum(q - q_fc, 0.0)
                mode = np.where(q <= 0, 0, np.where(full, 1, 2))
        # ---------------- towers + WSE only (CP-9) ----------------
        if pl.type == "CP-9":
            appr = pl.wse.approach_k if pl.wse else 2.0
            target = t_set - appr
            unmet, pw, wl, f_t = self._towers_serve(rt, q, c_w / 4.186, t_wb, target, w, detail, add, wse=True)
            water += wl
            q_fc = q - unmet
            mode = np.where(q <= 0, 0, np.where(unmet > 1e-6, 2, 1))

        # ---------------- chillers ----------------
        q_ch = np.maximum(q - q_fc, 0.0) if pl.type not in ("CP-3", "CP-4", "CP-9") else np.zeros(n)
        if pl.type == "CP-7":
            q_ch, q_fc, mode, unmet_ch, wl = self._cp7(rt, q, t_ret, t_set, c_w, w, detail, add, chs, served,
                                                      it_frac, eu)
            water += wl
            unmet += unmet_ch
        elif chs and q_ch.any():
            tcond = {}
            for c in chs:
                sp = c["spec"]
                if c["model"].kind == "air_cooled":
                    tc = t_db + sp.recirculation_k
                    if sp.adiabatic and sp.adiabatic.enabled and not disable_adiabatic:
                        act = _adiab_active(sp.adiabatic, t_db) & (q_ch > 0)
                        adiab_flag |= act
                        tc = np.where(act, adiabatic_temperature(t_db, t_wb, sp.adiabatic.efficiency,
                                                                 sp.recirculation_k, sp.recirculation_order), tc)
                    tc = tc + tcond_extra.get(sp.name, 0.0)
                    tcond[sp.name] = tc
            if any(c["model"].kind == "water_cooled" for c in chs):
                res, wl = self._water_cooled(rt, q_ch, t_set, tcond, w, detail, add, chs)
                water += wl
            else:
                res = dispatch([c["model"] for c in chs], q_ch, t_set, tcond)
            add("chillers", res["power"])
            unmet += res["unmet"]
            for c in chs:
                r = res["types"][c["model"].name]
                detail[f"chiller:{c['model'].name}"] = {
                    "q": r["q"], "n_run": r["n_run"], "plr": r["plr"], "power": r["power"],
                    "t_cond": tcond.get(c["model"].name, np.zeros(n)), "standby_used": r["standby_used"],
                    "below_min": r["below_min"], "out_of_range": r["out_of_range"], "lwt": t_set}
                sp = c["spec"]
                # adiabatic water on condenser air (air-cooled)
                if c["model"].kind == "air_cooled" and sp.adiabatic and sp.adiabatic.enabled and not disable_adiabatic:
                    act = _adiab_active(sp.adiabatic, t_db) & (r["n_run"] > 0)
                    q_rej = r["q"] + r["power"]
                    m_air = q_rej / (CP_AIR * sp.condenser_air_dt_k)
                    drop = np.where(act, sp.adiabatic.efficiency * (t_db - t_wb), 0.0)
                    net = evaporative_water_kg_s(m_air, drop, t_db) * 3600.0
                    water += net * (1 + sp.adiabatic.bleed_ratio)
            if pl.type != "CP-2":
                mode = np.where(q <= 0, 0, np.where(q_fc > 0, np.where(q_ch > 0, 2, 1), 3))
        else:
            for c in chs:
                detail[f"chiller:{c['model'].name}"] = {"q": np.zeros(n), "n_run": np.zeros(n), "plr": np.zeros(n),
                                                        "power": np.zeros(n), "t_cond": np.zeros(n),
                                                        "standby_used": np.zeros(n),
                                                        "below_min": np.zeros(n, dtype=bool),
                                                        "out_of_range": np.zeros(n, dtype=bool), "lwt": t_set}
        # free cooling fans (CP-2) after staging (units running compressors carry fans in the EIR)
        if pl.type == "CP-2" and fc_chs:
            for c in fc_chs:
                nm = c["spec"].name
                nrun = detail.get(f"chiller:{nm}", {}).get("n_run", np.zeros(n))
                n_d = c["model"].n_duty
                f_op = np.where(mode == 1, fc_detail["f_full"], np.where(mode == 2, 1.0, 0.0))
                n_fc = np.where(mode == 1, n_d, np.where(mode == 2, np.maximum(n_d - nrun, 0), 0))
                res = c["fc"]["fan"].evaluate(f_direct=f_op, n_run_override=n_fc, n_hours=n)
                pw = res["power"]
                add("free_cooling_fans", pw)
                p_fc_fans += pw
                detail[f"free_cooling:{nm}"] = {"power": pw, "f": f_op, "n_fans": n_fc,
                                                "t_air": fc_detail["t_air"][nm], "q_fc_max": fc_detail["qmax"]}
        # integral pumps following running chillers
        for c, g, share in int_pumps:
            if c["spec"].integral_pump_units == "running":
                nrun = detail[f"chiller:{c['model'].name}"]["n_run"]
                if pl.type == "CP-2":
                    nrun = np.where(mode == 1, c["model"].n_duty, np.where(mode == 2, c["model"].n_duty, nrun))
                res = g.evaluate(q_served=q * share, v_req=v_plant * share, it_fraction=it_frac, n_hours=n,
                                 n_run_override=nrun)
                c["pump_res"] = res
                add(g.end_use, res["power"])
                pump_heat += res["power"] * g.heat_to_stream
                if g.on_ups:
                    ups_loads = ups_loads + res["power"]
        for c, g, share in int_pumps:
            r = c["pump_res"]
            detail[f"pump:{g.name}"] = {"power": r["power"], "f": r["f"], "f_eff": r["f_eff"], "n_run": r["n_run"],
                                        "bypass": r["bypass"]}
        t_sup_ach = t_set + np.where(c_w > 0, unmet / np.maximum(c_w, 1e-9), 0.0)
        plant_cols = {"q": q, "q_free_cooling": q_fc, "unmet": unmet, "mode": mode, "adiabatic": adiab_flag,
                      "t_return": t_ret, "t_supply": t_sup_ach, "flow_l_s": v_plant * 1000.0, "water_l": water}
        detail[f"plant:{pl.name}"] = plant_cols
        sizing[f"plant:{pl.name}"] = q
        q_delivered = q - unmet
        return {"pump_heat": pump_heat, "q_delivered": q_delivered, "unmet": unmet, "t_sup_ach": t_sup_ach,
                "water_l": water, "ups_loads": ups_loads}

    # ------------------------------------------------------------------
    def _cw_setpoint(self, pl, w):
        cw = pl.condenser_water
        r = cw.reset if cw else None
        if r is None:
            return np.clip(w.t_wb + 3.0, 12.78, 23.89)
        if r.type == "wetbulb_offset":
            return np.clip(w.t_wb + r.offset_k, r.min_c, r.max_c)
        if r.type == "drybulb_offset":
            return np.clip(w.t_db + r.offset_k, r.min_c, r.max_c)
        return np.full(w.n, r.min_c if r.type == "fixed" else 29.4)

    def _towers_serve(self, rt, q_kw, m_w_total, t_wb, target, w, detail, add, wse=False):
        """Towers reject q_kw with total water flow m_w (kg/s) to reach target leaving temperature.
        Returns (deficit kW, fan power, water L/h, f)."""
        n = len(q_kw)
        towers = rt["towers"]
        n_tot = sum(t["spec"].duty for t in towers) or 1
        m_unit = np.maximum(m_w_total / n_tot, 1e-6)
        q_unit = q_kw / n_tot
        unmet = np.zeros(n)
        pw_tot = np.zeros(n)
        water = np.zeros(n)
        f_out = np.zeros(n)
        for t in towers:
            u = t["unit"]
            f, sat = u.solve_f(q_unit, m_unit, t_wb, target, f_min=t["fan"].f_min, p_kpa=w.p_kpa)
            t_leave = np.where(sat, u.leaving_temp(q_unit, m_unit, t_wb, 1.0, w.p_kpa), target)
            deficit = np.maximum(t_leave - target, 0.0) * m_unit * 4.186 * t["spec"].duty
            unmet += deficit
            res = t["fan"].evaluate(f_direct=np.where(q_kw > 0, f, 0.0), n_hours=n)
            pw = res["power"]
            add("heat_rejection_fans", pw)
            pw_tot += pw
            share = t["spec"].duty / n_tot
            evap = tower_evaporation_kg_s(q_kw * share, w.t_db, w.w, t_wb, w.p_kpa)
            blow = evap / (t["spec"].coc - 1.0)
            drift = t["spec"].drift_fraction * m_w_total * share
            water += (evap + blow + drift) * 3600.0
            f_out = f
            detail[f"tower:{t['spec'].name}"] = {"power": pw, "f": f, "t_leave": t_leave, "saturated": sat,
                                                 "evaporation_l_h": evap * 3600, "water_l_h": (evap + blow + drift) * 3600}
        return unmet, pw_tot, water, f_out

    def _water_cooled(self, rt, q_ch, t_set, tcond, w, detail, add, chs):
        """Water-cooled chillers with towers (CP-8) or dry coolers (CP-10) on the condenser."""
        pl = rt["plant"]
        n = w.n
        cw_set = self._cw_setpoint(pl, w)
        t_cw = cw_set.copy()
        dt_cw = pl.condenser_water.design_dt_k if pl.condenser_water else 5.5
        res = None
        water = np.zeros(n)
        for _ in range(4):
            for c in chs:
                if c["model"].kind == "water_cooled":
                    tcond[c["model"].name] = t_cw
            res = dispatch([c["model"] for c in chs], q_ch, t_set, tcond)
            q_cond = sum(res["types"][c["model"].name]["q"] + res["types"][c["model"].name]["power"]
                         for c in chs if c["model"].kind == "water_cooled")
            m_cw = q_cond / (4.186 * dt_cw)
            m_cw_des = sum(c["model"].q_ref * (1 + 1 / c["model"].cop_ref) * res["types"][c["model"].name]["n_run"]
                           for c in chs if c["model"].kind == "water_cooled") / (4.186 * dt_cw)
            m_cw = np.maximum(m_cw, m_cw_des)
            if rt["towers"]:
                tw = rt["towers"]
                n_tot = sum(t["spec"].duty for t in tw)
                m_unit = np.maximum(m_cw / n_tot, 1e-6)
                t_new = np.zeros(n)
                for t in tw:
                    u = t["unit"]
                    f, sat = u.solve_f(q_cond / n_tot, m_unit, w.t_wb, cw_set, f_min=t["fan"].f_min, p_kpa=w.p_kpa)
                    tl = np.where(sat, u.leaving_temp(q_cond / n_tot, m_unit, w.t_wb, 1.0, w.p_kpa), cw_set)
                    t_new = np.maximum(t_new, tl)
            elif rt["dry"]:
                ds = rt["dry"]
                n_tot = sum(d["spec"].duty for d in ds)
                cwu = m_cw * 4.186 / n_tot
                t_new = np.zeros(n)
                for d in ds:
                    ta = w.t_db + d["spec"].recirculation_k
                    # leaving temperature at full fan for this load: solve T_in such that q(1, T_in) = load
                    load = q_cond / n_tot
                    t_in = bisect(lambda ti: d["coil"].q(1.0, cwu, ti, ta) - load, ta, ta + 80.0)
                    t_full = t_in - load / np.maximum(cwu, 1e-9)
                    t_new = np.maximum(t_new, np.maximum(cw_set, t_full))
            else:
                t_new = cw_set
            t_cw = t_new
        # final heat rejection fan powers and water
        q_cond = sum(res["types"][c["model"].name]["q"] + res["types"][c["model"].name]["power"]
                     for c in chs if c["model"].kind == "water_cooled")
        m_cw = np.maximum(q_cond / (4.186 * dt_cw), m_cw_des)
        if rt["towers"]:
            _, _, wl, _ = self._towers_serve(rt, q_cond, m_cw, w.t_wb, t_cw, w, detail, add)
            water += wl
        elif rt["dry"]:
            n_tot = sum(d["spec"].duty for d in rt["dry"])
            cwu = m_cw * 4.186 / n_tot
            for d in rt["dry"]:
                ta = w.t_db + d["spec"].recirculation_k
                f, _, _ = d["coil"].solve_f(q_cond / n_tot, cwu, t_cw + q_cond / np.maximum(m_cw * 4.186, 1e-9), ta,
                                            f_min=d["fan"].f_min)
                r = d["fan"].evaluate(f_direct=np.where(q_cond > 0, f, 0.0), n_hours=n)
                add("heat_rejection_fans", r["power"])
                detail[f"dry_cooler:{d['spec'].name}"] = {"power": r["power"], "f": f, "t_cw": t_cw}
        self._cw_pumps(rt, res, chs, add, detail, n)
        detail[f"condenser:{pl.name}"] = {"t_cw": t_cw, "t_cw_set": cw_set, "q_cond": q_cond}
        return res, water

    def _cw_pumps(self, rt, res, chs, add, detail, n):
        g = rt["cw_pump"]
        if g is None:
            return
        nrun = sum(res["types"][c["model"].name]["n_run"] for c in chs if c["model"].kind == "water_cooled")
        nrun = np.minimum(nrun, g.n_energised)
        r = g.evaluate(q_served=np.where(nrun > 0, 1.0, 0.0), it_fraction=np.ones(n), n_hours=n,
                       f_direct=np.ones(n), n_run_override=nrun)
        add(g.end_use, r["power"])
        detail[f"pump:{g.name}"] = {"power": r["power"], "n_run": r["n_run"], "f": r["f"], "f_eff": r["f_eff"]}

    def _cp7(self, rt, q, t_ret, t_set, c_w, w, detail, add, chs, served, it_frac, eu):
        """Water-cooled chillers + towers + WSE (CP-7): full / partial / mechanical."""
        pl = rt["plant"]
        n = w.n
        appr = pl.wse.approach_k if pl.wse else 2.0
        m_chw = c_w / 4.186
        towers = rt["towers"]
        n_tot = sum(t["spec"].duty for t in towers)
        # full WSE feasibility: towers reject q at target t_set - approach with CHW-equivalent flow
        target = t_set - appr
        full = np.ones(n, dtype=bool)
        for t in towers:
            u = t["unit"]
            _, sat = u.solve_f(q / n_tot, np.maximum(m_chw / n_tot, 1e-6), w.t_wb, target, f_min=t["fan"].f_min,
                               p_kpa=w.p_kpa)
            full &= ~sat
        full &= q > 0
        # partial / mechanical: towers at full fan with WSE + condenser heat
        tcond = {c["model"].name: np.zeros(n) for c in chs}
        q_wse = np.zeros(n)
        cw_set = self._cw_setpoint(pl, w)
        dt_cw = pl.condenser_water.design_dt_k if pl.condenser_water else 5.5
        res = None
        t_cw = cw_set.copy()
        for _ in range(6):
            q_ch = np.where(full, 0.0, np.maximum(q - q_wse, 0.0))
            for c in chs:
                tcond[c["model"].name] = t_cw
            res = dispatch([c["model"] for c in chs], q_ch, t_set, tcond)
            q_rej = q_wse + q_ch + res["power"]
            m_cw = np.maximum(q_rej / (4.186 * dt_cw), m_chw)
            m_unit = np.maximum(m_cw / n_tot, 1e-6)
            t_full = np.zeros(n)
            for t in towers:
                t_full = np.maximum(t_full, t["unit"].leaving_temp(q_rej / n_tot, m_unit, w.t_wb, 1.0, w.p_kpa))
            econ = (t_full + appr) < t_ret - 0.5
            q_wse_new = np.where(econ & ~full, np.minimum(q, m_chw * 4.186 * np.maximum(t_ret - t_full - appr, 0.0)),
                                 0.0)
            q_wse = 0.5 * (q_wse + q_wse_new)
            t_cw = np.where(q_wse > 0, t_full, np.maximum(cw_set, t_full))
        q_ch = np.where(full, 0.0, np.maximum(q - q_wse, 0.0))
        for c in chs:
            tcond[c["model"].name] = t_cw
        res = dispatch([c["model"] for c in chs], q_ch, t_set, tcond)
        add("chillers", res["power"])
        q_rej = np.where(full, q, q_wse + q_ch + res["power"])
        tgt = np.where(full, target, np.where(q_wse > 0, w.t_wb - 50.0, cw_set))  # partial: full fan
        m_cw = np.where(full, m_chw, np.maximum(q_rej / (4.186 * dt_cw), m_chw))
        unmet_t, _, water, _ = self._towers_serve(rt, q_rej, m_cw, w.t_wb, tgt, w, detail, add)
        unmet = np.where(full, unmet_t, 0.0) + res["unmet"]
        for c in chs:
            r = res["types"][c["model"].name]
            detail[f"chiller:{c['model'].name}"] = {"q": r["q"], "n_run": r["n_run"], "plr": r["plr"],
                                                    "power": r["power"], "t_cond": t_cw,
                                                    "standby_used": r["standby_used"], "below_min": r["below_min"],
                                                    "out_of_range": r["out_of_range"], "lwt": t_set}
        self._cw_pumps(rt, res, chs, add, detail, n)
        q_fc = np.where(full, q, q_wse)
        mode = np.where(q <= 0, 0, np.where(full, 1, np.where(q_wse > 0, 2, 3)))
        return q_ch, q_fc, mode, unmet, water

    # ------------------------------------------------------------------
    def _other_end_uses(self, w: Weather, warnings: list[str]):
        o = self.p.other
        n = w.n
        out: dict[str, tuple[np.ndarray, str]] = {}
        heat: dict[str, np.ndarray] = {}
        annual: dict[str, float] = {}
        diesel_l = 0.0
        diesel_kwh = 0.0
        g = o.generators
        if g and g.count > 0:
            if g.format == "A":
                if g.fuel_l_per_h is None:
                    raise ValueError("generator testing Format A needs fuel_l_per_h")
                diesel_l = g.fuel_l_per_h * g.count * g.hours_per_test * g.tests_per_year
            else:
                diesel_l = float(g.annual_litres or 0.0)
            diesel_kwh = diesel_l * g.diesel_mwh_per_l * 1000.0
        j = o.jacket_heaters
        if j and j.kw_per_generator > 0:
            cnt = j.count if j.count is not None else (g.count if g else 0)
            frac = np.clip((j.t_off_c - w.t_db) / (j.t_off_c - j.t_on_c), 0.0, 1.0)
            if j.eflh_hours is not None:
                frac = frac * (j.eflh_hours / max(frac.sum(), 1e-9)) * (n / 8760.0)
            out["jacket_heaters"] = (cnt * j.kw_per_generator * frac, "infrastructure")
        lift_kwh = 0.0
        for lf in o.lifts:
            if lf.annual_kwh is not None:
                e = lf.annual_kwh
            else:
                if None in (lf.trips_per_year, lf.power_kw, lf.trip_time_s):
                    raise ValueError(f"lift {lf.name}: give annual_kwh or trips, power and trip time")
                e = lf.count * (lf.trips_per_year * lf.power_kw * lf.trip_time_s / 3600.0 * lf.running_factor
                                + lf.standby_kw * lf.standby_hours)
            annual[f"lift:{lf.name}"] = e
            lift_kwh += e
        if o.lifts:
            out["lifts"] = (np.full(n, lift_kwh / 8760.0), "infrastructure")
        for ld in o.loads:
            prof = schedules.profile(ld.profile, w.hour_of_day, w.is_weekend, self.base_dir)
            if ld.kw is not None:
                arr = ld.kw * prof
            elif ld.annual_kwh is not None:
                arr = ld.annual_kwh * prof / max(prof.sum(), 1e-9) * (n / 8760.0) if n == 8760 else \
                    np.full(n, ld.annual_kwh / 8760.0)
                annual[f"load:{ld.name}"] = ld.annual_kwh
            else:
                raise ValueError(f"load {ld.name}: give kw or annual_kwh")
            prev = out.get(ld.end_use)
            out[ld.end_use] = ((prev[0] if prev else 0) + arr, ld.boundary)
            if ld.heat_to_zone:
                heat[ld.heat_to_zone] = heat.get(ld.heat_to_zone, np.zeros(n)) + arr
        pv = np.zeros(n)
        if o.pv:
            pvs = o.pv
            if pvs.hourly_csv:
                import pandas as pd

                path = Path(pvs.hourly_csv)
                if not path.is_absolute():
                    path = self.base_dir / path
                pv = pd.read_csv(path).iloc[:, -1].to_numpy(dtype=float)[:n]
            else:
                ann = pvs.annual_kwh
                if ann is None and pvs.kw_peak and pvs.specific_yield_kwh_per_kw:
                    ann = pvs.kw_peak * pvs.specific_yield_kwh_per_kw
                if ann:
                    shape = np.maximum(w.ghi, 0.0)
                    pv = ann * shape / shape.sum() if shape.sum() > 0 else np.full(n, ann / n)
                    annual["pv"] = ann
        return out, heat, annual, diesel_l, diesel_kwh, pv


# ---------------------------------------------------------------------------
def _validate_plant_type(pl):
    t = pl.type
    has_ch = bool(pl.chillers)
    kinds = {c.kind for c in pl.chillers}
    ifc = any(c.free_cooling is not None and c.free_cooling.enabled for c in pl.chillers)
    rules = {
        "CP-1": has_ch and kinds == {"air_cooled"} and not pl.dry_coolers and not pl.towers,
        "CP-2": has_ch and kinds == {"air_cooled"} and ifc,
        "CP-3": not has_ch and bool(pl.dry_coolers),
        "CP-4": not has_ch and bool(pl.dry_coolers) and all(d.adiabatic for d in pl.dry_coolers),
        "CP-5": has_ch and bool(pl.dry_coolers),
        "CP-6": has_ch and bool(pl.dry_coolers) and all(d.adiabatic for d in pl.dry_coolers),
        "CP-7": has_ch and kinds == {"water_cooled"} and bool(pl.towers),
        "CP-8": has_ch and kinds == {"water_cooled"} and bool(pl.towers),
        "CP-9": not has_ch and bool(pl.towers),
        "CP-10": has_ch and kinds == {"water_cooled"} and bool(pl.dry_coolers),
    }
    if not rules[t]:
        raise ValueError(f"plant {pl.name}: equipment does not match {t} (REQ-UI-4). CP-1 air-cooled chillers; "
                         f"CP-2 air-cooled with free_cooling; CP-3/4 dry coolers only (4 adiabatic); CP-5/6 dry "
                         f"coolers + chillers; CP-7/8 water-cooled + towers (7 with WSE); CP-9 towers + HX; CP-10 "
                         f"water-cooled + dry coolers")


def _energised(r) -> int:
    duty = r.duty if r.duty is not None else 1
    if r.redundancy in ("2N_active", "0.5N+0.5N"):
        return duty + r.standby
    return duty


def _shares(r):
    out = []
    for s in r.serves:
        if isinstance(s, str):
            out.append((s, 1.0))
        else:
            out.append((s.zone, s.share))
    return out


def _zone_share_norm(units):
    tot: dict[str, float] = {}
    for r in units:
        for z, s in _shares(r):
            tot[z] = tot.get(z, 0.0) + s
    return {z: (t if t > 1.0 + 1e-9 else 1.0) for z, t in tot.items()}


def _shares_for(items, halls):
    """Share of each hall's heat taken by each serving CDU / FWU type (explicit share or equal split)."""
    out = {}
    for h in halls:
        serving = [x for x in items if h in x.serves]
        explicit = sum(x.share for x in serving if x.share)
        rest = [x for x in serving if not x.share]
        for x in serving:
            out[(x.name, h)] = x.share if x.share else (max(1.0 - explicit, 0.0) / len(rest) if rest else 0.0)
    return out


def _ru_end_use(r, zones) -> str:
    if r.end_use:
        return r.end_use
    t = r.type
    names = [s if isinstance(s, str) else s.zone for s in r.serves]
    office = any(zones.get(z) is not None and zones[z].category == "office" for z in names)
    if t in ("VRF", "split", "CRAC") and office:
        return "office_hvac"
    return {"CRAH": "crah_fans", "FCU": "fcu_fans", "PAC": "dx_water_cooled", "CRAC": "dx_air_cooled",
            "VRF": "dx_air_cooled", "split": "dx_air_cooled", "DX_dehumidifier": "dehumidifiers",
            "humidifier": "humidifiers", "OAF": "ventilation_fans", "EAF": "exhaust_fans"}[t]


def _activation(r, w) -> np.ndarray:
    a = r.activation
    v = r.activation_value
    if a == "always":
        return np.ones(w.n)
    if a == "never":
        return np.zeros(w.n)
    if v is None:
        raise ValueError(f"room unit {r.name}: activation {a} needs activation_value")
    if a == "outdoor_dewpoint_above":
        return (w.t_dp > v).astype(float)
    if a == "outdoor_dewpoint_below":
        return (w.t_dp < v).astype(float)
    if a == "outdoor_db_above":
        return (w.t_db > v).astype(float)
    return (w.t_db < v).astype(float)


def _adiab_active(ad, t_db):
    return (t_db >= ad.activation_c) if ad.activation_inclusive else (t_db > ad.activation_c)


def _ups_cap(u) -> float:
    mods = u.active_modules if u.active_modules is not None else u.modules * u.systems
    return float(mods * (u.module_kw or 0.0))
