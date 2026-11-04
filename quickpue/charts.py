"""Charts (REQ-OUT-14).  Requires matplotlib (optional dependency)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from .engine import end_use_label  # noqa: E402
from .weather import MONTH_NAMES  # noqa: E402


def make_charts(res, out_dir) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    base = res.scenarios[0]

    def save(fig, name):
        p = out / name
        fig.tight_layout()
        fig.savefig(p, dpi=120)
        plt.close(fig)
        files.append(str(p))

    # end-use pie (coarse groups)
    eu = base.end_uses[base.end_uses.boundary == "infrastructure"]
    g = eu.groupby("group").kwh.sum()
    g = g[g > 0]
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(g.values, labels=g.index, autopct="%1.1f%%", startangle=90)
    ax.set_title(f"Infrastructure electricity by end use group, {base.name}")
    save(fig, "end_use_pie.png")
    # PUE vs IT load
    flat = [s for s in res.scenarios if s.it.flat_fraction is not None]
    if flat:
        fig, ax = plt.subplots(figsize=(6, 4))
        x = [100 * s.it.flat_fraction for s in flat]
        ax.plot(x, [s.metrics["pue"] for s in flat], "o-", label="Annual PUE")
        ax.plot(x, [s.peaks["worst_hour"]["pue"] for s in flat], "s--", label="Peak hourly PUE")
        ax.set_xlabel("IT load (% of installed)")
        ax.set_ylabel("PUE")
        ax.grid(alpha=0.3)
        ax.legend()
        save(fig, "pue_vs_it_load.png")
    # monthly stacked energy
    h = base.hourly
    cols = [c for c in h.columns if c.startswith("eu:")]
    m = h.groupby("month")[cols].sum() / 1e3
    groups = {}
    for c in cols:
        grp = end_use_label(c[3:])[1]
        groups[grp] = groups.get(grp, 0) + m[c]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bottom = np.zeros(12)
    for grp, v in groups.items():
        ax.bar(MONTH_NAMES, v.values, bottom=bottom, label=grp)
        bottom += v.values
    ax.set_ylabel("MWh")
    ax.set_title(f"Monthly infrastructure electricity, {base.name}")
    ax.legend(fontsize=7, ncol=2)
    save(fig, "monthly_energy.png")
    # hourly PUE carpet and flow / PLR histograms per scenario
    for s in res.scenarios:
        safe = s.name.replace("%", "pct").replace(" ", "_")
        fig, ax = plt.subplots(figsize=(9, 3.5))
        im = ax.imshow(s.hourly.pue.to_numpy().reshape(365, 24).T, aspect="auto", origin="lower", cmap="viridis")
        ax.set_xlabel("Day of year")
        ax.set_ylabel("Hour")
        ax.set_title(f"Hourly PUE, {s.name}")
        fig.colorbar(im, ax=ax)
        save(fig, f"pue_carpet_{safe}.png")
        if s.it.flat_fraction is None:
            fig, ax = plt.subplots(figsize=(9, 3.5))
            ax.plot(s.hourly.it_kw.to_numpy(), lw=0.5, label="IT")
            ax.plot(s.hourly.infra_net_kw.to_numpy(), lw=0.5, label="Infrastructure")
            ax.set_xlabel("Hour of year")
            ax.set_ylabel("kW")
            ax.legend()
            save(fig, f"it_vs_infra_{safe}.png")
    d = base.sim.detail
    plr = [v["plr"][v["n_run"] > 0] for k, v in d.items() if k.startswith("chiller:") and (v["n_run"] > 0).any()]
    if plr:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.hist(np.concatenate(plr), bins=20, range=(0, 1))
        ax.set_xlabel("Chiller PLR")
        ax.set_ylabel("Hours")
        ax.set_title(f"Chiller part-load ratio, {base.name}")
        save(fig, "chiller_plr_hist.png")
    fl = {k: v["f"][v["n_run"] > 0] for k, v in d.items() if "f" in v and "n_run" in v and (v["n_run"] > 0).any()}
    if fl:
        fig, ax = plt.subplots(figsize=(7, 4))
        for k, v in list(fl.items())[:8]:
            ax.hist(np.clip(v, 0, 1.2), bins=24, range=(0, 1.2), histtype="step", label=k)
        ax.set_xlabel("Flow fraction f (before f_min clamp)")
        ax.set_ylabel("Hours")
        ax.legend(fontsize=6)
        save(fig, "fan_pump_flow_fraction_hist.png")
    modes = [(k[6:], v["mode"]) for k, v in d.items() if k.startswith("plant:")]
    if modes:
        fig, ax = plt.subplots(figsize=(6, 4))
        labels = ["Off", "Full FC", "Partial", "Mechanical"]
        w = 0.8 / len(modes)
        for i, (nm, mo) in enumerate(modes):
            ax.bar(np.arange(4) + i * w, [(mo == k).sum() for k in range(4)], width=w, label=nm)
        ax.set_xticks(np.arange(4) + 0.4 - w / 2)
        ax.set_xticklabels(labels)
        ax.set_ylabel("Hours")
        ax.legend()
        save(fig, "mode_hours.png")
    return files
