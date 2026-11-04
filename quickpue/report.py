"""Calculation transparency: calculation report (REQ-OUT-T-1), explain (REQ-OUT-T-2),
assumptions page (REQ-PRE-1) and warnings (13.4)."""

from __future__ import annotations

import numpy as np

from .engine import end_use_label
from .sources import SOURCES

EQUATIONS = [
    ("S-EQ-01", "Q_liq = f_liq * P_IT ; Q_air = (1 - f_liq) * P_IT + lighting + people + allocated losses + fan heat"),
    ("S-EQ-02", "T_loop,req = T_TCS,sup - dT_approach(Q) ; dT_approach = dT_des * Q / Q_des (load_scaled) ; "
                "T_junc = T_rack,sup + (Q_liq / N_units) * R_th"),
    ("S-EQ-03", "Q_avail = Q_ref * CAPFT(T_lwt, T_cond) ; PLR = Q / Q_avail ; "
                "P = Q_avail / COP_ref * EIRFT(T_lwt, T_cond) * EIRFPLR(max(PLR, PLR_min)) [* PLR / PLR_min cycling]"),
    ("S-EQ-04/05", "f_eff = max(f, f_min) ; P = N_run * P_des * FFLP(f_eff) [* k_drive(f_eff)] ; FFLP normalised "
                   "to 1 at f = 1"),
    ("S-EQ-04/05", "M1 f = Q_served / Q_des * N_duty / N_run ; M2 f = V_req / (N_run * V_des), "
                   "V_req = Q / (rho * cp * dT) ; M3 f = 1 ; M5 f solved (heat transfer) ; M6 f = table(IT fraction)"),
    ("S-EQ-09", "R-EPSEQ: P = (N_full * FFLP(1) + FFLP(f_part)) * P_des"),
    ("S-EQ-10", "Tower: c_s = (h_sat(T_w,in) - h_sat(T_wb)) / (T_w,in - T_wb) ; C_air = m_a * c_s ; "
                "UA = UA_des * f^0.6 * (m_w / m_w,des)^0.4 ; Q = eps_cf(NTU, Cr) * C_min * (T_w,in - T_wb)"),
    ("S-EQ-11", "Dry cooler / free cooling coil: C_air = C_air,des * f ; UA = UA_des * f^n ; "
                "Q = eps_crossflow(NTU, Cr) * C_min * (T_w,in - T_air) ; fan speed solved by bisection"),
    ("S-EQ-12", "Adiabatic: T_eff = T_db - eps * (T_db - T_wb) + dT_recirc (after pads) or "
                "(T_db + dT) - eps * ((T_db + dT) - T_wb) (before pads)"),
    ("S-EQ-13", "Water: evaporation = m_a,eff * (W_sat(T_wb + 3) - W_in), m_a,eff = Q / (h_out - h_in) ; "
                "blowdown = evap / (COC - 1) ; drift = drift_fraction * m_w ; pads net = m_a cp dT / h_fg"),
    ("S-EQ-16", "Jacket heater fraction = clamp((T_off - T_db) / (T_off - T_on), 0, 1) ; diesel MWh = L * 0.01076"),
    ("S-EQ-17", "PUE = (E_IT + E_infra,gross + E_contingency - E_PV + E_diesel) / E_IT ; WUE = water / E_IT ; "
                "GHG = E_elec,net * EF_e + V_diesel * EF_d"),
    ("S-EQ-18", "UPS: x = P_out / (active modules * module kW) ; eta = table(x) ; "
                "loss = P_out * (1/eta - 1) (physical) or P_out * (1 - eta) (simplified)"),
    ("S-EQ-19", "Transformer: loss = percent * throughput(basis) or N * (P_nl + P_fl * (S / S_rated)^2)"),
    ("S-EQ-20", "Zone: Q = losses + equipment + lighting + people + UA (T_out - T_set) + rho cp V_inf+OA (T_out - "
                "T_set) + fan heat ; latent from people and OA (DX units only)"),
    ("S-EQ-21", "DX: P_comp = Q / COP(T_cond) [or Q_cap / COP * EIRFPLR(PLR)] ; COP(T) = COP * (1 + slope (T - "
                "T_rated)) ; PAC condenser heat Q + P to loop"),
    ("S-EQ-24", "DT-A blend: V_draw = Q_HT / (rho cp (T_HT,ret - T_MT,sup)) ; DT-B HX: T_HT,sup >= T_MT,sup + "
                "approach ; DT-D split: residual of the dedicated plant passed to the parent loop"),
    ("10.2", "Coupling: iterate electrical losses -> zone gains -> cooling power until |dP_infra| / P_infra <= tol"),
]


def calculation_report(res) -> str:
    L = [f"# Calculation report: {res.project.project.name}", "",
         f"QuickPUE {res.version}, schema {res.schema_version}. Input: `{res.loaded.source_path}`.", "",
         "## Equations used", "", "| Source ID | Equation |", "|-|-|"]
    for sid, eq in EQUATIONS:
        L.append(f"| {sid} | `{eq}` |")
    L += ["", "## Source register (Section 15)", "", "| ID | Item | Source |", "|-|-|-|"]
    for k, v in SOURCES.items():
        L.append(f"| {k} | {v['item']} | {v['source']} |")
    L += ["", "## Curves and coefficients by equipment type", ""]
    eng = res.engine
    from .runner import _all_groups

    groups = _all_groups(eng)
    for rt in eng.plant_rt.values():
        for c in rt["chillers"]:
            m = c["model"]
            L.append(f"* Chiller **{m.name}**: {m.n_duty} duty + {m.n_standby} standby x {m.q_ref:,.0f} kW, COP "
                     f"{m.cop_ref:g} at LWT {m.lwt_ref:g} C / ECT {m.ect_ref:g} C. {m.curves.source}.")
            L.append(f"  * {m.curves.capft.describe()}")
            L.append(f"  * {m.curves.eirft.describe()}")
            L.append(f"  * {m.curves.eirfplr.describe()}; minimum PLR {m.min_plr:g} ({m.below_min})")
            if m.curves.fit_report:
                L.append(f"  * Fit report: {m.curves.fit_report}")
            if c["fc"]:
                coil = c["fc"]["coil"]
                L.append(f"  * Free cooling coil: rated {coil.rated_q:,.0f} kW at {coil.rated_dt:g} K, UA "
                         f"{coil.ua_des:.2f} kW/K, C_air {coil.c_air_des:.1f} kW/K, n {coil.n_exp:g}")
                groups.append(c["fc"]["fan"])
        for d in rt["dry"]:
            L.append(f"* Dry cooler **{d['spec'].name}**: UA {d['coil'].ua_des:.2f} kW/K per unit, C_air "
                     f"{d['coil'].c_air_des:.1f} kW/K, rated {d['spec'].rated_capacity_kw:,.0f} kW")
            groups.append(d["fan"])
        for t in rt["towers"]:
            L.append(f"* Tower **{t['spec'].name}**: UA {t['unit'].ua_des:.2f} kW/K per cell, air {t['unit'].m_a_des:.1f} "
                     f"kg/s, water {t['unit'].m_w_des:.1f} kg/s")
            groups.append(t["fan"])
    for g in groups:
        L.append(f"* Fan / pump **{g.name}** ({end_use_label(g.end_use)[0]}): P_des {g.p_des_kw:g} kW x "
                 f"{g.n_duty} duty + {g.n_standby} standby ({g.redundancy}); {g.method}, f_min {g.f_min:g}, "
                 f"{g.rule}; {g.curve.describe()}"
                 + (f"; M1 design load {g.design_load_kw:,.1f} kW" if g.method == "M1" else ""))
    for u in res.project.electrical.ups:
        L.append(f"* UPS **{u.name}** ({u.path}): {u.modules} x {u.systems} modules x {u.module_kw:,.1f} kW; "
                 f"efficiency table {u.efficiency}; convention {u.loss_convention or res.project.electrical.loss_convention}")
    L += ["", "## Defaults and auto-sized values applied", ""]
    for e in res.register:
        if e.origin in ("auto", "preset"):
            L.append(f"* `{e.path}` = {_fmt(e.value)} {e.unit} ({e.origin}: {e.ref})")
    L += ["", f"Design condition for sizing: {res.design_label}.", ""]
    return "\n".join(L)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.4g}"
    return str(v)


def assumptions_page(res) -> str:
    """One page 'assumptions applied' list printed before results (REQ-PRE-1)."""
    L = ["ASSUMPTIONS APPLIED", "==================="]
    L += [f"- {a}" for a in res.assumptions]
    auto = [e for e in res.register if e.origin == "auto"]
    pre = [e for e in res.register if e.origin == "preset"]
    L.append(f"- {len(pre)} preset default values and {len(auto)} auto-sized values (see the input register).")
    for e in auto[:40]:
        L.append(f"  * {e.path} = {_fmt(e.value)} {e.unit}: {e.ref}")
    if len(auto) > 40:
        L.append(f"  * ... {len(auto) - 40} more")
    pend = [e for e in res.register if e.kind == "pending_manufacturer"]
    for e in pend:
        L.append(f"- PENDING MANUFACTURER: {e.path} = {_fmt(e.value)} {e.unit} ({e.ref})")
    for pl in res.project.plants:
        for c in pl.chillers:
            if not c.curves.table and not (c.curves.capft and c.curves.eirft):
                L.append(f"- PENDING MANUFACTURER: chiller {c.name} uses library curve analogue "
                         f"{c.curves.library or 'default'} normalised to its rated point")
    L.append(f"- Design condition: {res.design_label}")
    return "\n".join(L)


def all_warnings(res) -> list[str]:
    out = list(dict.fromkeys(res.warnings))
    for s in res.scenarios:
        for w in s.warnings:
            out.append(f"[{s.name}] {w}")
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
def explain(res, item: str, hour: int = 0, scenario: str | None = None) -> str:
    """Equation chain and input values for one result at one hour (REQ-OUT-T-2).

    item: an end-use key (e.g. 'chillers', 'fwu_fans', 'ups_loss_it', 'pue') or an equipment name
    (chiller, fan / pump group, UPS, transformer)."""
    s = res.scenario(scenario) if scenario else res.scenarios[0]
    h = int(hour)
    sim = s.sim
    eng = res.engine
    w = res.weather
    L = [f"explain {item!r}, scenario {s.name}, hour index {h} ({w.month[h]:02d}-{w.day[h]:02d} hour {w.hour[h]}), "
         f"T_db {w.t_db[h]:.1f} C, T_wb {w.t_wb[h]:.1f} C, IT {s.hourly.it_kw[h]:,.1f} kW"]
    if item == "pue":
        it = s.hourly.it_kw[h]
        L.append(f"S-EQ-17: hourly PUE = (IT + infrastructure net + diesel spread) / IT = "
                 f"({it:,.1f} + {s.hourly.infra_net_kw[h]:,.1f} + {s.metrics['diesel_kwh'] / 8760:,.2f}) / {it:,.1f} "
                 f"= {s.hourly.pue[h]:.4f}")
        L.append(f"Annual PUE (energy weighted, REQ-C-M-1) = {s.metrics['pue']:.4f}")
        return "\n".join(L)
    from .runner import _all_groups

    groups = {g.name: g for g in _all_groups(eng)}
    for rt in eng.plant_rt.values():
        for c in rt["chillers"]:
            if c["fc"]:
                groups[c["fc"]["fan"].name] = c["fc"]["fan"]
        for d in rt["dry"]:
            groups[d["fan"].name] = d["fan"]
        for t in rt["towers"]:
            groups[t["fan"].name] = t["fan"]
    # end-use key: list contributing details
    if item in sim.eu:
        L.append(f"End use {item} ({end_use_label(item)[0]}): {sim.eu[item][h]:,.3f} kW this hour, "
                 f"{sim.eu[item].sum() / 1e3:,.1f} MWh/yr")
        for g in groups.values():
            if g.end_use == item:
                L += _explain_group(g, sim, h)
        for name, d in sim.detail.items():
            if name.startswith("chiller:") and item == "chillers":
                L += _explain_chiller(eng, name[8:], d, h)
            if name.startswith("loss:") and _loss_eu(eng, name[5:]) == item:
                L += _explain_loss(res, name[5:], d, h)
        return "\n".join(L)
    if item in groups:
        return "\n".join(L + _explain_group(groups[item], sim, h))
    if f"chiller:{item}" in sim.detail:
        return "\n".join(L + _explain_chiller(eng, item, sim.detail[f"chiller:{item}"], h))
    if f"loss:{item}" in sim.detail:
        return "\n".join(L + _explain_loss(res, item, sim.detail[f"loss:{item}"], h))
    raise KeyError(f"unknown item {item!r}; try an end-use key ({', '.join(sim.eu)}), 'pue', or an equipment name")


def _loss_eu(eng, name):
    for n, k in eng.elements:
        if n == name:
            return {"pdu": "pdu_loss", "ups_it": "ups_loss_it", "ups_mech": "ups_loss_mech",
                    "transformer_hv": "transformer_hv", "transformer_mvlv": "transformer_mvlv",
                    "distribution": "distribution_loss"}[k]
    return None


def _find_detail(sim, gname):
    for name, d in sim.detail.items():
        if name.endswith(gname) or name.split(":", 1)[-1] == gname.rsplit(" ", 1)[0]:
            if "f" in d and "power" in d:
                return d
    return None


def _explain_group(g, sim, h):
    d = None
    for name, dd in sim.detail.items():
        key = name.split(":", 1)[-1]
        if key == g.name or (key + " fans") == g.name or (key + " pump") == g.name:
            d = dd
            break
    L = [f"  {g.name}: S-EQ-04/05 P = N_run * P_des * FFLP(f_eff); method {g.method}, curve {g.curve.curve_id}, "
         f"f_min {g.f_min:g}, {g.rule}"]
    if d is not None and "f" in d:
        f = float(d["f"][h])
        fe = float(d.get("f_eff", d["f"])[h])
        nr = float(d.get("n_run", np.zeros_like(d["f"]))[h]) if "n_run" in d else float("nan")
        pw = float(d.get("power", d.get("fan_power", np.zeros_like(d["f"])))[h])
        L.append(f"    f = {f:.4f}; f_eff = max(f, {g.f_min:g}) = {fe:.4f}; N_run = {nr:g}; FFLP(f_eff) = "
                 f"{float(g.curve(np.array([fe]))[0]):.4f}; P = {nr:g} x {g.p_des_kw:g} x FFLP = {pw:,.3f} kW")
    return L


def _explain_chiller(eng, name, d, h):
    m = None
    for rt in eng.plant_rt.values():
        for c in rt["chillers"]:
            if c["model"].name == name:
                m = c["model"]
    if m is None:
        return []
    n = d["n_run"][h]
    lwt = float(np.atleast_1d(d["lwt"])[h])
    tc = float(d["t_cond"][h])
    cap = float(m.capacity(lwt, tc))
    eirft = float(m.curves.eirft(lwt, tc))
    plr = float(d["plr"][h])
    return [f"  Chiller {name}: S-EQ-03 with T_lwt {lwt:.2f} C, T_cond {tc:.2f} C",
            f"    CAPFT = {float(m.curves.capft(lwt, tc)):.4f}; Q_avail = {m.q_ref:,.0f} x CAPFT = {cap:,.1f} kW per unit",
            f"    Load {d['q'][h]:,.1f} kW on N_run = {n:g}; PLR = {plr:.4f}; EIRFT = {eirft:.4f}; "
            f"EIRFPLR(max(PLR, {m.min_plr:g})) = {float(m.curves.eirfplr(max(plr, m.min_plr))):.4f}",
            f"    P = N_run x Q_avail / COP_ref x EIRFT x EIRFPLR = {d['power'][h]:,.2f} kW"]


def _explain_loss(res, name, d, h):
    L = [f"  Loss element {name}: {d['loss'][h]:,.3f} kW"]
    if "load_frac" in d:
        L.append(f"    S-EQ-18 UPS: P_out = {d['pout'][h]:,.1f} kW; load fraction x = {d['load_frac'][h]:.4f}; "
                 f"convention {res.project.electrical.loss_convention}")
    if "throughput" in d:
        L.append(f"    S-EQ-19 transformer: throughput {d['throughput'][h]:,.1f} kW")
    if "base" in d:
        L.append(f"    distribution: base {d['base'][h]:,.1f} kW")
    return L
