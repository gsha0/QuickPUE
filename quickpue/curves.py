"""Performance curve library (requirements 11.3) and generic curve objects.

Fraction-of-full-load-power curves FFLP(f) for fans and pumps, chiller
biquadratic / quadratic curves, and the optional motor + VFD part-load
efficiency correction ``k_drive`` (11.3.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# FFLP library (11.3.1).  Coefficients C1..C5 of C1 + C2 f + C3 f^2 + C4 f^3 + C5 f^4
# ---------------------------------------------------------------------------
FFLP_LIBRARY: dict[str, dict[str, Any]] = {
    "K-CONST": {"c": [1, 0, 0, 0, 0], "source": "[EP-ER] Constant Speed Pump (FracFullLoadPower = 1.0)", "shaft": False,
                "label": "Constant speed"},
    "K-LIN": {"c": [0, 1, 0, 0, 0], "source": "[EP-IO] Pump:VariableSpeed defaults (S-EQ-04)", "shaft": True,
              "label": "Linear (EnergyPlus pump default)"},
    "K-SQUARE": {"c": [0, 0, 1, 0, 0], "source": "Square law P ~ f^2 (used by reference test cases, TEST_CASES O-05)",
                 "shaft": True, "label": "Square law"},
    "K-CUBE": {"c": [0, 0, 0, 1, 0], "source": "Affinity laws; [EP-ER] multi-speed fan exponent 3", "shaft": True,
               "label": "Ideal affinity (cube law)"},
    "K-VSM": {"c": [0.0015302446, 0.0052080574, 1.1086242, -0.11635563, 0],
              "source": "[EP-IO] Table 'Fan Coefficient Values', Var. Speed Motor (S-EQ-06)", "shaft": False,
              "label": "EnergyPlus Var. Speed Motor fan"},
    "K-IVD": {"c": [0.35071223, 0.30850535, -0.54137364, 0.87198823, 0],
              "source": "[EP-IO] Table 'Fan Coefficient Values', Inlet Vane Dampers (S-EQ-06)", "shaft": False,
              "label": "EnergyPlus Inlet Vane Dampers fan"},
    "K-DD": {"c": [0.37073425, 0.97250253, -0.34240761, 0, 0],
             "source": "[EP-IO] Table 'Fan Coefficient Values', Discharge Dampers (S-EQ-06)", "shaft": False,
             "label": "EnergyPlus Discharge Dampers fan"},
    "K-EPVAV": {"c": [0.0407598940, 0.08804497, -0.072926120, 0.9437398230, 0],
                "source": "[EP-IO] Fan:SystemModel example 'VAV Fan Curve' (S-EQ-06)", "shaft": False,
                "label": "EnergyPlus Fan:SystemModel VAV example"},
    "K-90.1G": {"c": [0.0013, 0.1470, 0.9506, -0.0998, 0],
                "source": "ASHRAE 90.1 Appendix G VAV fan curve (S-EQ-15; verify edition before release)", "shaft": False,
                "label": "ASHRAE 90.1 Appendix G VAV"},
}


@dataclass
class FFLPCurve:
    """Fraction of full-load power vs flow fraction, normalised to 1.0 at f = 1."""

    curve_id: str
    coeffs: list[float] | None = None  # polynomial C1..C5
    table_x: list[float] | None = None
    table_y: list[float] | None = None
    source: str = ""
    shaft: bool = False  # shaft-power shape (k_drive allowed)
    norm: float = 1.0  # normalisation factor applied (reported)
    label: str = ""

    def __post_init__(self):
        raw1 = float(self._raw(np.array([1.0]))[0])
        if raw1 <= 0:
            raise ValueError(f"curve {self.curve_id}: value at f = 1 must be positive")
        self.norm = 1.0 / raw1

    def _raw(self, f):
        f = np.asarray(f, dtype=float)
        if self.coeffs is not None:
            c = list(self.coeffs) + [0.0] * (5 - len(self.coeffs))
            return c[0] + c[1] * f + c[2] * f**2 + c[3] * f**3 + c[4] * f**4
        return np.interp(f, self.table_x, self.table_y)

    def __call__(self, f):
        return self._raw(f) * self.norm

    def describe(self) -> str:
        if self.coeffs is not None:
            c = ", ".join(f"{x:.6g}" for x in self.coeffs)
            body = f"polynomial C1..C5 = [{c}]"
        else:
            body = "table " + ", ".join(f"({x:g}, {y:g})" for x, y in zip(self.table_x, self.table_y))
        n = f"; normalised x{self.norm:.5f}" if abs(self.norm - 1.0) > 1e-9 else ""
        return f"{self.curve_id}: {body}{n} [{self.source}]"


_DP_RE = re.compile(r"^K-DP\(\s*([0-9.]+)\s*\)$", re.I)


def make_fflp(spec: Any) -> FFLPCurve:
    """Build an FFLP curve from a spec.

    Accepted forms: ``"K-VSM"``, ``"K-DP(0.3)"``, ``{"id": "K-DP", "s": 0.3}``,
    ``{"coefficients": [...]}`` (K-USER polynomial), ``{"table": {"x": [...], "y": [...]}}``
    or ``{"table": [[x, y], ...]}`` (K-USER table), ``[c1, c2, c3, c4, c5]``.
    """
    if isinstance(spec, FFLPCurve):
        return spec
    if isinstance(spec, str):
        s = spec.strip()
        m = _DP_RE.match(s)
        if m:
            return _dp(float(m.group(1)))
        key = s.upper()
        if key not in FFLP_LIBRARY:
            raise ValueError(f"unknown part-load curve {spec!r}; library: {', '.join(FFLP_LIBRARY)} or K-DP(s)")
        e = FFLP_LIBRARY[key]
        return FFLPCurve(key, coeffs=list(e["c"]), source=e["source"], shaft=e["shaft"], label=e["label"])
    if isinstance(spec, (list, tuple)):
        return FFLPCurve("K-USER", coeffs=[float(x) for x in spec], source="user polynomial", shaft=False,
                         label="User polynomial")
    if isinstance(spec, dict):
        src = spec.get("source", "user data")
        if spec.get("id", "").upper() == "K-DP":
            return _dp(float(spec["s"]))
        if "id" in spec and spec["id"].upper() in FFLP_LIBRARY:
            return make_fflp(spec["id"])
        if "coefficients" in spec:
            return FFLPCurve(spec.get("name", "K-USER"), coeffs=[float(x) for x in spec["coefficients"]],
                             source=str(src), shaft=bool(spec.get("shaft", False)), label=spec.get("label", "User"))
        if "table" in spec:
            t = spec["table"]
            if isinstance(t, dict):
                x, y = list(map(float, t["x"])), list(map(float, t["y"]))
            else:
                x, y = [float(r[0]) for r in t], [float(r[1]) for r in t]
            order = np.argsort(x)
            return FFLPCurve(spec.get("name", "K-USER"), table_x=list(np.array(x)[order]),
                             table_y=list(np.array(y)[order]), source=str(src), shaft=bool(spec.get("shaft", False)),
                             label=spec.get("label", "User table"))
    raise ValueError(f"cannot interpret part-load curve spec {spec!r}")


def _dp(s: float) -> FFLPCurve:
    if not 0.0 <= s <= 1.0:
        raise ValueError("K-DP(s): s must be within 0..1")
    return FFLPCurve(f"K-DP({s:g})", coeffs=[0.0, s, 0.0, 1.0 - s, 0.0],
                     source="Derived: differential pressure control s*f + (1 - s)*f^3 (S-EQ-07)", shaft=True,
                     label=f"Differential pressure control, s = {s:g}")


# ---------------------------------------------------------------------------
# Motor + VFD part-load efficiency (11.3.2, S-EQ-08)
# ---------------------------------------------------------------------------
VFD_COEFFS = {"10hp": (0.978715, 0.022227, 0.001941), "50hp": (0.987910, 0.018376, -0.001692),
              "200hp": (0.984476, 0.009828, -0.004560)}
MOTOR_COEFFS = {"10hp": (1.146258, 0.045766, -0.110367, 0.8745), "25hp": (1.137209, 0.050236, -0.08915, 0.8991),
                "100hp": (1.035294, 0.012948, -0.024708, 0.9499)}


@dataclass
class DriveCorrection:
    vfd: tuple[float, float, float] = VFD_COEFFS["50hp"]
    motor: tuple[float, float, float] = MOTOR_COEFFS["25hp"][:3]

    @staticmethod
    def _hyp(x, abc):
        a, b, c = abc
        x = np.maximum(np.asarray(x, dtype=float), 1e-6)
        return a * x / (b + x) + c * x

    def __call__(self, shaft_fraction):
        """k_drive = eta(1) / eta(x) with x = fractional shaft (output) power."""
        x = np.clip(np.asarray(shaft_fraction, dtype=float), 1e-4, 1.0)
        eta = self._hyp(x, self.motor) * self._hyp(x, self.vfd)
        eta1 = self._hyp(1.0, self.motor) * self._hyp(1.0, self.vfd)
        return eta1 / eta


def make_drive(spec) -> DriveCorrection | None:
    if not spec:
        return None
    if spec is True:
        return DriveCorrection()
    vfd = spec.get("vfd", "50hp")
    motor = spec.get("motor", "25hp")
    vfd = VFD_COEFFS[vfd] if isinstance(vfd, str) else tuple(vfd)
    motor = MOTOR_COEFFS[motor][:3] if isinstance(motor, str) else tuple(motor)[:3]
    return DriveCorrection(vfd=vfd, motor=motor)


# ---------------------------------------------------------------------------
# Chiller curves (S-EQ-03)
# ---------------------------------------------------------------------------
@dataclass
class Biquadratic:
    """z = c1 + c2 x + c3 x^2 + c4 y + c5 y^2 + c6 x y with optional input limits (EnergyPlus behaviour)."""

    c: list[float]
    x_min: float = -1e9
    x_max: float = 1e9
    y_min: float = -1e9
    y_max: float = 1e9
    x_shift: float = 0.0  # evaluated at x - x_shift (S-EQ-23 normalisation)
    y_shift: float = 0.0
    scale: float = 1.0
    clamp: bool = True
    name: str = ""

    def raw(self, x, y):
        c = self.c
        return c[0] + c[1] * x + c[2] * x * x + c[3] * y + c[4] * y * y + c[5] * x * y

    def inputs(self, x, y):
        xs = np.asarray(x, dtype=float) - self.x_shift
        ys = np.asarray(y, dtype=float) - self.y_shift
        if self.clamp:
            xs = np.clip(xs, self.x_min, self.x_max)
            ys = np.clip(ys, self.y_min, self.y_max)
        return xs, ys

    def __call__(self, x, y):
        xs, ys = self.inputs(x, y)
        return self.raw(xs, ys) * self.scale

    def out_of_range(self, x, y):
        xs = np.asarray(x, dtype=float) - self.x_shift
        ys = np.asarray(y, dtype=float) - self.y_shift
        return (xs < self.x_min - 1e-9) | (xs > self.x_max + 1e-9) | (ys < self.y_min - 1e-9) | (ys > self.y_max + 1e-9)

    def describe(self) -> str:
        c = ", ".join(f"{v:.6g}" for v in self.c)
        extra = []
        if self.x_shift or self.y_shift:
            extra.append(f"inputs shifted by ({self.x_shift:+.2f}, {self.y_shift:+.2f}) K")
        if abs(self.scale - 1.0) > 1e-12:
            extra.append(f"scaled x{self.scale:.5f}")
        if self.x_min > -1e8:
            extra.append(f"x in [{self.x_min:g}, {self.x_max:g}], y in [{self.y_min:g}, {self.y_max:g}]"
                         + (" (clamped)" if self.clamp else ""))
        return f"{self.name} biquadratic [{c}]" + ("; " + "; ".join(extra) if extra else "")


@dataclass
class PolyPLR:
    """EIRFPLR(PLR) = c1 + c2 PLR + c3 PLR^2 (+ c4 PLR^3)."""

    c: list[float]
    x_min: float = 0.0
    x_max: float = 1.0
    name: str = "EIRFPLR"
    clamp: bool = True

    def __call__(self, plr):
        x = np.asarray(plr, dtype=float)
        if self.clamp:
            x = np.clip(x, self.x_min, max(self.x_max, 1.0))
        c = list(self.c) + [0.0] * (4 - len(self.c))
        return c[0] + c[1] * x + c[2] * x * x + c[3] * x**3

    def describe(self) -> str:
        return f"{self.name} polynomial [{', '.join(f'{v:.6g}' for v in self.c)}], PLR in [{self.x_min:g}, {self.x_max:g}]"


@dataclass
class Table1D:
    x: list[float]
    y: list[float]
    name: str = ""
    extrapolated: dict = field(default_factory=dict)

    def __call__(self, v):
        return np.interp(np.asarray(v, dtype=float), self.x, self.y)

    def below(self, v):
        return np.asarray(v) < self.x[0] - 1e-12

    def above(self, v):
        return np.asarray(v) > self.x[-1] + 1e-12
