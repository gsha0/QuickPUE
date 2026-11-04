"""Heat exchanger models: effectiveness-NTU relations, air-to-water coils (dry coolers and
integrated free cooling coils, S-EQ-11) and cooling towers (S-EQ-10).

All per-unit quantities: heat in kW, capacity rates C in kW/K, mass flows in kg/s.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import psychro

CP_AIR = 1.006  # kJ/kgK


def bisect(fun, lo, hi, iterations: int = 40):
    """Vectorised bisection for an increasing function: returns x with fun(x) ~ 0 within [lo, hi]."""
    lo = np.array(lo, dtype=float, copy=True)
    hi = np.array(hi, dtype=float, copy=True)
    for _ in range(iterations):
        mid = 0.5 * (lo + hi)
        pos = fun(mid) > 0
        hi = np.where(pos, mid, hi)
        lo = np.where(pos, lo, mid)
    return 0.5 * (lo + hi)


def eps_crossflow_unmixed(ntu, cr):
    """Cross flow, both fluids unmixed (standard approximation)."""
    ntu = np.maximum(np.asarray(ntu, dtype=float), 1e-12)
    cr = np.clip(np.asarray(cr, dtype=float), 1e-9, 1.0)
    return 1.0 - np.exp((1.0 / cr) * ntu**0.22 * (np.exp(-cr * ntu**0.78) - 1.0))


def eps_counterflow(ntu, cr):
    ntu = np.maximum(np.asarray(ntu, dtype=float), 1e-12)
    cr = np.clip(np.asarray(cr, dtype=float), 0.0, 1.0)
    near1 = np.abs(1.0 - cr) < 1e-6
    e = np.exp(-ntu * (1.0 - cr))
    with np.errstate(divide="ignore", invalid="ignore"):
        eps = np.where(near1, ntu / (1.0 + ntu), (1.0 - e) / (1.0 - cr * e))
    return eps


def ntu_for_eps(eps_target, cr, relation, ntu_max=50.0):
    eps_target = np.asarray(eps_target, dtype=float)
    return bisect(lambda ntu: relation(ntu, cr) - eps_target, np.full(eps_target.shape, 1e-6),
                  np.full(eps_target.shape, ntu_max), iterations=60)


# ---------------------------------------------------------------------------
@dataclass
class AirWaterCoil:
    """Dry cooler or integrated free-cooling coil, one unit, rated by one point.

    UA(f) = UA_des * f**n_exp; C_air(f) = C_air_des * f (S-EQ-11).
    """

    name: str
    ua_des: float  # kW/K
    c_air_des: float  # kW/K
    c_w_des: float  # kW/K
    n_exp: float = 0.6
    rated_q: float = 0.0
    rated_dt: float = 0.0

    @classmethod
    def from_rating(cls, name, q_kw, t_w_in, t_w_out, t_air_in, c_air_ratio=None, airflow_m3s=None, n_exp=0.6,
                    rho_air=1.18):
        dt_w = t_w_in - t_w_out
        if dt_w <= 0 or t_w_in <= t_air_in or q_kw <= 0:
            raise ValueError(f"{name}: rating needs water in > water out > air in and positive capacity")
        c_w = q_kw / dt_w
        if airflow_m3s:
            c_a = airflow_m3s * rho_air * CP_AIR
        else:
            c_a = (c_air_ratio or 1.5) * c_w
        cmin, cmax = min(c_w, c_a), max(c_w, c_a)
        eps = q_kw / (cmin * (t_w_in - t_air_in))
        if eps >= 0.999:
            raise ValueError(f"{name}: rated point implies effectiveness {eps:.3f} >= 1; check rating or airflow")
        ntu = float(ntu_for_eps(np.array([eps]), np.array([cmin / cmax]), eps_crossflow_unmixed)[0])
        return cls(name=name, ua_des=ntu * cmin, c_air_des=c_a, c_w_des=c_w, n_exp=n_exp, rated_q=q_kw,
                   rated_dt=t_w_in - t_air_in)

    def q(self, f, c_w, t_w_in, t_air):
        """Heat rejected per unit (kW) at fan fraction f, water capacity rate c_w (kW/K)."""
        f = np.maximum(np.asarray(f, dtype=float), 1e-6)
        c_w = np.maximum(np.asarray(c_w, dtype=float), 1e-9)
        c_a = self.c_air_des * f
        ua = self.ua_des * f**self.n_exp
        cmin = np.minimum(c_a, c_w)
        cmax = np.maximum(c_a, c_w)
        eps = eps_crossflow_unmixed(ua / cmin, cmin / cmax)
        return np.maximum(eps * cmin * (np.asarray(t_w_in) - np.asarray(t_air)), 0.0)

    def solve_f(self, q_target, c_w, t_w_in, t_air, f_min=0.2):
        """Fan fraction to reject q_target (M5).  Returns (f, q_achieved, saturated)."""
        q_target = np.asarray(q_target, dtype=float)
        q_full = self.q(1.0, c_w, t_w_in, t_air)
        sat = q_full < q_target - 1e-9
        f = bisect(lambda x: self.q(x, c_w, t_w_in, t_air) - q_target, np.full(q_target.shape, f_min),
                   np.ones(q_target.shape))
        f = np.where(sat, 1.0, f)
        q_fmin = self.q(f_min, c_w, t_w_in, t_air)
        f = np.where(q_fmin >= q_target, f_min, f)
        q = np.minimum(q_target, q_full)
        return f, q, sat


# ---------------------------------------------------------------------------
@dataclass
class CoolingTowerUnit:
    """Variable speed cooling tower, one cell, effectiveness-NTU with effective saturated-air
    specific heat (EnergyPlus simple tower / Merkel formulation, S-EQ-10)."""

    name: str
    ua_des: float  # kW/K (enthalpy-based, per unit)
    m_a_des: float  # kg/s
    m_w_des: float  # kg/s
    cp_w: float = 4.186
    exp_air: float = 0.6
    exp_water: float = 0.4

    @classmethod
    def from_rating(cls, name, q_kw, t_wb, approach, range_k, airflow_m3s=None, p_kpa=101.325, cp_w=4.186,
                    exp_air=0.6, exp_water=0.4):
        m_w = q_kw / (cp_w * range_k)
        if airflow_m3s is None:
            airflow_m3s = 2.76316e-5 * q_kw * 1000.0  # [EP-IO] Merkel default per unit capacity
        m_a = airflow_m3s * 1.18
        t_in = t_wb + approach + range_k
        tmp = cls(name, 1.0, m_a, m_w, cp_w, exp_air, exp_water)
        lo, hi = np.array([1e-3]), np.array([1e5])
        ua = bisect(lambda u: tmp._q_ua(u, 1.0, m_w, np.array([t_in]), np.array([t_wb]), p_kpa) - q_kw, lo, hi,
                    iterations=80)
        tmp.ua_des = float(ua[0])
        if tmp.ua_des > 9e4:
            raise ValueError(f"{name}: tower rating infeasible (approach too small for airflow)")
        return tmp

    def _q_ua(self, ua_des, f, m_w, t_w_in, t_wb, p_kpa):
        f = np.maximum(np.asarray(f, dtype=float), 1e-6)
        m_w = np.maximum(np.asarray(m_w, dtype=float), 1e-9)
        t_w_in = np.asarray(t_w_in, dtype=float)
        t_wb = np.asarray(t_wb, dtype=float)
        dt = np.maximum(t_w_in - t_wb, 1e-6)
        cs = (psychro.h_sat(t_w_in, p_kpa) - psychro.h_sat(t_wb, p_kpa)) / dt
        c_a = self.m_a_des * f * cs
        c_w = m_w * self.cp_w
        ua = ua_des * f**self.exp_air * (m_w / self.m_w_des) ** self.exp_water
        cmin = np.minimum(c_a, c_w)
        cmax = np.maximum(c_a, c_w)
        eps = eps_counterflow(ua / cmin, cmin / cmax)
        return np.where(t_w_in > t_wb, eps * cmin * (t_w_in - t_wb), 0.0)

    def q(self, f, m_w, t_w_in, t_wb, p_kpa=101.325):
        return self._q_ua(self.ua_des, f, m_w, t_w_in, t_wb, p_kpa)

    def leaving_temp(self, q_kw, m_w, t_wb, f, p_kpa=101.325):
        """Leaving water temperature when rejecting q_kw at fan fraction f."""
        q_kw = np.asarray(q_kw, dtype=float)
        t_wb = np.asarray(t_wb, dtype=float)
        dt_w = q_kw / (np.maximum(m_w, 1e-9) * self.cp_w)

        def resid(t_out):
            return self.q(f, m_w, t_out + dt_w, t_wb, p_kpa) - q_kw

        t_out = bisect(resid, t_wb - 0.0, t_wb + 60.0, iterations=40)
        return t_out

    def solve_f(self, q_kw, m_w, t_wb, t_out_target, f_min=0.2, p_kpa=101.325):
        q_kw = np.asarray(q_kw, dtype=float)
        t_in = np.asarray(t_out_target, dtype=float) + q_kw / (np.maximum(m_w, 1e-9) * self.cp_w)
        q_full = self.q(1.0, m_w, t_in, t_wb, p_kpa)
        sat = q_full < q_kw - 1e-9
        f = bisect(lambda x: self.q(x, m_w, t_in, t_wb, p_kpa) - q_kw, np.full(q_kw.shape, f_min),
                   np.ones(q_kw.shape))
        f = np.where(sat, 1.0, f)
        f = np.where(self.q(f_min, m_w, t_in, t_wb, p_kpa) >= q_kw, f_min, f)
        return f, sat


def tower_evaporation_kg_s(q_kw, t_db, w_in, t_wb, p_kpa, exit_offset_k=3.0):
    """Evaporation (kg/s) with exit air saturated at T_wb + 3 K (DCOPTEST method, S-EQ-13)."""
    h_in = psychro.enthalpy(t_db, w_in)
    t_out = np.asarray(t_wb) + exit_offset_k
    h_out = psychro.h_sat(t_out, p_kpa)
    w_out = psychro.humidity_ratio_sat(t_out, p_kpa)
    m_a = np.asarray(q_kw) / np.maximum(h_out - h_in, 1.0)
    return np.maximum(m_a * (w_out - w_in), 0.0)


def adiabatic_temperature(t_db, t_wb, efficiency, recirc_k=0.0, order="after_pads"):
    """Effective entering air temperature after adiabatic pads (S-EQ-12).

    order = "after_pads": T = T_db - eps*(T_db - T_wb) + dT_recirc (TEST_CASES R-1, default)
    order = "before_pads": T = (T_db + dT) - eps*((T_db + dT) - T_wb) (requirements REQ-C-IFC-3)
    """
    t_db = np.asarray(t_db, dtype=float)
    t_wb = np.asarray(t_wb, dtype=float)
    if order == "before_pads":
        t = t_db + recirc_k
        return t - efficiency * (t - t_wb)
    return t_db - efficiency * (t_db - t_wb) + recirc_k


def evaporative_water_kg_s(m_air_kg_s, dt_sensible, t_db):
    """Net water evaporated (kg/s) for a sensible temperature drop of the air stream."""
    return np.maximum(np.asarray(m_air_kg_s) * CP_AIR * np.asarray(dt_sensible) / psychro.h_fg(t_db), 0.0)
