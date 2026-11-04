"""Electric EIR chiller model, curve library, curve fitting and staging (S-EQ-03, REQ-C-CH-1 to 7)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

import numpy as np

from .curves import Biquadratic, PolyPLR


def library() -> dict:
    with resources.files("quickpue.data").joinpath("chiller_library.json").open() as fh:
        return json.load(fh)


DEFAULT_LIBRARY = {"air_cooled": "EP-ACC-SCROLL-434", "water_cooled": "EP-WCC-CENT-VSD-1495"}


@dataclass
class ChillerCurves:
    capft: Biquadratic
    eirft: Biquadratic
    eirfplr: PolyPLR
    source: str
    pending_manufacturer: bool = False
    fit_report: dict = field(default_factory=dict)


def curves_from_library(entry_id: str, lwt_ref: float, ect_ref: float, clamp: bool = True) -> ChillerCurves:
    lib = library()
    if entry_id not in lib:
        raise ValueError(f"unknown chiller library entry {entry_id!r}; available: {', '.join(lib)}")
    e = lib[entry_id]
    dx = lwt_ref - e["ref_lwt_c"]
    dy = ect_ref - e["ref_ect_c"]
    cap = Biquadratic(e["CAPFT"][:6], *e["CAPFT"][6:10], x_shift=dx, y_shift=dy, clamp=clamp, name="CAPFT")
    eir = Biquadratic(e["EIRFT"][:6], *e["EIRFT"][6:10], x_shift=dx, y_shift=dy, clamp=clamp, name="EIRFT")
    cap.scale = 1.0 / float(cap(lwt_ref, ect_ref))
    eir.scale = 1.0 / float(eir(lwt_ref, ect_ref))
    plr_c = e["EIRFPLR"][:3]
    p1 = sum(plr_c)
    plr = PolyPLR([c / p1 for c in plr_c], x_min=e["EIRFPLR"][3], x_max=e["EIRFPLR"][4])
    src = (f"S-DEF-01 library analogue {entry_id} ({e['dataset']}: {e['entry']}), "
           f"normalised to the project rated point by temperature shift (S-EQ-23)")
    return ChillerCurves(cap, eir, plr, src, pending_manufacturer=True)


def curves_from_coefficients(spec: dict, lwt_ref: float, ect_ref: float, clamp: bool = True,
                             normalize: bool = True) -> ChillerCurves:
    def bq(name, c):
        c = list(map(float, c))
        lims = c[6:10] if len(c) >= 10 else [-1e9, 1e9, -1e9, 1e9]
        b = Biquadratic(c[:6], *lims, clamp=clamp and len(c) >= 10, name=name)
        if normalize:
            b.scale = 1.0 / float(b(lwt_ref, ect_ref))
        return b

    plr_c = list(map(float, spec["eirfplr"]))
    lims = (plr_c[3], plr_c[4]) if len(plr_c) == 5 else (0.0, 1.0)
    coeffs = plr_c[:3] if len(plr_c) == 5 else plr_c
    if normalize:
        s = sum(coeffs)
        coeffs = [c / s for c in coeffs]
    return ChillerCurves(bq("CAPFT", spec["capft"]), bq("EIRFT", spec["eirft"]),
                         PolyPLR(coeffs, x_min=lims[0], x_max=lims[1]), spec.get("source", "user coefficients"))


def _design_matrix(x, y, use_x: bool, use_y: bool):
    cols = [np.ones_like(x)]
    names = [0]
    if use_x:
        cols += [x, x * x]
        names += [1, 2]
    if use_y:
        cols += [y, y * y]
        names += [3, 4]
    if use_x and use_y:
        cols.append(x * y)
        names.append(5)
    return np.column_stack(cols), names


def fit_biquadratic(x, y, z, name):
    x, y, z = map(lambda a: np.asarray(a, dtype=float), (x, y, z))
    use_x = np.ptp(x) > 1e-9
    use_y = np.ptp(y) > 1e-9
    A, idx = _design_matrix(x, y, use_x, use_y)
    if len(z) < A.shape[1]:
        raise ValueError(f"{name}: need at least {A.shape[1]} points to fit, have {len(z)}")
    sol, *_ = np.linalg.lstsq(A, z, rcond=None)
    c = [0.0] * 6
    for k, v in zip(idx, sol):
        c[k] = float(v)
    b = Biquadratic(c, float(x.min()), float(x.max()), float(y.min()), float(y.max()), clamp=True, name=name)
    pred = b.raw(x, y)
    err = pred - z
    return b, {"rms": float(np.sqrt(np.mean(err**2))), "max_abs": float(np.max(np.abs(err))), "n": int(len(z)),
               "lwt_varies": bool(use_x), "tcond_varies": bool(use_y)}


def curves_from_table(rows: list[dict], q_ref: float, cop_ref: float, lwt_ref: float, ect_ref: float,
                      clamp: bool = True) -> ChillerCurves:
    """Fit CAPFT / EIRFT / EIRFPLR from manufacturer data (REQ-C-CH-2).

    Each row: lwt_c, ect_c, capacity_kw (available capacity at full load) or load_kw, power_kw, plr (default 1).
    Full-load rows (plr = 1) fit CAPFT and EIRFT; part-load rows fit EIRFPLR.
    """
    full = [r for r in rows if float(r.get("plr", 1.0)) >= 0.999]
    part = [r for r in rows if float(r.get("plr", 1.0)) < 0.999]
    if len(full) < 3:
        raise ValueError("chiller table fit needs at least 3 full-load rows")
    x = np.array([float(r["lwt_c"]) for r in full])
    y = np.array([float(r["ect_c"]) for r in full])
    qa = np.array([float(r.get("capacity_kw", r.get("load_kw"))) for r in full])
    pa = np.array([float(r["power_kw"]) for r in full])
    p_ref = q_ref / cop_ref
    cap, rep_c = fit_biquadratic(x, y, qa / q_ref, "CAPFT")
    eir, rep_e = fit_biquadratic(x, y, (pa / qa) / (p_ref / q_ref), "EIRFT")
    cap.clamp = eir.clamp = clamp
    rep = {"CAPFT": rep_c, "EIRFT": rep_e, "CAPFT_at_rated": float(cap(lwt_ref, ect_ref)),
           "EIRFT_at_rated": float(eir(lwt_ref, ect_ref))}
    if part:
        xp = np.array([float(r["lwt_c"]) for r in part])
        yp = np.array([float(r["ect_c"]) for r in part])
        load = np.array([float(r.get("load_kw", r.get("capacity_kw"))) for r in part])
        pw = np.array([float(r["power_kw"]) for r in part])
        qav = q_ref * cap(xp, yp)
        plr = np.concatenate([load / qav, np.ones(len(full))])
        obs = np.concatenate([pw / (qav / cop_ref * eir(xp, yp)), np.ones(len(full))])
        A = np.column_stack([np.ones_like(plr), plr, plr * plr])
        sol, *_ = np.linalg.lstsq(A, obs, rcond=None)
        pc = [float(v) for v in sol]
        err = A @ sol - obs
        rep["EIRFPLR"] = {"rms": float(np.sqrt(np.mean(err**2))), "max_abs": float(np.max(np.abs(err))),
                          "n": int(len(plr))}
        eirfplr = PolyPLR(pc, x_min=float(min(plr.min(), 1.0)), x_max=1.0)
    else:
        eirfplr = PolyPLR([0.0, 1.0, 0.0])
        rep["EIRFPLR"] = "no part-load rows: linear EIRFPLR assumed"
    return ChillerCurves(cap, eir, eirfplr, "manufacturer table fit (REQ-C-CH-2)", fit_report=rep)


# ---------------------------------------------------------------------------
@dataclass
class ChillerModel:
    name: str
    kind: str  # air_cooled | water_cooled
    n_duty: int
    n_standby: int
    q_ref: float  # kW per unit
    cop_ref: float
    lwt_ref: float
    ect_ref: float
    curves: ChillerCurves
    min_plr: float = 0.1
    below_min: str = "cycling"
    stage_up: float = 1.0
    standby_on_shortfall: bool = True
    priority: int = 1
    lwt_range: tuple | None = None
    tcond_range: tuple | None = None

    def capacity(self, lwt, tcond):
        return self.q_ref * self.curves.capft(lwt, tcond)

    def unit_power(self, q_unit, lwt, tcond):
        """Electric power per running unit (kW) delivering q_unit (kW)."""
        q_av = self.capacity(lwt, tcond)
        plr = np.where(q_av > 0, np.asarray(q_unit) / np.maximum(q_av, 1e-9), 0.0)
        eirft = self.curves.eirft(lwt, tcond)
        base = q_av / self.cop_ref * eirft
        plr_eval = np.maximum(plr, self.min_plr)
        p = base * self.curves.eirfplr(plr_eval)
        if self.below_min == "cycling":
            p = np.where(plr < self.min_plr, p * plr / self.min_plr, p)
        return np.where(np.asarray(q_unit) > 0, p, 0.0), plr

    def validity_flags(self, lwt, tcond):
        a = self.curves.capft.out_of_range(lwt, tcond) | self.curves.eirft.out_of_range(lwt, tcond)
        if self.lwt_range:
            a = a | (np.asarray(lwt) < self.lwt_range[0]) | (np.asarray(lwt) > self.lwt_range[1])
        if self.tcond_range:
            a = a | (np.asarray(tcond) < self.tcond_range[0]) | (np.asarray(tcond) > self.tcond_range[1])
        return a


def dispatch(chillers: list[ChillerModel], q_load, lwt, tcond: dict[str, np.ndarray]) -> dict:
    """Stage chillers by priority (REQ-C-CH-3): minimum number of duty units with PLR <= stage-up,
    equal loading within a type, standby only on shortfall.  Returns per-type and total results."""
    q_load = np.asarray(q_load, dtype=float)
    n = len(q_load)
    remaining = q_load.copy()
    out = {}
    order = sorted(chillers, key=lambda c: c.priority)
    cap_unit = {c.name: np.maximum(c.capacity(lwt, tcond[c.name]), 1e-6) for c in order}
    alloc = {c.name: np.zeros(n) for c in order}
    nrun = {c.name: np.zeros(n) for c in order}
    # pass 1: duty units up to stage-up PLR; pass 2: duty units up to PLR 1; pass 3: standby units
    for limit_attr in ("stage_up", "full", "standby"):
        for c in order:
            if limit_attr == "standby" and not c.standby_on_shortfall:
                continue
            units = c.n_duty + (c.n_standby if limit_attr == "standby" else 0)
            plr_max = c.stage_up if limit_attr == "stage_up" else 1.0
            cap = units * cap_unit[c.name] * plr_max
            extra = np.minimum(remaining, np.maximum(cap - alloc[c.name], 0.0))
            alloc[c.name] += extra
            remaining -= extra
    unmet = np.maximum(remaining, 0.0)
    total_p = np.zeros(n)
    for c in order:
        q = alloc[c.name]
        cu = cap_unit[c.name]
        stage_cap = cu * c.stage_up
        k = np.ceil(q / stage_cap - 1e-9)
        k = np.where(k > c.n_duty, np.ceil(q / cu - 1e-9), k)
        k = np.clip(k, 0, c.n_duty + c.n_standby)
        k = np.where(q > 1e-9, np.maximum(k, 1), 0)
        nrun[c.name] = k
        q_unit = np.where(k > 0, q / np.maximum(k, 1), 0.0)
        p_unit, plr = c.unit_power(q_unit, lwt, tcond[c.name])
        p = p_unit * k
        total_p += p
        out[c.name] = {"q": q, "n_run": k, "plr": np.where(k > 0, plr, 0.0), "power": p, "q_avail_unit": cu,
                       "standby_used": np.maximum(k - c.n_duty, 0), "below_min": (k > 0) & (plr < c.min_plr),
                       "out_of_range": (k > 0) & c.validity_flags(lwt, tcond[c.name])}
    return {"types": out, "power": total_p, "unmet": unmet, "q": q_load - unmet}
