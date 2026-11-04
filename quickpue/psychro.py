"""Psychrometrics (S-EQ-13), SI units, vectorised with numpy.

Temperatures in degC, pressures in kPa, humidity ratio in kg/kg dry air,
enthalpy in kJ/kg dry air.  Saturation pressure uses the Hyland-Wexler
correlations from ASHRAE Handbook Fundamentals (2017) Chapter 1, Eq. 5 and 6.
"""

from __future__ import annotations

import numpy as np

R_DA = 0.287042  # kJ/(kg K) dry air gas constant
CP_DA = 1.006  # kJ/(kg K)
CP_V = 1.86  # kJ/(kg K)
H_FG0 = 2501.0  # kJ/kg at 0 degC
CP_W = 4.186  # kJ/(kg K) liquid water

# ASHRAE 2017 Fundamentals Ch.1 Eq. 5 (ice, -100..0 C) and Eq. 6 (water, 0..200 C)
_C1, _C2, _C3, _C4, _C5, _C6, _C7 = (
    -5.6745359e3, 6.3925247, -9.6778430e-3, 6.2215701e-7, 2.0747825e-9, -9.4840240e-13, 4.1635019,
)
_C8, _C9, _C10, _C11, _C12, _C13 = (
    -5.8002206e3, 1.3914993, -4.8640239e-2, 4.1764768e-5, -1.4452093e-8, 6.5459673,
)


def p_ws(t_c):
    """Saturation vapour pressure (kPa) over ice (t < 0) or liquid water (t >= 0)."""
    t = np.asarray(t_c, dtype=float)
    T = t + 273.15
    ice = _C1 / T + _C2 + _C3 * T + _C4 * T**2 + _C5 * T**3 + _C6 * T**4 + _C7 * np.log(T)
    liq = _C8 / T + _C9 + _C10 * T + _C11 * T**2 + _C12 * T**3 + _C13 * np.log(T)
    lnp = np.where(t < 0.0, ice, liq)
    return np.exp(lnp) / 1000.0


def p_ws_tetens(t_c):
    """Tetens saturation pressure (kPa), kept for DCOPTEST compatibility checks."""
    t = np.asarray(t_c, dtype=float)
    return 0.61078 * np.exp(17.27 * t / (t + 237.3))


def pressure_at_altitude(z_m):
    """Standard atmosphere pressure (kPa) at altitude z (m), ASHRAE Ch.1 Eq. 3."""
    return 101.325 * (1.0 - 2.25577e-5 * np.asarray(z_m, dtype=float)) ** 5.2559


def humidity_ratio_from_pw(p_w, p):
    p_w = np.asarray(p_w, dtype=float)
    return 0.621945 * p_w / (np.asarray(p, dtype=float) - p_w)


def humidity_ratio_from_dewpoint(t_dp, p):
    return humidity_ratio_from_pw(p_ws(t_dp), p)


def humidity_ratio_sat(t, p):
    return humidity_ratio_from_pw(p_ws(t), p)


def humidity_ratio_from_rh(t, rh_pct, p):
    return humidity_ratio_from_pw(np.asarray(rh_pct) / 100.0 * p_ws(t), p)


def enthalpy(t, w):
    """Moist air enthalpy (kJ/kg dry air)."""
    t = np.asarray(t, dtype=float)
    return CP_DA * t + np.asarray(w) * (H_FG0 + CP_V * t)


def h_sat(t, p):
    return enthalpy(t, humidity_ratio_sat(t, p))


def density(t, w, p):
    """Moist air density (kg moist air / m3)."""
    t = np.asarray(t, dtype=float)
    w = np.asarray(w, dtype=float)
    v = R_DA * (t + 273.15) * (1.0 + 1.607858 * w) / np.asarray(p, dtype=float)  # m3/kg dry air
    return (1.0 + w) / v


def dewpoint_from_w(w, p):
    """Dew point (degC) from humidity ratio by bisection on p_ws."""
    p_w = np.asarray(w, dtype=float) * np.asarray(p, dtype=float) / (0.621945 + np.asarray(w, dtype=float))
    lo = np.full(np.shape(p_w), -60.0)
    hi = np.full(np.shape(p_w), 100.0)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        high = p_ws(mid) > p_w
        hi = np.where(high, mid, hi)
        lo = np.where(high, lo, mid)
    return 0.5 * (lo + hi)


def wet_bulb(t, w, p, iterations: int = 50):
    """Thermodynamic wet bulb (degC), ASHRAE Ch.1 Eq. 33/35, solved by bisection."""
    t = np.asarray(t, dtype=float)
    w = np.asarray(w, dtype=float)
    p = np.broadcast_to(np.asarray(p, dtype=float), t.shape)
    lo = np.full(t.shape, -60.0)
    hi = t.copy()
    for _ in range(iterations):
        tw = 0.5 * (lo + hi)
        ws = humidity_ratio_sat(tw, p)
        # Eq. 33 (above freezing) and Eq. 35 (below freezing)
        w_above = ((2501.0 - 2.326 * tw) * ws - 1.006 * (t - tw)) / (2501.0 + 1.86 * t - 4.186 * tw)
        w_below = ((2830.0 - 0.24 * tw) * ws - 1.006 * (t - tw)) / (2830.0 + 1.86 * t - 2.1 * tw)
        w_calc = np.where(tw >= 0.0, w_above, w_below)
        too_high = w_calc > w  # wet bulb guess too high
        hi = np.where(too_high, tw, hi)
        lo = np.where(too_high, lo, tw)
    return 0.5 * (lo + hi)


def stull_wet_bulb(t, rh_pct):
    """Stull (2011) empirical wet bulb, fallback used by DCOPTEST."""
    t = np.asarray(t, dtype=float)
    rh = np.asarray(rh_pct, dtype=float)
    return (
        t * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
        + np.arctan(t + rh)
        - np.arctan(rh - 1.676331)
        + 0.00391838 * rh**1.5 * np.arctan(0.023101 * rh)
        - 4.686035
    )


def h_fg(t):
    """Latent heat of vaporisation (kJ/kg) near t (degC)."""
    return 2501.0 - 2.361 * np.asarray(t, dtype=float)
