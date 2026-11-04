"""IT load scenarios: flat fractions and 8,760 h profiles (IN-IT-3, IN-IT-5, UC-6, D16)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .schema import Hall, Scenario

HOURS = 8760


@dataclass
class ITInput:
    name: str
    it_kw: dict[str, np.ndarray]  # per hall type (all halls of the type), kW
    liquid_fraction: dict[str, np.ndarray]
    it_fraction: np.ndarray  # total IT / installed IT
    flat_fraction: float | None
    warnings: list[str] = field(default_factory=list)
    description: str = ""


def build_it_input(sc: Scenario, halls: list[Hall], base_dir: Path | None = None, n: int = HOURS) -> ITInput:
    installed = {h.name: h.count * h.it_kw for h in halls}
    total_inst = sum(installed.values())
    warnings: list[str] = []
    lf = {h.name: np.full(n, h.liquid_fraction) for h in halls}
    if sc.it_fraction is not None:
        it = {h.name: np.full(n, sc.it_fraction * installed[h.name]) for h in halls}
        frac = np.full(n, sc.it_fraction)
        return ITInput(sc.name, it, lf, frac, sc.it_fraction, warnings,
                       f"Flat {sc.it_fraction * 100:g} % of installed IT ({total_inst:,.0f} kW), 8,760 h")

    path = Path(sc.profile)
    if base_dir and not path.is_absolute():
        path = base_dir / path
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]

    def series(col):
        v = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
        if np.isnan(v).any():
            k = int(np.isnan(v).sum())
            warnings.append(f"IT profile {path.name}:{col}: {k} gaps filled by linear interpolation.")
            idx = np.arange(len(v))
            good = ~np.isnan(v)
            v = np.interp(idx, idx[good], v[good])
        if len(v) == 8784:
            v = np.concatenate([v[: 59 * 24], v[60 * 24:]])
            warnings.append(f"IT profile {path.name}: 8,784 values; 29 February removed.")
        if len(v) != n:
            if not sc.repeat:
                raise ValueError(f"IT profile {path}: {len(v)} values; 8,760 needed (set repeat: true to repeat a "
                                 f"shorter series)")
            reps = int(np.ceil(n / len(v)))
            v = np.tile(v, reps)[:n]
            warnings.append(f"IT profile {path.name}:{col}: {len(df)} values repeated to 8,760 h (repeat flag).")
        return v

    it: dict[str, np.ndarray] = {}
    if sc.per_hall:
        for h in halls:
            if h.name not in df.columns:
                raise ValueError(f"IT profile {path}: per-hall column {h.name!r} missing")
            v = series(h.name)
            it[h.name] = v * installed[h.name] if sc.units == "fraction" else v
    else:
        col = sc.column or [c for c in df.columns if c.lower() not in ("hour", "datetime", "time", "date")][0]
        v = series(col)
        tot = v * total_inst if sc.units == "fraction" else v
        for h in halls:
            it[h.name] = tot * (installed[h.name] / total_inst if total_inst else 0.0)
    if sc.liquid_fraction_column:
        lv = np.clip(series(sc.liquid_fraction_column), 0.0, 1.0)
        lf = {h.name: lv.copy() for h in halls}
    tot = sum(it.values())
    frac = tot / total_inst if total_inst else np.zeros(n)
    if (tot > total_inst * 1.0001).any():
        k = int((tot > total_inst * 1.0001).sum())
        warnings.append(f"IT profile {path.name}: {k} h above installed IT ({total_inst:,.0f} kW); values kept.")
    if (tot < 0).any():
        raise ValueError(f"IT profile {path}: negative values")
    return ITInput(sc.name, it, lf, frac, None, warnings,
                   f"Hourly profile {path.name} ({sc.units}), mean {frac.mean() * 100:.1f} % of installed IT")
