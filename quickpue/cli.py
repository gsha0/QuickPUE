"""Command line interface (REQ-UI-2)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import click

from . import __version__


@click.group()
@click.version_option(__version__, prog_name="quickpue")
def main():
    """QuickPUE: rapid, transparent data centre infrastructure energy and PUE estimator."""


@main.command()
@click.argument("project", type=click.Path(exists=True, dir_okay=False))
@click.option("-o", "--output-set", default=None, help="nabers | leed | ssda | design-check | full | path.yaml")
@click.option("--out", "out_dir", default=None, type=click.Path(), help="Output directory (default <project>_results)")
@click.option("-f", "--format", "formats", multiple=True, default=("csv", "md", "json", "xlsx"),
              help="Table formats: csv, md, json, xlsx (repeatable)")
@click.option("--scenario", "scenarios", multiple=True, help="Run only these scenario names")
@click.option("--no-hourly", is_flag=True, help="Skip hourly CSV / Parquet files")
@click.option("--no-charts", is_flag=True, help="Skip charts")
@click.option("--hourly-columns", default="full", type=click.Choice(["full", "summary", "plant", "fans_pumps",
                                                                     "electrical"]))
def run(project, output_set, out_dir, formats, scenarios, no_hourly, no_charts, hourly_columns):
    """Run PROJECT (YAML or Python) for all scenarios and export results."""
    from .outputs import export
    from .report import all_warnings, assumptions_page
    from .runner import run as run_project

    res = run_project(project, list(scenarios) or None)
    click.echo(assumptions_page(res))
    click.echo("")
    click.echo(res.summary().to_string(index=False, float_format=lambda v: f"{v:,.3f}"))
    out = Path(out_dir) if out_dir else Path(project).with_suffix("").parent / (Path(project).stem + "_results")
    fm = tuple(f for f in formats if f != "xlsx" or _has("openpyxl"))
    export(res, out, formats=fm, output_set=output_set, hourly=not no_hourly, charts=not no_charts,
           hourly_preset=hourly_columns)
    warns = all_warnings(res)
    click.echo(f"\n{len(warns)} warnings (see warnings.txt). Results written to {out}")


@main.command()
@click.argument("project", type=click.Path(exists=True, dir_okay=False))
def validate(project):
    """Validate PROJECT against the schema and links without running."""
    from .engine import Engine
    from .inputs import load_project
    from .runner import prepare

    try:
        lp = load_project(project)
        prepare(lp)
    except Exception as e:  # noqa: BLE001
        click.echo(f"INVALID: {e}", err=True)
        sys.exit(1)
    click.echo(f"OK: {project} (schema {lp.project.schema_version}, preset {lp.project.preset or 'none'})")


@main.command()
@click.argument("studies", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", "out_dir", default="batch_results", type=click.Path())
@click.option("-o", "--output-set", default=None)
def batch(studies, out_dir, output_set):
    """Run a Python STUDIES file defining STUDIES = {name: project dict or path} or studies()."""
    import pandas as pd

    from .inputs import load_project
    from .outputs import export
    from .runner import run as run_project

    spec = importlib.util.spec_from_file_location("quickpue_studies", studies)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    st = getattr(mod, "STUDIES", None) or mod.studies()
    rows = []
    base = Path(studies).resolve().parent
    for name, proj in st.items():
        lp = load_project(proj, base_dir=base) if isinstance(proj, dict) else load_project(base / proj)
        res = run_project(lp)
        export(res, Path(out_dir) / name, formats=("csv", "md", "json"), output_set=output_set, hourly=False,
               charts=False)
        df = res.summary()
        df.insert(0, "Study", name)
        rows.append(df)
        click.echo(f"{name}: " + ", ".join(f"{r.Scenario} PUE {r.PUE:.3f}" for r in df.itertuples()))
    allr = pd.concat(rows, ignore_index=True)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    allr.to_csv(Path(out_dir) / "batch_summary.csv", index=False)
    click.echo(f"Batch summary: {Path(out_dir) / 'batch_summary.csv'}")


@main.command("export-eplus")
@click.argument("project", type=click.Path(exists=True, dir_okay=False))
def export_eplus(project):
    """EnergyPlus reference model exporter (phase P3; not implemented in this version)."""
    click.echo("The EnergyPlus reference exporter (requirements 5.3, phase P3) is not implemented in this version. "
               "Component verification against analytical solutions is in the test suite.", err=True)
    sys.exit(2)


@main.command()
def presets():
    """List topology presets (8.4.1)."""
    from .inputs import list_presets

    for p in list_presets():
        click.echo(f"{p['id']:<18} {p['water_system']:<5} {p['plant_type']:<12} {p['dcoptest'] or '':<8} {p['name']}")


@main.command()
@click.argument("epw", type=click.Path(exists=True, dir_okay=False))
def weather(epw):
    """Print the weather file parameters and monthly summary (OUT-5)."""
    from .weather import monthly_summary, read_epw

    w = read_epw(epw)
    click.echo(f"{w.station_label()}  lat {w.latitude} lon {w.longitude} elev {w.elevation_m} m")
    click.echo(f"Design conditions: {w.design}")
    click.echo(monthly_summary(w).round(1).to_string())


@main.command()
@click.argument("project", type=click.Path(exists=True, dir_okay=False))
@click.argument("item")
@click.option("--hour", default=0, type=int, help="Hour index 0..8759")
@click.option("--scenario", default=None)
def explain(project, item, hour, scenario):
    """Print the equation chain and values for ITEM at HOUR (REQ-OUT-T-2)."""
    from .report import explain as ex
    from .runner import run as run_project

    res = run_project(project, [scenario] if scenario else None, counterfactual=False)
    click.echo(ex(res, item, hour, scenario))


def _has(mod):
    return importlib.util.find_spec(mod) is not None


if __name__ == "__main__":
    main()
