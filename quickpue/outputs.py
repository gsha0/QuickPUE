"""Exports: tables (CSV, Markdown, JSON, XLSX), hourly files (CSV, Parquet), daily / monthly aggregates,
charts, calculation report, input register and warnings (requirements 13)."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .report import all_warnings, assumptions_page, calculation_report
from .tables import TABLE_TITLES, all_tables

HOURLY_PRESETS = {
    "summary": ("month", "day", "hour", "t_db", "t_wb", "it_kw", "infra_net_kw", "pue", "pv_kw", "water_l_h"),
    "plant": ("plant:", "chiller:", "free_cooling:", "dry_cooler:", "tower:", "condenser:", "loop_"),
    "fans_pumps": ("pump:", "fwu:", "cdu:", "room_unit:"),
    "electrical": ("loss:", "eu:pdu", "eu:ups", "eu:transformer", "eu:distribution"),
}


def load_output_set(name_or_path) -> dict:
    p = Path(str(name_or_path))
    if p.suffix in (".yaml", ".yml") and p.exists():
        return yaml.safe_load(p.read_text())
    f = resources.files("quickpue.output_sets").joinpath(f"{name_or_path}.yaml")
    if not f.is_file():
        avail = [x.name[:-5] for x in resources.files("quickpue.output_sets").iterdir() if x.name.endswith(".yaml")]
        raise ValueError(f"unknown output set {name_or_path!r}; available: {', '.join(sorted(avail))}")
    return yaml.safe_load(f.read_text())


def hourly_columns(df: pd.DataFrame, preset: str = "full") -> pd.DataFrame:
    df = df[[c for c in df.columns if not c.startswith("_")]]
    if preset == "full":
        return df
    keys = HOURLY_PRESETS[preset]
    base = list(HOURLY_PRESETS["summary"])
    cols = [c for c in df.columns if c in base or any(c.startswith(k) for k in keys)]
    return df[cols]


def _md_table(df: pd.DataFrame, floatfmt="{:,.3f}") -> str:
    if df is None or df.empty:
        return "_(none)_"
    cols = list(df.columns)

    def f(v):
        if isinstance(v, (float, np.floating)):
            if np.isnan(v):
                return ""
            a = abs(v)
            if a >= 1000:
                return f"{v:,.0f}"
            if a >= 10:
                return f"{v:,.1f}"
            return f"{v:.3f}".rstrip("0").rstrip(".") if a > 0 else "0"
        s = str(v).replace("|", "/").replace("\n", " ")
        return s
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "-|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(f(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def export(res, out_dir, formats=("csv", "md", "json"), output_set=None, hourly=True, charts=True,
           hourly_preset="full") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    oset = load_output_set(output_set or res.project.project.workflow or "design-check")
    tables = all_tables(res)
    sel = [t for t in oset["tables"] if t in tables]
    written = {}
    stamp = (f"QuickPUE {res.version} (schema {res.schema_version}); project '{res.project.project.name}'; "
             f"output set {oset['id']}; reference documents: "
             f"{'; '.join(res.project.project.reference_documents) or 'none stated'}")
    if "csv" in formats:
        d = out / "tables"
        d.mkdir(exist_ok=True)
        for k in sel:
            p = d / f"{k}.csv"
            tables[k].to_csv(p, index=False)
            written[f"csv:{k}"] = str(p)
    if "json" in formats:
        p = out / "results.json"
        payload = {"stamp": stamp, "output_set": oset["id"],
                   "metrics": {s.name: s.metrics for s in res.scenarios},
                   "peaks": {s.name: s.peaks for s in res.scenarios},
                   "tables": {k: json.loads(tables[k].to_json(orient="records")) for k in sel},
                   "warnings": all_warnings(res)}
        p.write_text(json.dumps(payload, indent=1, default=float))
        written["json"] = str(p)
    if "xlsx" in formats:
        p = out / "results.xlsx"
        with pd.ExcelWriter(p) as xw:
            pd.DataFrame({"QuickPUE": [stamp]}).to_excel(xw, sheet_name="README", index=False)
            for k in sel:
                tables[k].to_excel(xw, sheet_name=k[:31], index=False)
            pd.DataFrame({"Warning": all_warnings(res)}).to_excel(xw, sheet_name="Warnings", index=False)
        written["xlsx"] = str(p)
    if "md" in formats:
        p = out / "report.md"
        L = [f"# {oset.get('title', 'QuickPUE results')}: {res.project.project.name}", "", f"_{stamp}_", "",
             "```", assumptions_page(res), "```", ""]
        for k in sel:
            L += [f"## {k}: {TABLE_TITLES.get(k, k)}", "", _md_table(tables[k]), ""]
        L += ["## Warnings", ""] + [f"* {w}" for w in all_warnings(res)] + [""]
        p.write_text("\n".join(L))
        written["md"] = str(p)
    # always: calculation report, input register, warnings, assumptions
    (out / "calculation_report.md").write_text(calculation_report(res))
    tables["OUT-6b"].to_csv(out / "input_register.csv", index=False)
    (out / "warnings.txt").write_text("\n".join(all_warnings(res)) + "\n")
    (out / "assumptions.txt").write_text(assumptions_page(res) + "\n")
    written.update({"calculation_report": str(out / "calculation_report.md"),
                    "input_register": str(out / "input_register.csv")})
    if hourly:
        hd = out / "hourly"
        hd.mkdir(exist_ok=True)
        for s in res.scenarios:
            safe = s.name.replace("%", "pct").replace(" ", "_").replace("/", "_")
            df = hourly_columns(s.hourly, hourly_preset)
            df.to_csv(hd / f"hourly_{safe}.csv", index=False)
            try:
                df.to_parquet(hd / f"hourly_{safe}.parquet", index=False)
            except Exception:
                pass
            num = s.hourly[[c for c in s.hourly.columns if c.startswith("eu:")] + ["it_kw", "pv_kw", "water_l_h"]]
            day = (np.arange(len(num)) // 24) + 1
            (num.groupby(day).sum() / 1e3).to_csv(hd / f"daily_MWh_{safe}.csv", index_label="day")
            (num.groupby(s.hourly.month).sum() / 1e3).to_csv(hd / f"monthly_MWh_{safe}.csv", index_label="month")
        written["hourly"] = str(hd)
    if charts:
        try:
            from .charts import make_charts

            written["charts"] = make_charts(res, out / "charts")
        except ImportError:
            (out / "charts_skipped.txt").write_text("matplotlib not installed; charts skipped\n")
    return written
