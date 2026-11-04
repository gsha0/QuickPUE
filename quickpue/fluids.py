"""Heat transfer fluid properties (S-DEF-04).

Rounded specific heat and density near 20 degC as a function of glycol
concentration (mass percent).  These are deliberately simple: loop energy
balances need cp * rho to about 1 percent; the values are recorded as
assumptions in the calculation report.
"""

from __future__ import annotations

import numpy as np

# (glycol percent, cp kJ/kgK, density kg/m3), ASHRAE Fundamentals Ch. 31, rounded near 20 C
_TABLES = {
    "water": [(0.0, 4.182, 998.2)],
    "pg": [(0.0, 4.182, 998.2), (10.0, 4.11, 1007.0), (20.0, 4.02, 1016.0), (25.0, 3.96, 1020.0),
           (30.0, 3.90, 1025.0), (40.0, 3.76, 1033.0), (50.0, 3.58, 1041.0)],
    "eg": [(0.0, 4.182, 998.2), (10.0, 4.05, 1013.0), (20.0, 3.90, 1027.0), (25.0, 3.82, 1033.0),
           (30.0, 3.73, 1040.0), (40.0, 3.55, 1053.0), (50.0, 3.35, 1066.0)],
}

# Approximate freezing points (degC) for glycol warnings
_FREEZE = {
    "water": [(0.0, 0.0)],
    "pg": [(0.0, 0.0), (10.0, -3.0), (20.0, -7.0), (25.0, -10.0), (30.0, -13.0), (40.0, -21.0), (50.0, -33.0)],
    "eg": [(0.0, 0.0), (10.0, -4.0), (20.0, -8.0), (25.0, -11.0), (30.0, -15.0), (40.0, -24.0), (50.0, -37.0)],
}


def _interp(table, pct, col):
    xs = [r[0] for r in table]
    ys = [r[col] for r in table]
    return float(np.interp(pct, xs, ys))


def cp(medium: str = "water", glycol_pct: float = 0.0) -> float:
    return _interp(_TABLES[_key(medium)], glycol_pct, 1)


def rho(medium: str = "water", glycol_pct: float = 0.0) -> float:
    return _interp(_TABLES[_key(medium)], glycol_pct, 2)


def rho_cp(medium: str = "water", glycol_pct: float = 0.0) -> float:
    """Volumetric heat capacity in kJ/(m3 K)."""
    return cp(medium, glycol_pct) * rho(medium, glycol_pct)


def freezing_point(medium: str = "water", glycol_pct: float = 0.0) -> float:
    return _interp(_FREEZE[_key(medium)], glycol_pct, 1)


def _key(medium: str) -> str:
    m = medium.lower()
    if m in ("water", "w"):
        return "water"
    if m in ("pg", "propylene_glycol", "propylene glycol"):
        return "pg"
    if m in ("eg", "ethylene_glycol", "ethylene glycol"):
        return "eg"
    raise ValueError(f"unknown medium {medium!r} (water, pg, eg)")
