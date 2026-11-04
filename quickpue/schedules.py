"""Hourly schedule profiles (fractions 0..1) for lighting, occupancy and equipment."""

from __future__ import annotations

from pathlib import Path

import numpy as np

# [NKB] data centre lighting and occupancy profile: 5 % 00:00-08:00 and 18:00-24:00, 15 % 08:00-18:00
_NKB_DC = [0.05] * 8 + [0.15] * 10 + [0.05] * 6
# Simple office profile (assumption, not the NCC Class 5 table): 100 % 08:00-18:00 weekdays, 10 % otherwise
_OFFICE_WD = [0.1] * 8 + [1.0] * 10 + [0.1] * 6
_OFFICE_WE = [0.1] * 24

LIBRARY = {
    "always": {"weekday": [1.0] * 24, "weekend": [1.0] * 24, "source": "Continuous"},
    "nkb_dc": {"weekday": _NKB_DC, "weekend": _NKB_DC, "source": "[NKB] data centre lighting / occupancy profile"},
    "office_simple": {"weekday": _OFFICE_WD, "weekend": _OFFICE_WE,
                      "source": "Assumption: simple office profile (replace with the NCC Class 5 profile if required)"},
}


def profile(spec, hour_of_day: np.ndarray, is_weekend: np.ndarray, base_dir: Path | None = None) -> np.ndarray:
    """Return an hourly fraction array for a profile spec.

    spec: library name; a 24-value list; {"weekday": [24], "weekend": [24]}; a constant number;
    or {"csv": path, "column": name} with 8,760 values.
    """
    n = len(hour_of_day)
    if spec is None:
        return np.ones(n)
    if isinstance(spec, (int, float)):
        return np.full(n, float(spec))
    if isinstance(spec, str):
        if spec not in LIBRARY:
            raise ValueError(f"unknown profile {spec!r}; library: {', '.join(LIBRARY)}")
        spec = LIBRARY[spec]
    if isinstance(spec, (list, tuple)):
        if len(spec) != 24:
            raise ValueError("a list profile needs 24 hourly values")
        return np.asarray(spec, dtype=float)[hour_of_day]
    if isinstance(spec, dict):
        if "csv" in spec:
            import pandas as pd

            path = Path(spec["csv"])
            if base_dir and not path.is_absolute():
                path = base_dir / path
            df = pd.read_csv(path)
            col = spec.get("column") or df.columns[-1]
            v = df[col].to_numpy(dtype=float)
            if len(v) != n:
                raise ValueError(f"profile {path}: expected {n} values, found {len(v)}")
            return v
        wd = np.asarray(spec["weekday"], dtype=float)
        we = np.asarray(spec.get("weekend", spec["weekday"]), dtype=float)
        return np.where(is_weekend, we[hour_of_day], wd[hour_of_day])
    raise ValueError(f"cannot interpret profile {spec!r}")


def describe(spec) -> str:
    if isinstance(spec, str) and spec in LIBRARY:
        return f"{spec} ({LIBRARY[spec]['source']})"
    return str(spec)
