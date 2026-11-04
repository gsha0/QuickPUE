"""EPW weather reader, design conditions and monthly summary (IN-W-1 to IN-W-3, OUT-5)."""

from __future__ import annotations

import calendar
import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import psychro

HOURS = 8760
MONTH_NAMES = [calendar.month_abbr[i] for i in range(1, 13)]
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass
class Weather:
    """Hourly weather for one typical year (8,760 rows, leap day removed)."""

    path: str
    city: str
    state: str
    country: str
    source: str
    wmo: str
    latitude: float
    longitude: float
    timezone: float
    elevation_m: float
    month: np.ndarray
    day: np.ndarray
    hour: np.ndarray  # 1..24 as in the EPW
    year: np.ndarray
    t_db: np.ndarray
    t_dp: np.ndarray
    rh: np.ndarray
    p_kpa: np.ndarray
    ghi: np.ndarray
    wind: np.ndarray
    w: np.ndarray = field(init=False)
    t_wb: np.ndarray = field(init=False)
    h: np.ndarray = field(init=False)
    design: dict = field(default_factory=dict)
    comments: list = field(default_factory=list)
    start_weekday: int = 6  # 0 = Monday; EPW DATA PERIODS start day
    warnings: list = field(default_factory=list)

    def __post_init__(self):
        self.w = psychro.humidity_ratio_from_dewpoint(np.minimum(self.t_dp, self.t_db), self.p_kpa)
        self.t_wb = psychro.wet_bulb(self.t_db, self.w, self.p_kpa)
        self.h = psychro.enthalpy(self.t_db, self.w)

    # ------------------------------------------------------------------
    @property
    def n(self) -> int:
        return len(self.t_db)

    @property
    def hour_of_day(self) -> np.ndarray:
        """0..23 (EPW hour 1 is the hour ending 01:00, so it is hour-of-day 0)."""
        return (self.hour - 1) % 24

    @property
    def day_of_year(self) -> np.ndarray:
        return np.arange(self.n) // 24

    @property
    def weekday(self) -> np.ndarray:
        """0 = Monday .. 6 = Sunday, from the EPW DATA PERIODS start day."""
        return (self.start_weekday + self.day_of_year) % 7

    @property
    def is_weekend(self) -> np.ndarray:
        return self.weekday >= 5

    def station_label(self) -> str:
        return f"{self.city}, {self.state}, {self.country} (WMO {self.wmo})"

    def subset(self, idx) -> "Weather":
        """Weather restricted to the given hour indices (used for design passes)."""
        sub = object.__new__(Weather)
        for k, v in self.__dict__.items():
            if isinstance(v, np.ndarray) and v.shape == self.t_db.shape:
                setattr(sub, k, v[idx])
            else:
                setattr(sub, k, v)
        return sub

    @classmethod
    def synthetic(cls, t_db, t_wb=None, rh=None, p_kpa=101.325, start_weekday=0) -> "Weather":
        """Build a weather object from arrays (design points, unit tests)."""
        t_db = np.atleast_1d(np.asarray(t_db, dtype=float))
        n = len(t_db)
        p = np.full(n, float(p_kpa))
        if t_wb is not None:
            t_wb = np.broadcast_to(np.asarray(t_wb, dtype=float), (n,)).copy()
            # humidity ratio from wet bulb (ASHRAE Eq. 33)
            ws = psychro.humidity_ratio_sat(t_wb, p)
            w = ((2501.0 - 2.326 * t_wb) * ws - 1.006 * (t_db - t_wb)) / (2501.0 + 1.86 * t_db - 4.186 * t_wb)
            w = np.maximum(w, 1e-5)
            t_dp = psychro.dewpoint_from_w(w, p)
        else:
            rh = np.broadcast_to(np.asarray(50.0 if rh is None else rh, dtype=float), (n,)).copy()
            w = psychro.humidity_ratio_from_rh(t_db, rh, p)
            t_dp = psychro.dewpoint_from_w(w, p)
        rh_calc = 100.0 * psychro.p_ws(t_dp) / psychro.p_ws(t_db)
        hours = np.arange(n)
        obj = cls(
            path="<synthetic>", city="synthetic", state="", country="", source="", wmo="", latitude=0.0,
            longitude=0.0, timezone=0.0, elevation_m=0.0, month=np.ones(n, dtype=int),
            day=(hours // 24 + 1).astype(int), hour=(hours % 24 + 1).astype(int), year=np.zeros(n, dtype=int),
            t_db=t_db, t_dp=t_dp, rh=rh_calc, p_kpa=p, ghi=np.zeros(n), wind=np.zeros(n),
            start_weekday=start_weekday,
        )
        if t_wb is not None:
            obj.t_wb = t_wb
        return obj


def _f(x, default=float("nan")):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def read_epw(path: str | Path) -> Weather:
    path = Path(path)
    with open(path, newline="", encoding="latin-1") as fh:
        rows = list(csv.reader(fh))
    header = {}
    comments = []
    data_start = None
    for i, r in enumerate(rows[:12]):
        key = r[0].strip().upper() if r else ""
        if key == "DATA PERIODS":
            header[key] = r
            data_start = i + 1
            break
        if key.startswith("COMMENTS"):
            comments.append(",".join(r[1:]).strip().strip('"'))
        header[key] = r
    if data_start is None:
        raise ValueError(f"{path}: no DATA PERIODS record; not an EPW file?")
    loc = header.get("LOCATION", [""] * 10)
    data = [r for r in rows[data_start:] if len(r) > 20]
    arr = np.array([[_f(r[0]), _f(r[1]), _f(r[2]), _f(r[3]), _f(r[6]), _f(r[7]), _f(r[8]), _f(r[9]),
                     _f(r[13]), _f(r[21])] for r in data])
    warnings = []
    if len(arr) == 8784:
        keep = ~((arr[:, 1] == 2) & (arr[:, 2] == 29))
        arr = arr[keep]
        warnings.append("EPW has 8,784 hours; 29 February removed to give 8,760 hours.")
    if len(arr) != HOURS:
        raise ValueError(f"{path}: expected 8,760 hourly records, found {len(arr)}")
    # missing value handling (EPW codes 99.9 / 999 / 999999)
    t_db = arr[:, 4]
    t_dp = arr[:, 5]
    rh = arr[:, 6]
    p = arr[:, 7] / 1000.0
    elev = _f(loc[9], 0.0)
    for name, a, bad in (("dry bulb", t_db, 99.9), ("dew point", t_dp, 99.9)):
        m = a >= bad
        if m.any():
            warnings.append(f"EPW {name}: {int(m.sum())} missing values linearly interpolated.")
            idx = np.arange(len(a))
            a[m] = np.interp(idx[m], idx[~m], a[~m])
    mp = (p <= 30.0) | (p >= 120.0)
    if mp.any():
        p[mp] = float(psychro.pressure_at_altitude(elev))
        warnings.append(f"EPW pressure: {int(mp.sum())} missing values set to standard pressure at altitude.")
    start_weekday = 6
    dp = header.get("DATA PERIODS")
    if dp and len(dp) > 4 and dp[4].strip().lower() in _WEEKDAYS:
        start_weekday = _WEEKDAYS.index(dp[4].strip().lower())
    w = Weather(
        path=str(path), city=loc[1].strip(), state=loc[2].strip(), country=loc[3].strip(), source=loc[4].strip(),
        wmo=loc[5].strip(), latitude=_f(loc[6]), longitude=_f(loc[7]), timezone=_f(loc[8]), elevation_m=elev,
        month=arr[:, 1].astype(int), day=arr[:, 2].astype(int), hour=arr[:, 3].astype(int), year=arr[:, 0].astype(int),
        t_db=t_db, t_dp=t_dp, rh=rh, p_kpa=p, ghi=arr[:, 8], wind=arr[:, 9], comments=comments,
        start_weekday=start_weekday, warnings=warnings,
    )
    w.design = parse_design_conditions(header.get("DESIGN CONDITIONS"))
    return w


def parse_design_conditions(rec) -> dict:
    """Parse cooling 0.4 % DB / MCWB and heating 99.6 % from the EPW DESIGN CONDITIONS record."""
    out: dict = {}
    if not rec:
        return out
    try:
        i = [x.strip() for x in rec].index("Cooling")
        out["cooling_db_0p4"] = _f(rec[i + 3])
        out["cooling_mcwb_0p4"] = _f(rec[i + 4])
        out["cooling_db_1"] = _f(rec[i + 5])
        out["cooling_mcwb_1"] = _f(rec[i + 6])
        out["cooling_wb_0p4"] = _f(rec[i + 9])
        out["cooling_mcdb_wb_0p4"] = _f(rec[i + 10])
    except (ValueError, IndexError):
        pass
    try:
        i = [x.strip() for x in rec].index("Heating")
        out["heating_db_99p6"] = _f(rec[i + 2])
    except (ValueError, IndexError):
        pass
    try:
        i = [x.strip() for x in rec].index("Extremes")
        # ASHRAE extremes: ... mean annual extreme max DB is the 5th field after wind values
        out["extreme_max_db_mean"] = _f(rec[i + 5])
    except (ValueError, IndexError):
        pass
    if "Climatic Design" in ",".join(rec):
        out["source"] = rec[2].strip() if len(rec) > 2 else ""
    return {k: v for k, v in out.items() if not (isinstance(v, float) and math.isnan(v))}


def monthly_summary(w: Weather) -> pd.DataFrame:
    """Monthly weather table (OUT-5; TEST_CASES W-01)."""
    df = pd.DataFrame({"month": w.month, "t_db": w.t_db, "t_dp": w.t_dp, "rh": w.rh, "t_wb": w.t_wb})
    g = df.groupby("month")
    out = pd.DataFrame({
        "DBT max (C)": g.t_db.max(), "DBT min (C)": g.t_db.min(), "DBT mean (C)": g.t_db.mean(),
        "DPT max (C)": g.t_dp.max(), "DPT min (C)": g.t_dp.min(), "WBT max (C)": g.t_wb.max(),
        "RH mean (%)": g.rh.mean(),
    })
    out.index = [MONTH_NAMES[m - 1] for m in out.index]
    annual = pd.DataFrame({
        "DBT max (C)": [df.t_db.max()], "DBT min (C)": [df.t_db.min()], "DBT mean (C)": [df.t_db.mean()],
        "DPT max (C)": [df.t_dp.max()], "DPT min (C)": [df.t_dp.min()], "WBT max (C)": [df.t_wb.max()],
        "RH mean (%)": [df.rh.mean()],
    }, index=["Annual"])
    return pd.concat([out, annual])


def design_point(w: Weather, spec="epw_0.4") -> tuple[float, float, str]:
    """Return (T_db, T_wb, label) for the design condition used for sizing (IN-W-3)."""
    if isinstance(spec, dict):
        return float(spec["db"]), float(spec["wb"]), "user design condition"
    if spec == "epw_0.4" and "cooling_db_0p4" in w.design and "cooling_mcwb_0p4" in w.design:
        return w.design["cooling_db_0p4"], w.design["cooling_mcwb_0p4"], "EPW cooling 0.4 % DB / MCWB"
    if spec in ("max", "epw_0.4"):
        i = int(np.argmax(w.t_db))
        return float(w.t_db[i]), float(w.t_wb[i]), "maximum dry bulb hour in weather file"
    raise ValueError(f"unknown design condition spec {spec!r}")


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
