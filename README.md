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

## Install

```bash
pip install -e ".[dev]"
```

Optional extras: `xlsx` (openpyxl), `charts` (matplotlib), `parquet` (pyarrow), `fit` (scipy).

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
pytest                                   # 80+ tests, about a minute
python tests/cases/compare_reference.py  # regenerates docs/VALIDATION_RESULTS.md
```

* Component verification V-C-1 to V-C-7 (`tests/test_components.py`).
* Reference cases DC_O1 and DC_S1: W-01, T1 checks O-01 to O-11 and S-01 to S-06, T3 robustness
  (`tests/test_reference_cases.py`).
* Every preset runs from minimum input with the hourly energy balance closed (`tests/test_system.py`).
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
