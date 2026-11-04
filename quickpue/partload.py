"""Fan and pump part-load model (requirements Section 11).

P = N_run * P_des * FFLP(f_eff) * k_drive(f_eff), f_eff = max(f, f_min).
PLR methods M1 to M6 derive the flow fraction from the served load; running
rules R-ALL, R-STAGE and R-EPSEQ set the number of running units.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .curves import DriveCorrection, FFLPCurve, make_drive, make_fflp

METHODS = ("M1", "M2", "M3", "M4", "M5", "M6")
RULES = ("R-ALL", "R-STAGE", "R-EPSEQ")


@dataclass
class FanPumpGroup:
    """One unique fan or pump type: design absorbed power per unit x quantity (D3, REQ-DM-2)."""

    name: str
    end_use: str
    p_des_kw: float
    v_des_m3s: float | None  # design flow per unit
    n_duty: int
    n_standby: int = 0
    redundancy: str = "N+x"  # N+x | 2N_active | 0.5N+0.5N
    method: str = "M2"
    curve: FFLPCurve = field(default_factory=lambda: make_fflp("K-CONST"))
    f_min: float = 0.0
    rule: str = "R-ALL"
    stage_up: float = 1.0
    design_load_kw: float | None = None  # M1
    table: list | None = None  # M6: [[it_fraction, f], ...]
    drive: DriveCorrection | None = None
    heat_to_stream: float = 1.0
    on_ups: bool = False
    off_at_zero_load: bool = True
    auto_sized: dict = field(default_factory=dict)

    @property
    def n_energised(self) -> int:
        if self.redundancy in ("2N_active", "0.5N+0.5N"):
            return self.n_duty + self.n_standby
        return self.n_duty

    @property
    def quantity(self) -> int:
        return self.n_duty + self.n_standby

    def describe(self) -> str:
        parts = [f"{self.method}", self.curve.curve_id, f"f_min {self.f_min:g}", self.rule]
        if self.drive is not None:
            parts.append("k_drive")
        return ", ".join(parts)

    # ------------------------------------------------------------------
    def evaluate(self, *, q_served=None, v_req=None, f_direct=None, it_fraction=None, n_hours=None,
                 n_run_override=None) -> dict:
        """Return dict of arrays: f (demand), f_eff, n_run, power (kW), bypass (fraction), overload.

        Inputs by method: M1 q_served (kW); M2 / M4 v_req (m3/s); M3 none; M5 f_direct; M6 it_fraction.
        """
        n = n_hours or _len(q_served, v_req, f_direct, it_fraction)
        n_e = self.n_energised
        if n_e <= 0 or self.p_des_kw <= 0:
            z = np.zeros(n)
            return {"f": z, "f_eff": z, "n_run": z, "power": z, "bypass": z, "overload": z, "active": z > 0}
        m = self.method
        # total demand expressed in "unit design flows" (f_total = sum over units of f)
        if m == "M1":
            if q_served is None:
                raise ValueError(f"{self.name}: M1 needs the served load")
            qdes = self.design_load_kw
            if not qdes or qdes <= 0:
                raise ValueError(f"{self.name}: M1 needs design_load_kw > 0")
            f_total = np.asarray(q_served, dtype=float) / qdes * self.n_duty
            load_flag = np.asarray(q_served) > 0
        elif m in ("M2", "M4"):
            if v_req is None or not self.v_des_m3s:
                raise ValueError(f"{self.name}: {m} needs required flow and design flow per unit")
            f_total = np.asarray(v_req, dtype=float) / self.v_des_m3s
            load_flag = np.asarray(v_req) > 0
        elif m == "M3":
            f_total = np.full(n, float(n_e))
            load_flag = np.ones(n, dtype=bool) if q_served is None else np.asarray(q_served) > 0
        elif m == "M5":
            if f_direct is None:
                raise ValueError(f"{self.name}: M5 needs the solved flow fraction")
            f_unit = np.asarray(f_direct, dtype=float)
            nr = np.full(n, float(n_e)) if n_run_override is None else np.asarray(n_run_override, dtype=float)
            f_total = f_unit * nr
            load_flag = f_unit > 0
        elif m == "M6":
            if it_fraction is None or not self.table:
                raise ValueError(f"{self.name}: M6 needs an IT fraction table")
            xs = [float(r[0]) for r in self.table]
            ys = [float(r[1]) for r in self.table]
            f_unit = np.interp(np.asarray(it_fraction, dtype=float), xs, ys)
            f_total = f_unit * self.n_duty
            load_flag = np.asarray(it_fraction) > 0
        else:
            raise ValueError(f"unknown PLR method {m}")
        f_total = np.maximum(f_total, 0.0)

        # running units
        if n_run_override is not None:
            n_run = np.asarray(n_run_override, dtype=float).copy()
        elif m == "M3":
            n_run = np.full(n, float(n_e))
        elif self.rule == "R-ALL":
            n_run = np.full(n, float(n_e))
        elif self.rule == "R-STAGE":
            n_run = np.clip(np.ceil(f_total / max(self.stage_up, 1e-6) - 1e-9), 1, n_e).astype(float)
        elif self.rule == "R-EPSEQ":
            n_run = np.clip(np.ceil(f_total - 1e-9), 1, n_e).astype(float)
        else:
            raise ValueError(f"unknown running rule {self.rule}")
        if self.off_at_zero_load:
            n_run = np.where(load_flag, n_run, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            f = np.where(n_run > 0, f_total / np.maximum(n_run, 1e-12), 0.0)
        overload = np.maximum(f - 1.0, 0.0) * n_run  # unit-flows beyond capacity
        if self.rule == "R-EPSEQ" and n_run_override is None and m not in ("M3",):
            # sequential: N_full units at f = 1 and one at part load (S-EQ-09)
            n_full = np.minimum(np.floor(f_total + 1e-12), n_run)
            rem = np.clip(f_total - n_full, 0.0, 1.0)
            part = np.where((rem > 1e-9) & (n_full < n_run), 1.0, 0.0)
            n_full = np.where(part > 0, n_run - 1, n_run)
            rem_eff = np.maximum(rem, self.f_min)
            p_unit_full = self._p(np.ones(n))
            power = self.p_des_kw * (n_full * p_unit_full + part * self._p(rem_eff))
            power = np.where(n_run > 0, power, 0.0)
            f_eff = np.where(n_run > 0, np.minimum(np.maximum(f, self.f_min), 1.0), 0.0)
            bypass = np.where(n_run > 0, np.maximum(self.f_min - rem, 0.0) * part / np.maximum(n_run, 1), 0.0)
            return {"f": f, "f_eff": f_eff, "n_run": n_run, "power": power, "bypass": bypass, "overload": overload,
                    "active": n_run > 0}
        f_eff = np.where(n_run > 0, np.clip(np.maximum(f, self.f_min), 0.0, 1.0), 0.0)
        bypass = np.where(n_run > 0, np.maximum(self.f_min - f, 0.0), 0.0)
        power = n_run * self.p_des_kw * self._p(f_eff)
        return {"f": f, "f_eff": f_eff, "n_run": n_run, "power": power, "bypass": bypass, "overload": overload,
                "active": n_run > 0}

    def _p(self, f_eff):
        p = self.curve(f_eff)
        if self.drive is not None:
            p = p * self.drive(np.maximum(p, 1e-6))
        return np.where(np.asarray(f_eff) > 0, p, 0.0)


def _len(*arrs) -> int:
    for a in arrs:
        if a is not None and np.ndim(a) > 0:
            return len(a)
    return 1


def build_group(name: str, end_use: str, spec, *, default_method="M2", default_curve="K-CONST", default_f_min=0.0,
                default_rule="R-ALL", n_duty=None, n_standby=None, redundancy=None) -> FanPumpGroup:
    """Build a FanPumpGroup from a validated schema object (``schema.FanPump``)."""
    pl = spec.part_load
    curve = make_fflp(pl.curve if pl.curve is not None else default_curve)
    drive = make_drive(pl.drive)
    if drive is not None and not curve.shaft:
        raise ValueError(f"{name}: k_drive may only be used with shaft-power curves (K-CUBE, K-DP(s), K-LIN, "
                         f"K-SQUARE); {curve.curve_id} already includes drive losses (11.2)")
    flow = spec.flow_l_s / 1000.0 if spec.flow_l_s else None
    return FanPumpGroup(
        name=name, end_use=end_use, p_des_kw=float(spec.power_kw or 0.0), v_des_m3s=flow,
        n_duty=int(n_duty if n_duty is not None else spec.duty),
        n_standby=int(n_standby if n_standby is not None else spec.standby),
        redundancy=redundancy or spec.redundancy,
        method=pl.method or default_method, curve=curve,
        f_min=float(pl.f_min if pl.f_min is not None else default_f_min),
        rule=pl.running or default_rule, stage_up=float(pl.stage_up), design_load_kw=pl.design_load_kw,
        table=pl.table, drive=drive, heat_to_stream=float(pl.heat_to_stream), on_ups=bool(spec.on_ups),
    )
