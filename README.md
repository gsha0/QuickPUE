# QuickPUE

Rapid, transparent data centre infrastructure energy and PUE estimator. QuickPUE takes equipment-schedule
inputs (or just a topology preset, IT load, liquid fraction and a weather file), simulates 8,760 hours per IT
load scenario with a quasi-steady physics engine, and reports annual and hourly energy by end use, PUE,
water use, optional GHG and equipment-level detail.

It implements `docs/NEW_TOOL_REQUIREMENTS.md` (v0.4) and is checked against the reference cases in
`docs/TEST_CASES.md` (results in `docs/VALIDATION_RESULTS.md`, discussion in `docs/VALIDATION.md`).

* Standalone Python (numpy, pandas, pydantic, pyyaml, click). No commercial simulation package.
* Every input can carry a unit and a source (`document`, `inference`, `designer`, `assumption`,
  `pending_manufacturer`); every default and auto-sized value lands in the input register.
* Every equation carries a source ID (`quickpue/sources.py`, requirements Section 15) and is listed in the
  calculation report; `explain` prints the equation chain and values for any result and hour.
* Hourly energy balance is checked in every hour; unmet loads, curve extrapolation, minimum-speed operation
  and capacity shortfalls are reported, never hidden.
* Optional web input editor (`quickpue-ui`) for building, checking and visualising input files in a browser.

## Install

```bash
pip install -e ".[dev]"
```

Optional extras: `xlsx` (openpyxl), `charts` (matplotlib), `parquet` (pyarrow), `fit` (scipy).

The install provides two commands: `quickpue` (CLI) and `quickpue-ui` (web input editor). The editor needs no
extra packages.

## Quick start (minimum input, UC-7)

```yaml
# examples/minimum_input.yaml
preset: LC-ACC-IFC-AD
project: {name: Minimum input example}
weather: {epw: ../tests/data/AUS_NSW_Horsley.Equestrian.Centre.947600_TMYx.2011-2025.epw}
it: {installed_kw: 10000, liquid_fraction: 0.8}
scenarios: nabers          # 90 / 75 / 50 / 25 % flat, 8,760 h
```

```bash
quickpue run examples/minimum_input.yaml -o nabers
```

The run prints the "assumptions applied" page, then the scenario summary, and writes tables (CSV, Markdown,
JSON, XLSX), hourly / daily / monthly files, charts, `calculation_report.md`, `input_register.csv`,
`warnings.txt` and `assumptions.txt` to `<project>_results/`.

From Python:

```python
import quickpue as q
res = q.run("examples/minimum_input.yaml")
print(res.summary())
print(q.explain(res, "chillers", hour=4000))
q.export(res, "out", formats=("csv", "md", "xlsx"), output_set="design-check")
```

## CLI

| Command | Purpose |
|-|-|
| `quickpue run project.yaml [-o SET] [--out DIR]` | Run all scenarios and export (sets: `nabers`, `leed`, `ssda`, `design-check`, `full`, or a YAML file) |
| `quickpue validate project.yaml` | Schema, link and sizing checks without running |
| `quickpue batch studies.py` | Run a dictionary of projects (`examples/studies.py`) and write a combined summary |
| `quickpue explain project.yaml ITEM --hour H` | Equation chain for an end use or equipment item at one hour |
| `quickpue presets` | List topology presets |
| `quickpue weather file.epw` | EPW parameters and monthly summary |
| `quickpue export-eplus project.yaml` | EnergyPlus reference exporter: not implemented yet (phase P3) |
| `quickpue-ui [project.yaml] [--root DIR]` | Web input editor (see below); inputs only, does not run the simulation |

## Web input editor

An optional browser front end for building, checking and visualising input files. It edits inputs only: it
never runs the simulation, and it reads and writes the same YAML project files as the CLI, so a file saved in
the editor runs unchanged with `quickpue run`.

```bash
quickpue-ui                                  # browse and edit projects under the current directory
quickpue-ui examples/minimum_input.yaml      # open a project (python -m quickpue.webui works too)
quickpue-ui --root ~/projects --port 8800 --no-browser
```

| Option | Default | Purpose |
|-|-|-|
| `project` | none | Project YAML to open at start |
| `--root DIR` | current directory, or the project's folder if it lies outside it | Folder the editor may list and save into |
| `--host` | `127.0.0.1` | Bind address (local only by default) |
| `--port` | `8765` | Port; `0` picks a free one |
| `--no-browser` | off | Do not open a browser window |
| `--verbose` | off | Log every request |

### Editing

* One page per schema section (project and preset, weather, IT and scenarios, halls, loops, plants, CDUs,
  FWUs, zones, room units, electrical, other end uses, boundary and GHG, settings). The forms are generated
  from the pydantic schema, so they follow `quickpue/schema.py`.
* Preset items show as "preset". **Customise** adds an entry of the same name whose values merge over the
  preset item (as in the YAML); **Remove** writes `_remove: true`; **Revert to preset** deletes your entries.
* Fields left empty are not written to the file. The placeholder shows the value that will apply and the
  note below it says where it comes from: preset, tool default (with its basis) or auto-sized (with the
  sizing rule from the design pass). The input register keeps the correct origin for every value.
* The tag next to each field attaches a unit and a source (`{value, unit, source}`), for example a capacity
  in MW from a document reference; the register shows the converted value.
* Files: New (preset, IT, liquid fraction, weather), Open (YAML or JSON under the root, or a file from this
  computer), Save, Save as, Download. Undo and redo cover form edits (Ctrl+Z / Ctrl+Y outside text fields,
  Ctrl+S saves). Unsaved edits are kept in the browser so they can be restored on the next visit.
* Paths in the file (EPW, profile CSVs, PV CSV) are relative to the project file. The Browse button lists
  files under the root; Save as to another folder rewrites relative paths so they still resolve.
* The YAML page shows the file text and accepts edits that are applied back to the form.

### Checking

* A live check runs the same steps as `quickpue validate`: schema, references and auto-sizing (design
  pass), without the hourly simulation. Errors are marked on the fields, counted per section and listed in
  the Issues panel with a link to the field. Unknown loop, hall and zone names are flagged as you type.
* The **Input register** page lists every value the run would use (entered, preset, tool default,
  auto-sized) with its source and basis, the same register the CLI writes to `input_register.csv`, and can be
  downloaded as CSV.

### Input visualisation

| Page | Shows |
|-|-|
| Weather | Station and design point, monthly temperatures, hourly dry bulb heatmap, hours per year above each input threshold (design DB, adiabatic activation, tower design WB, room unit activation) |
| IT load and scenarios | Installed IT, liquid share and IT load per flat scenario (liquid and air) |
| System diagram | Halls and zones, the CDUs, FWUs and room units serving them, loops and plants; missing references in red; click a box to edit it |
| Loss heat allocation | Where each electrical loss element releases its heat, as the engine resolves `losses` and `heat_outdoors`; unallocated shares highlighted |
| Within forms | Part-load (FFLP) curves with `f_min`, supply temperature reset, UPS efficiency and M6 tables, daily lighting and occupancy profiles, hours above the adiabatic activation, hall IT and density totals |

### Scope and safety

* Standard library HTTP server and plain JavaScript (no build step, no CDN): works offline.
* Bound to 127.0.0.1; requests with a non-local Host header and non-JSON posts are refused. It saves only
  `.yaml` / `.yml` files inside `--root` and does not open Python project scripts.
* Comments in a YAML file are not kept when the editor saves it; Save as keeps the original.
* Hourly profile CSVs are listed but not previewed.

## Project files

YAML (data) or Python (`PROJECT = {...}` or `project()` returning a dict) validated by one pydantic schema
(`quickpue/schema.py`). Units follow the field-name suffix: `_kw`, `_kwh`, `_c`, `_k`, `_l_s`, `_pa`, `_m2`,
`_m`. Any value may be written as `{value, unit, source}`:

```yaml
capacity_kw: {value: 2.2, unit: MW, source: {kind: document, ref: "Chiller schedule rev C"}}
```

Main sections: `halls`, `loops`, `plants` (chillers, dry coolers, towers, WSE, condenser water), `cdus`,
`fwus`, `zones`, `room_units`, `electrical` (UPS, transformers, distribution, PDU, loss heat allocation),
`other` (generator testing, jacket heaters, lifts, fixed loads, PV), `contingency`, `boundary`, `ghg`,
`scenarios`, `settings`. `tests/cases/dc_o1.yaml` is a fully worked equipment-schedule example.

With a `preset`, user sections merge over the preset template (lists of named items merge by `name`; an item
with `_remove: true` deletes the preset item). Any field left empty is auto-sized (requirements 8.4.2) from a
design pass at the EPW 0.4 % cooling condition.

### Scenarios

`nabers` (90 / 75 / 50 / 25 %), `design` (100 %), or a list of flat fractions and hourly profiles (UC-6):

```yaml
scenarios:
  - {name: "90%", it_fraction: 0.9}
  - {name: Ramp-up, profile: it_profile.csv, units: kW, column: it_kw}
  - {name: Typical week, profile: week.csv, units: fraction, repeat: true}
```

## Topology presets (8.4.1)

| Preset | Water system | Plant | DCOPTEST |
|-|-|-|-|
| AIR-WCC-WSE, AIR-WCC, AIR-WSE, AIR-DC, AIR-DC-CH, AIR-CH-DC | WS-6 | CP-7, CP-8, CP-9, CP-3, CP-5, CP-10 | Types 2, 3, 1, 4, 5, 6 |
| LC-WSE, LC-WCC-WSE, LC-WCC, LC-DC, LC-DC-CH, LC-CH-DC | WS-1 | CP-9, CP-7, CP-8, CP-3, CP-5, CP-10 | Types 7, 8, 9, 10, 11, 12 |
| LC-ACC, LC-ACC-IFC, LC-ACC-IFC-AD | WS-1 | CP-1, CP-2, CP-2 + adiabatic | new |
| LC-ACC-IFC-DUAL | WS-2 | CP-2 | new |
| LC-ADC-CH | WS-1 | CP-6 | new |
| LC-W45-DC | WS-5 | CP-3 + CP-1 | new ([KO26] W45) |

Preset files are YAML in `quickpue/presets/` (shared defaults in `_base_*.yaml`). A project directory may hold
its own `<ID>.yaml` presets.

## What the engine models

| Area | Implementation |
|-|-|
| Halls | IT per hall type, liquid fraction split (D11), lighting / people profiles, allocated loss heat |
| CDUs | Equal sharing, pump part-load model, approach scaled with load, TCS drift, optional junction check |
| FWUs, CRAH, FCU | Airflow from load and air dT (M2) or other PLR methods, fan curves, coil load and fan heat to loops |
| Fans and pumps | `P = N_run * P_des * FFLP(f_eff)`, methods M1 to M6, rules R-ALL / R-STAGE / R-EPSEQ, curve library 11.3, optional motor + VFD correction |
| Chillers | EnergyPlus EIR model; curves from manufacturer tables (least squares fit), coefficients, or a library analogue normalised to the rated point and flagged pending manufacturer; staging, cycling / false loading, validity warnings |
| Free cooling | Integrated free-cooling coils (CP-2), dry coolers (CP-3 to CP-6), towers with plate HX (CP-7, CP-9): full / partial / mechanical with fan speed solved by effectiveness-NTU |
| Adiabatic | Activation threshold, saturation efficiency, recirculation before or after the pads, water use, automatic dry counterfactual |
| Heat rejection | Dry coolers (cross-flow effectiveness-NTU, UA(f)), cooling towers (Merkel-type effectiveness with UA flow modifiers), condenser water reset |
| Loops | Supply resets, flows, bypass at minimum flow, return temperatures; multi-temperature arrangements DT-A blending, DT-B HX cascade, DT-C dedicated, DT-D split duty |
| Supporting zones | Box heat balance: allocated electrical losses, gains, envelope UA, infiltration, outdoor air, latent; CRAH, CRAC, PAC, VRF / split, FCU, dehumidifier, humidifier, OAF, EAF |
| Electrical | PDU, UPS (IT and mechanical paths, efficiency tables, physical or simplified convention), transformers (percent of a named basis or no-load + load loss), distribution; loss heat released to zones; coupled iteration |
| Other end uses | Generator testing diesel (Format A / B), jacket heaters (EPW ramp or stated EFLH), lifts, fixed loads (DHW, ancillary, office), PV credit, contingency |
| Metrics | Energy-ratio PUE (no emissions ratio or ratings, D14), pPUE, WUE, optional GHG with user factors, hourly PUE, peak PUE with conditions |

## Verification

```bash
pytest                                   # 96 tests, about a minute
python tests/cases/compare_reference.py  # regenerates docs/VALIDATION_RESULTS.md
```

* Component verification V-C-1 to V-C-7 (`tests/test_components.py`).
* Reference cases DC_O1 and DC_S1: W-01, T1 checks O-01 to O-11 and S-01 to S-06, T3 robustness
  (`tests/test_reference_cases.py`).
* Every preset runs from minimum input with the hourly energy balance closed (`tests/test_system.py`).
* Web input editor API: YAML written by the editor loads to the identical project and register for DC_O1 and
  DC_S1, check results and error locations, file access limited to the root (`tests/test_webui.py`, about 2 s).
* Performance: a scenario takes well under 1 s; four scenarios plus the adiabatic counterfactual about 2 s.

## Status and limitations

* The EnergyPlus reference exporter and the EnergyPlus equivalence suites (requirements 5.3, 14.2, 14.3;
  phases P3 and P6) are not implemented. Verification so far is analytical and against the reference cases.
* Design choices for items the requirements leave TBD are listed in `docs/DESIGN_DECISIONS.md`; they are
  defaults and can be changed per project.
* Chiller library curves are EnergyPlus dataset entries rated near standard CHW temperatures; at elevated CHW
  they are shifted to the project rated point and clamped, and every hour outside the curve range is counted.
  Use manufacturer data at project conditions for design results.
* Solar gains, thermal mass and sub-hourly controls are not modelled (requirements Section 6).
* The web input editor covers inputs only. Results come from `quickpue run` or the Python API.
