# QuickPUE review and improvement plan

Status: plan for review. No code was changed by this review.
Date: 2026-11-05
Baseline: QuickPUE 0.1.0, commit `bbbbaa1` (main after PR 2, web input editor)
Companion to: `docs/NEW_TOOL_REQUIREMENTS.md` (v0.4), `docs/DESIGN_DECISIONS.md`, `docs/VALIDATION.md`, `docs/TEST_CASES.md`

## Contents

1. [Summary](#1-summary)
2. [Codebase overview](#2-codebase-overview)
3. [Requirements coverage](#3-requirements-coverage)
4. [Confirmed defects and honesty gaps](#4-confirmed-defects-and-honesty-gaps)
5. [Code improvements](#5-code-improvements)
6. [Product improvements](#6-product-improvements)
7. [Other ways to meet the original requirements](#7-other-ways-to-meet-the-original-requirements)
8. [Roadmap](#8-roadmap)
9. [Decisions needed](#9-decisions-needed)
10. [Appendix A: probe evidence](#appendix-a-probe-evidence)
11. [Appendix B: measured metrics](#appendix-b-measured-metrics)
12. [Appendix C: research notes and references](#appendix-c-research-notes-and-references)

### Method

* Read every document in `docs/`, every Python module, all presets and output sets, the web editor backend
  and the structure of its front end.
* Ran the full test suite, line coverage, `ruff` (default and extended rule sets) and `mypy`; ran the DC_O1
  reference case end to end; ran targeted probe scripts against suspected defects (Appendix A); opened the web
  editor in headless Chromium and captured its pages (no console errors).
* Researched standards, regulation, peer tools and methods that bear on the requirements (Appendix C).

### Identifiers used in this plan

| Prefix | Meaning |
|-|-|
| F-xx | Confirmed defect or honesty gap, reproduced by a probe or read directly from the code |
| C-xx | Code quality and architecture improvement |
| P-xx | Product improvement (scope, workflow, modelling, outputs) |

Priority: **High** (fix before the next release used on a project), **Medium** (next 1 to 3 months),
**Low** (opportunistic). Effort: **S** up to 2 days, **M** 3 to 10 days, **L** 2 to 6 weeks, **XL** more than
6 weeks.

## 1. Summary

### What is in good shape

* **Architecture follows the specification.** Schema, loader with attribution, preset merge, sizing by design
  passes, a vectorised hourly engine with a year-wide fixed-point coupling, metrics, tables, exports, and an
  input-only web editor. Phases P1, P2, P4, P5 and P7 of requirements Section 18 are delivered, and P8
  (water-cooled plants) apart from its DCOPTEST comparison (V-O-1).
* **Transparency culture is built in.** Source IDs (`sources.py`), the input register with origins (user,
  preset, default, auto), an assumptions page, a calculation report and `explain`.
* **Performance is far ahead of target.** 0.11 s per scenario against the 5 s target (NF-1); DC_O1 with four
  scenarios, the adiabatic counterfactual, CSV tables, hourly files and charts runs in 9.8 s.
* **Tests are meaningful.** 96 tests pass in 39 s; component checks V-C-1 to V-C-7; T1 reference checks; every
  preset from minimum input; web API tests. Line coverage is 90 % overall and 92 % for the engine (NF-8
  target met).
* **The web editor is usable and careful.** Schema-driven forms, preset-aware placeholders, origin notes per
  field, a system diagram and loss allocation view, a local-only server with host and content-type checks.

### What needs attention first

1. **The input register misses defaults the engine applies in code** (F-01). The free-cooling coil rating
   (50 % of chiller capacity, fan power 2 %) is the parameter `docs/VALIDATION.md` names as the main DC_O1
   chiller gap, and it never appears in the register. Eight of fifteen sampled engine defaults are missing.
   This works against PR-2 and REQ-ATTR-2.
2. **Some inputs are silently ignored or overwritten** (F-02, F-03, F-06). A condenser water reset of type
   `ambient_linear` runs as a constant 29.4 C; `fixed` runs at 12.78 C; an explicit `standby: 0` becomes 1;
   `max_ambient_c`, `condenser_flow_l_s` and the site coordinates are accepted and never used.
3. **Water use is undercounted** when adiabatic pads run in free-cooling mode (F-04): enabling the option
   lowers reported water from 7,316 kL to 4,124 kL.
4. **Default tower sizing and condenser reset do not match** (F-05): towers are sized at the mean coincident
   wet bulb (20.2 C) instead of the 0.4 % wet bulb (23.1 C), with a 4 K approach against a T_wb + 3 K reset, so
   the towers in the LC-WCC and AIR-WCC presets run at full fan for about 8,450 of 8,760 h.
5. **Validation holes** (F-07, F-08, F-09, F-10): negative duty counts, missing reset parameters, a zero-IT
   scenario that crashes, unit tags on fields such as `electricity_kg_per_kwh` that raise, and user presets
   that cannot extend built-in presets.
6. **EnergyPlus equivalence (D1) has not started** (phases P3 and P6). It is the main credibility gap for any
   formal acceptance route (D8).
7. **The engine is hard to extend safely** (C-01, C-02): `_iterate` has cyclomatic complexity 66, `_plant` 44,
   `sizing._apply_sizes` 56; state moves in string-keyed dictionaries; the sized project reuses the input
   schema's Optional fields (99 mypy errors).

### Largest product opportunities

* **Regulatory output sets the engine can already almost produce**: ASHRAE 90.4 MLC and ELC (the LEED and
  IECC 2024 path for data centres), EU Energy Efficiency Directive KPIs and the EU rating label, and the
  German EnEfG checks (PUE 1.2 and energy reuse factor for new data centres from July 2026).
* **Heat reuse and ERF / ERE modelling**, which the EnEfG and EU reporting now require at design stage.
* **Built-in sensitivity, uncertainty and climate screening** (UC-3, UC-4). At 0.1 s per scenario, a
  1,000-sample Monte Carlo takes minutes.
* **Better chiller modelling at elevated chilled water** (table model, lift-dependent part load, optimal
  staging), where the DC_O1 gap sits.
* **A results view**: a self-contained HTML report first, then optionally a Run button in the editor.
* **Current design practice**: W32 to W45 liquid-cooled presets for AI halls, indirect evaporative and
  air-side economiser plants, IT profile generation for ramp-up and AI workloads, zone heating.

### Recommended sequence

| Phase | Duration | Content |
|-|-|-|
| A | 2 to 3 weeks | Correctness and honesty fixes (F-01 to F-12), CI hardening, golden and property-based tests |
| B | 4 to 8 weeks | Engine refactor behind golden tests, structured warnings, reproducibility stamp, EnergyPlus component harness, climate library, sensitivity and sweep commands, HTML report, chiller table model |
| C | 3 to 6 months | Heat reuse and ERF, ASHRAE 90.4, EU and German output sets, new plant types and presets, IT profile generator, carbon and water extensions, plant-level and system EnergyPlus equivalence |
| D | Later | Cost and TCO, storage, results in the editor (decision), operational calibration, back-testing (D9) |

## 2. Codebase overview

### 2.1 Data flow

```
project file (YAML, Python or dict)
  |  inputs.load_project: strip {value, unit, source}, record register entries,
  |  merge the preset template by item name, expand minimum input
  v
schema.Project (pydantic, schema 1.0)
  |  runner.prepare: read_epw, sizing.size_project (design passes at the EPW 0.4 % point)
  v
sized Project + DesignLoads -> engine.Engine (built once per run)
  |  per scenario: scenarios.build_it_input -> Engine.simulate
  |  fixed point over all 8,760 h: electrical chain -> halls -> CDUs, FWUs -> zones, room units
  |  -> loops (children first) -> plants
  v
SimResult (end uses, detail arrays, ledger) -> runner (metrics, peaks, warnings, register)
  v
tables.all_tables (OUT-1 to OUT-12, GHG) -> outputs.export (tables, hourly, charts, reports)
```

Key design facts:

* Hours are independent, so every quantity is a numpy vector of 8,760 values; the coupling between
  infrastructure power, electrical losses, room gains and cooling is a fixed-point iteration over the whole
  year, with detection of discrete staging limit cycles.
* Auto-sizing runs the same engine on a two-hour synthetic weather file at the design point (installed IT and
  the sizing IT fraction), then sizes from those loads and runs again for M1 group design loads.
* Preset templates merge under user input; lists of named items merge by `name`; `_remove: true` deletes.
* The register records the origin of each value: `user`, `preset`, `default` (schema default with a
  description) or `auto` (sizing rule).

### 2.2 Module map

| Path | Lines | Role |
|-|-|-|
| `quickpue/engine.py` | 1,607 | Hourly engine: electrical chain, halls, CDUs, FWUs, zones, room units, loops, all plant types, other end uses, ledger |
| `quickpue/schema.py` | 585 | Pydantic input schema (one model for input and sized project) |
| `quickpue/tables.py` | 455 | OUT-1 to OUT-12 and GHG tables |
| `quickpue/sizing.py` | 362 | Auto-sizing rules (8.4.2) from design passes |
| `quickpue/runner.py` | 318 | Orchestration, metrics, peaks, derived warnings, register build |
| `quickpue/inputs.py` | 268 | Loading, attribution, unit conversion, presets, minimum input |
| `quickpue/curves.py` | 267 | FFLP library, drive correction, chiller curve objects |
| `quickpue/weather.py` | 259 | EPW reader, design conditions, monthly summary |
| `quickpue/report.py` | 255 | Calculation report, assumptions page, warnings, `explain` |
| `quickpue/chiller.py` | 230 | EIR chiller model, library, table fit, staging |
| `quickpue/heatx.py` | 212 | Effectiveness-NTU, air-water coils, towers, adiabatic and evaporation |
| `quickpue/partload.py` | 181 | Fan and pump groups: methods M1 to M6, running rules |
| `quickpue/cli.py`, `outputs.py`, `charts.py`, `sources.py`, `psychro.py`, `scenarios.py`, `schedules.py`, `fluids.py` | 887 | CLI, exports, charts, source register, psychrometrics, IT scenarios, profiles, fluid properties |
| `quickpue/webui/` (Python) | 702 | Editor server and JSON API |
| `quickpue/webui/static/` | 3,857 | Editor front end (six ES modules, CSS, HTML), no build step |
| `quickpue/presets/` | 21 files | 18 topology presets and 3 shared bases |
| `tests/` | 827 + cases | Four test modules, DC_O1 and DC_S1 projects, comparison script |

### 2.3 Measured state

| Item | Result |
|-|-|
| Tests | 96 passed in 39 s (Python 3.13); CI runs 3.10 and 3.13 plus a CLI smoke run |
| Line coverage | 90 % overall; engine 92 %, sizing 98 %, schema 98 %; lowest: `schedules` 51 %, `cli` 65 %, `webui/server` 64 %, `scenarios` 75 % |
| Runtime | 0.11 s per scenario (4 MW, LC-ACC-IFC-AD, 6 coupling iterations); DC_O1 full run with exports 9.8 s |
| Lint (`ruff`, extended rules) | 362 findings: 131 style (`Optional` annotations), 59 magic numbers, 27 functions above complexity 10, 18 functions with too many arguments; no correctness findings beyond unused arguments |
| Types (`mypy`) | 99 errors in 11 files; 44 in `sizing.py`, mostly Optional schema fields used as definite values after sizing |
| Hourly output | DC_O1: 234 columns per scenario, 84 MB of CSV for four scenarios (Parquet skipped silently without `pyarrow`) |
| Warnings | DC_O1: 42 free-text warnings, many repeated per scenario |
| Register | DC_O1: 450 rows; 266 user values without a source kind |
| Repository hygiene | No `LICENSE`, `NOTICE`, `CHANGELOG` or `CONTRIBUTING` file |

## 3. Requirements coverage

Status: **Done**, **Partial** (works with a stated gap) or **Open** (not started).

| Requirement | Status | Evidence and gap |
|-|-|-|
| REQ-UI-1 Python API | Done | `quickpue/__init__.py`: `load_project`, `run`, `export`, `explain` |
| REQ-UI-2 CLI | Partial | `run`, `validate`, `batch`, `explain`, `presets`, `weather` work; `export-eplus` is a stub (phase P3) |
| REQ-UI-3 YAML or Python, versioned schema | Partial | Both load; `schema_version` is stamped but there is no migration path for future schema versions |
| REQ-UI-4 Enumerated types, invalid combinations fail | Partial | Plant type rules exist, but CP-7 and CP-8 rules are identical (WSE not required), reset parameters are not validated, negative duty is accepted (F-07) |
| REQ-UI-5 Templates incl. DCOPTEST and [KO26] cases | Partial | 18 presets; no [KO26] W17 / W45 templates and no "DCOPTEST compatible" template (Section 17) |
| REQ-UI-6 Output sets | Done | Five YAML sets plus user files |
| REQ-ATTR-1 `{value, unit, source}` | Partial | Works for simple suffixes; composite fields such as `electricity_kg_per_kwh` are misclassified (F-09) |
| REQ-ATTR-2 Defaults recorded as assumptions | Partial | Defaults applied inside the engine and Optional defaults are not recorded (F-01) |
| REQ-ATTR-3 Input register export | Done | `input_register.csv`, OUT-6b, OUT-6c, editor register page |
| REQ-DM-1 Redundancy modes | Done | `N+x`, `2N_active`, `0.5N+0.5N` for fans, pumps and room units |
| REQ-DM-2 / 2b Part-load model for every type | Partial | Fans, pumps, chillers, CDUs, heat rejection, UPS, transformers, DX; the "user defined plant item with PLR table" of 11.1 is not implemented |
| REQ-DM-4 Link validation | Done | `Engine._check_links` |
| 8.4 Presets and minimum input | Done | 18 presets, minimum input expands to one hall type |
| REQ-PRE-1 Assumptions page | Done | Printed before results |
| REQ-PRE-2 User presets | Partial | Project folder presets load, but `extends` is ignored for them (F-10) |
| REQ-PRE-3 Auto-sized values flagged in equipment tables | Partial | Flagged in the register; OUT-9a has no auto-sized flag column |
| IN-P-6 Designer PUE comparison | Partial | Field shown in the input overview only; no comparison output |
| IN-W-2 Distance to site | Partial | `distance_km` is reported; `site_latitude` / `site_longitude` are accepted but unused although `haversine_km` exists |
| IN-W-3 Design and extreme conditions | Partial | EPW header 0.4 % values used; the 0.4 % wet bulb and extremes are parsed but unused (F-05); no STAT file |
| IN-IT-5 8,760 h profile | Partial | Works, including leap day and repeat; timestamps are not checked against the EPW year and weekday |
| IN-L-3 Supply reset, load based | Partial | Fixed, ambient linear, wet bulb and dry bulb offset; load-based reset missing |
| IN-CH-12 Operating limits | Open | `max_ambient_c` accepted and unused; no high-ambient derate (F-06) |
| IN-E-1 Lineups | Partial | IT and mechanical UPS paths and `on_ups` flags; no explicit lineup objects |
| REQ-C-1 to 7 General and coupling | Done | Vectorised fixed point; limit cycle detection; bounded bisection |
| REQ-C-5 Energy balance closure | Partial | The ledger closes to 1e-15 but mostly by construction (F-12); no site-boundary first-law check |
| REQ-C-CDU-2 Approach model | Partial | `load_scaled` and `fixed`; the effectiveness-NTU option with `UA ~ m^0.8` is missing |
| REQ-C-CDU-3 TCS return, LMTD, junction | Partial | Junction check only; TCS return and LMTD not reported |
| REQ-C-CH-1 to 7 Chillers | Done | EIR model, table fit, staging, cycling and false loading, validity flags; fit is unbounded least squares (REQ-C-CH-2 asks for bounded) |
| REQ-C-IFC-1 to 4 Free cooling, adiabatic, counterfactual | Partial | Implemented; pad water in free-cooling mode is not counted (F-04) |
| REQ-C-HR-1 to 4 Dry coolers, towers, WSE | Done | Simplified tower model documented in DESIGN_DECISIONS |
| REQ-C-Z-0 to 5 Zones and room units | Partial | Implemented; zone heating is reported but not modelled |
| REQ-C-E-1 to 4 Electrical chain | Done | Physical and simplified conventions, bases per element |
| REQ-C-O-1 to 3 Other end uses | Done | Lifts use a stated approximation of the GBCA method |
| REQ-C-M-1 to 4 Metrics | Partial | Energy-weighted PUE, hourly PUE, WUE, GHG; peak PUE gives one worst hour per scenario rather than both framings across scenarios (F-17); zero IT crashes (F-08) |
| Section 11 Fans and pumps | Done | M1 to M6, R-ALL, R-STAGE, R-EPSEQ, curve library, `k_drive`; R-STAGE hysteresis missing |
| Section 12 Multi-temperature loops | Done | DT-A to DT-D with tests |
| REQ-OUT-H-1 to 3 Hourly files | Partial | CSV always; Parquet only with `pyarrow`, skipped silently (F-15) |
| OUT-1 to OUT-12 | Done | All tables present |
| REQ-OUT-13 / 14 Formats and charts | Done | CSV, MD, JSON, XLSX; eight chart types |
| REQ-OUT-T-1 Calculation report | Done | Equation list is maintained by hand next to the code (C-10) |
| REQ-OUT-T-2 `explain` | Partial | Fans, pumps, chillers, losses and PUE only (F-16) |
| 13.4 Warnings | Partial | Most categories; fan and pump flow overload not warned (F-14); free text only (C-07) |
| V-C-1 to 7 Component verification | Done | `tests/test_components.py` |
| V-E-1 to 7, 14.3 EnergyPlus equivalence | Open | Needs the exporter (P-01) |
| V-O-1 DCOPTEST, V-O-2 [KO26] | Open | P-02 |
| V-O-3 Balance closure in regression cases | Done | As an accounting check (F-12) |
| V-O-4 Randomised inputs never raise | Open | No property-based tests; a zero-IT scenario raises (F-08) |
| V-O-5 Golden results per template | Partial | Reference case assertions exist; presets are only checked for 1.0 < PUE < 2.5 |
| NF-1 Performance | Done | 0.11 s per scenario |
| NF-2 Determinism | Done | `test_determinism` |
| NF-5 Versioning and reproducibility | Partial | Version and schema stamped; no input or EPW hash, no run record (C-09) |
| NF-6 SI / IP display | Open | SI only; IP units rejected on input (F-09) |
| NF-7 Licensing | Open | No licence file; EnergyPlus-derived curve data has no notice (F-20) |
| NF-8 Typed, 90 % coverage | Partial | Coverage met; 99 type errors and no type check in CI |

## 4. Confirmed defects and honesty gaps

Each item was reproduced by a probe (Appendix A) or read directly from the code. Line numbers refer to
commit `bbbbaa1`.

| ID | Priority | Finding | Evidence | Impact | Fix | Effort |
|-|-|-|-|-|-|-|
| F-01 | High | Defaults applied in engine code never reach the input register | Free-cooling coil 50 % of capacity and fan 2 % (`engine.py:296`, `:304`); chiller minimum PLR 0.15, ignoring the library entry's own value (`engine.py:283`); occupant gains 70 / 60 W (`engine.py:430`, `:443`); zone RH limit 50 % when unset (`engine.py:456`); room unit air dT 10 K and density 1.2 (`engine.py:824`); supply air humidity ratio 0.008 (`engine.py:730`); dry cooler enable dT 1 K (`engine.py:1128`); WSE approach 2 K without a WSE block (`engine.py:1155`, `:1378`); CW reset fallback (`engine.py:1258`). `runner._walk_defaults` skips Optional defaults and fields without a description (`runner.py:316`), so hall height, cold aisle, loop HX approach, tower approach and zone height are also missing. Probe A: 8 of 15 sampled defaults missing | PR-2, REQ-ATTR-2; the largest DC_O1 driver is invisible to reviewers; the editor shows an empty "Minimum PLR" although 0.15 applies | Move every default into a schema field with a description and source ID, or into a `log.set` sizing rule; add a test that every field the engine reads is in the register | M |
| F-02 | High | Condenser water reset types are not honoured | `_cw_setpoint` (`engine.py:1254` to `1263`): `fixed` returns `min_c` (12.78 C by default); `ambient_linear` returns a constant 29.4 C and ignores its parameters. Probe 3: PUE 1.254 with wet bulb reset, 1.306 with `ambient_linear` | Silent wrong results for a user input | Implement `ambient_linear` for condenser water, add an explicit setpoint for `fixed`, validate required parameters | S |
| F-03 | High | An explicit `standby: 0` becomes 1 | `x.standby or 1` in `sizing.py:179`, `:227`, `:263`, `:299`, `:323` cannot tell 0 from unset. Probe 2: user `standby: 0` gives quantity 5, standby 1. Even without user input the sized standby is never logged: the minimum example has no register entry for chiller standby, and the editor placeholder shows "0, tool default" while the run uses 1 | User value overwritten; the register and editor do not show the standby the run uses | Make `standby` Optional and test `is None`; log the sized standby as `auto` | S |
| F-04 | High | Pad water is not counted in free-cooling mode | CP-2 branch applies pads to the coil air when `adiabatic_in_free_cooling` is set (`engine.py:1077` to `1085`) but computes no water and sets no adiabatic flag; water is only computed for running chillers. Probe C: enabling the option lowers water from 7,316 kL to 4,124 kL | WUE understated (PR-5) | Compute evaporation from coil airflow at the solved fan speed and the pad temperature drop; set the adiabatic flag | S |
| F-05 | Medium | Tower sizing and condenser reset defaults are inconsistent | Towers are rated at the wet bulb coincident with the 0.4 % dry bulb (20.2 C, `sizing.py:332`), not the parsed 0.4 % wet bulb (23.1 C), with a 4 K approach, while the preset reset is T_wb + 3 K. Probe B: towers saturated 3,635 h and at full fan 8,448 h (LC-WCC); similar for AIR-WCC | Tower fan energy overstated for every water-cooled preset; permanent warnings | Size towers at the 0.4 % wet bulb (or a selectable extreme); default reset offset equal to the tower approach; consider an optimised setpoint (P-12). This is internal consistency, not tuning to a reference case | S |
| F-06 | Medium | Inputs accepted but ignored | `Chiller.max_ambient_c`, `Chiller.condenser_flow_l_s`, `WeatherSpec.site_latitude` and `site_longitude` have no reader outside `schema.py`; `haversine_km` is never called | A user expects a limit or a distance that never applies | Implement (high-ambient limit as unmet with a warning; distance from coordinates) or reject with a message | S |
| F-07 | Medium | Validation gaps | Probe 10: `quantity: 1, standby: 2` gives duty -1 (dry coolers, towers, chillers, FWUs, room units). Probe 4: `ambient_linear` without parameters raises a numpy `TypeError`. Probe 4b: a reversed ambient band is accepted. Probe 11: CP-7 runs without a WSE block using a hidden 2 K approach because the CP-7 and CP-8 rules are identical (`engine.py:1521`). PV hourly CSV length is unchecked (`engine.py:1496`). An EFLH override above the ramp EFLH pushes the hourly fraction above 1 (`engine.py:1458`) | Obscure errors or silent nonsense | Pydantic validators and targeted tests | S |
| F-08 | Medium | A zero-IT scenario crashes | `np.nanargmax` on an all-NaN hourly PUE (`runner.py:184`); probe 5 | V-O-4 requires that valid inputs never raise | Guard; report PUE as undefined with a warning | S |
| F-09 | Medium | Unit handling is incomplete | `_unit_for` infers the unit from the last suffix (`inputs.py:59`): `electricity_kg_per_kwh` is treated as kWh, `server_airflow_l_s_per_kw` as kW, `diesel_mwh_per_l` as litres; a correct unit tag raises (probe 1) and the register shows wrong units. No IP units (probe E), no affine conversion for degrees Fahrenheit | REQ-ATTR-1, NF-6; blocks US workflows | Unit metadata per field instead of suffix inference; IP units with affine support (C-04) | M |
| F-10 | Medium | User presets cannot extend built-in presets | `load_preset` returns a project-folder preset before resolving `extends` (`inputs.py:175` to `177`). Probe D: a user preset extending LC-ACC loads with no plants | REQ-PRE-2 | Resolve `extends` for every preset; detect cycles | S |
| F-11 | Medium | Inner loops run a fixed number of passes without a residual check | Condenser loop 4 passes (`engine.py:1306`); CP-7 economiser 6 passes with 0.5 relaxation (`engine.py:1398`) | Possible silent non-convergence (PR-5) | Residual check, hour count warning, shared solver (C-08) | S |
| F-12 | Medium | The energy ledger is mostly an accounting identity | Plant `removed += q_delivered + unmet` (`engine.py:931`) where unmet is a residual, so the plant term closes by construction; zone and DX terms are similar | The closure check cannot detect a component that under-delivers or loses heat | Keep the ledger; add an independent site-boundary first-law check: electricity in equals heat rejected by plants, DX condensers, outdoor losses, envelope and ventilation, plus unmet (C-05) | M |
| F-13 | Low | Water properties assumed for glycol loops in tower and WSE paths | The loop capacity rate is converted to an equivalent water mass flow by dividing by 4.186 (`engine.py:1157`, `:1379`). Capacity rates are preserved, but the tower water-flow UA modifier and drift use the equivalent flow | Negligible for water, small for glycol loops | Pass the loop medium properties explicitly | S |
| F-14 | Low | Fan and pump flow overload is computed but not reported | `FanPumpGroup.evaluate` returns `overload`; only FWU coil and CDU overloads produce warnings | Capacity shortfall hidden (PR-5) | Warn when f > 1 with all units running | S |
| F-15 | Low | Silent or unused pieces | Parquet export skipped without a message (`outputs.py:129`); the `fit` extra (scipy) is never imported; chiller fit is unbounded | Confusing install and output behaviour | Message when Parquet is skipped; use `scipy.optimize.lsq_linear` for bounded fits or drop the extra | S |
| F-16 | Low | `explain` covers only part of the model | Probe F: CDU, FWU, zones and loops raise `KeyError`; dry coolers, towers, adiabatic water and loop mixing have no equation chain (`report.py:137`) | REQ-OUT-T-2 "any result" | Explain providers per component (falls out of C-01) | M |
| F-17 | Low | Peak PUE framing | One worst hour per scenario; the two framings of REQ-C-M-3 are not reported side by side; `explain pue` spreads diesel even when `annual_items_hourly: separate` | Reporting detail | Peak table across scenarios with conditions and powers | S |
| F-18 | Low | Warnings are unstructured | Free text, repeated per scenario (42 for DC_O1), no code or severity | Hard to filter, test or show in the editor | Structured issues (C-07) | M |
| F-19 | Low | EPW gaps | Missing values handled for dry bulb, dew point and pressure, not RH or GHI (PV shape); extreme values parsed but unused | Rare bad files give wrong PV shape | Extend missing-value handling; use extremes in design options (P-03) | S |
| F-20 | Low | No licence or third-party notice | Repository root | NF-7; curve coefficients come from EnergyPlus datasets | Add `LICENSE` (BSD-3-Clause is compatible with DCOPTEST and EnergyPlus), `NOTICE`, `CHANGELOG` | S |
| F-21 | Low | Auto-sized values are not flagged in equipment tables | OUT-9a rows carry values but not their origin | REQ-PRE-3 | Add an origin column from the register | S |

## 5. Code improvements

### 5.1 Overview

| ID | Priority | Improvement | Effort |
|-|-|-|-|
| C-01 | High | Split the engine into typed components with explicit contributions | L |
| C-02 | High | Separate the input model from a resolved (sized) model that carries value, unit and origin | L |
| C-03 | High | One defaults and constants registry with source IDs | M |
| C-04 | Medium | Field-level unit metadata, IP units and IP display | M |
| C-05 | High | Test strategy: golden files, property-based, metamorphic and first-law tests | M |
| C-06 | High | CI: ruff, mypy, coverage gate, reference drift check, wheel build | S |
| C-07 | Medium | Structured issues instead of warning strings | M |
| C-08 | Medium | Solver hygiene: residuals, shared bracketed solver, iteration counts in hourly output | S |
| C-09 | Medium | Reproducibility stamp and run record; schema migrations | M |
| C-10 | Medium | Generate the equation table from code annotations; test ID consistency | S |
| C-11 | Low | Output layout: Parquet by default, summary and detail hourly files, documented column names | S |
| C-12 | Medium | Packaging and documentation: licence, changelog, API docs, release process | M |
| C-13 | Low | Web editor: browser smoke test in CI, parity tests for mirrored logic, root-limited reads | S |
| C-14 | Low | Parallel batch and sweep execution with cached weather and sizing | S |

### 5.2 Details

**C-01 Engine components.** Today `Engine._iterate` (complexity 66) runs halls, CDUs, FWUs, zones, room
units and loops inline, and `Engine._plant` (44) switches on `pl.type` across all plant families. State
travels as dictionaries keyed by strings such as `"chiller:ACC"`, and reports, warnings and charts parse
those keys back. Proposed structure:

* `components/` with `HallModel`, `CDUModel`, `FWUModel`, `ZoneModel`, `RoomUnitModel`, `LoopNetwork`,
  `ElectricalChain` and one `PlantModel` subclass per family: air-cooled chillers (CP-1, CP-2), dry coolers
  with or without trim chillers (CP-3 to CP-6), towers (CP-7 to CP-9), water-cooled chillers on dry coolers
  (CP-10).
* Each component returns a typed contribution: end-use arrays, ledger terms (heat in, heat out, unmet),
  detail arrays, issues and an `explain(hour)` provider. A registry maps plant type to class.
* Keep numpy vectorisation and the year-wide fixed point. Migrate one component at a time behind golden
  results (C-05) so that every step shows identical numbers.

Benefits: new plant types (P-13, P-14) become additions rather than edits to a 245-line method; `explain`
(F-16) and structured issues (C-07) come per component; complexity drops below 15 per function.

**C-02 Resolved model.** `schema.Project` serves both as input (Optional everywhere) and as the sized model,
which is why `mypy` reports 44 errors in `sizing.py` and why the engine re-checks None in many places.
Introduce a `ResolvedProject` produced by sizing, with every field required and each value carrying
`(value, unit, origin, source)`. The register is then built from the resolved model, not reconstructed from
three places (`lp.register`, `SizingLog`, `_walk_defaults`), which removes the class of gaps in F-01 and
F-03 by construction.

**C-03 Defaults registry.** A `defaults.py` holding every constant the engine uses (occupant gains, air
density, specific heats, CW reset bounds, chiller minimum PLR, default pressure rises) with a source ID and a
basis text. The engine reads only from the resolved model or this registry. A test fails if a numeric literal
other than 0, 1 or a physical constant appears in engine code (ruff `PLR2004` finds 59 candidates today).

**C-04 Units.** Declare the unit per field in the schema (`json_schema_extra={"unit": "kg/kWh"}`) instead of
inferring it from the name suffix. Support IP input (degrees Fahrenheit with affine conversion, gpm, cfm,
tons, Btu/h, in. w.g., ft) through a table or the optional `pint` package, and an IP display option for
tables (NF-6). Keep SI internally.

**C-05 Tests.**

* Golden results per preset and reference case: end uses, PUE, water, peak and selected hourly series with
  per-variable tolerances (V-O-5), stored as small JSON files and regenerated deliberately.
* Property-based tests with Hypothesis that generate valid projects (presets, hall mixes, loops, plant
  types, scenarios) and assert: no exception, closed ledger, non-negative end uses, monotonic sanity (more IT
  never lowers infrastructure energy at equal weather) (V-O-4).
* Metamorphic tests: scaling all equipment and IT by k scales energy by k; splitting a hall type into two
  identical types changes nothing; a flat profile equals the flat scenario (exists).
* A site-boundary first-law test (F-12).
* Raise coverage of `schedules`, `scenarios`, `cli` and the server (51 to 75 % today).

**C-06 CI.** Add `ruff` with a curated rule set (bugbear, simplify, pyupgrade, complexity warnings), `mypy`
on core modules (strict for new code), a coverage gate (90 % engine, NF-8), a Python 3.10 to 3.13 matrix, a
step that regenerates `docs/VALIDATION_RESULTS.md` and fails on unexplained drift, and a wheel build.

**C-07 Structured issues.** Replace warning strings with an `Issue` record: code (stable, documented),
severity, requirement reference, item, scenario, hours affected, magnitude (kWh, K) and message. Aggregate
across scenarios, export as JSON and CSV, and let the editor and CI filter by code.

**C-08 Solver hygiene.** One vectorised bracketed solver with a tolerance and a returned residual (bisection
or Brent), used by coils, towers and condenser loops; residuals and iteration counts in the hourly output;
warnings for any inner loop that does not converge (F-11).

**C-09 Reproducibility.** Stamp every output with the SHA-256 of the input file and EPW, the resolved project
as JSON, the package version and git commit, and the run time. Add `quickpue rerun results.json` and
versioned schema migrations keyed by `schema_version` (NF-5).

**C-10 Traceability automation.** Annotate engine functions with their source IDs (decorator or constant)
and generate the equation table of the calculation report from them. A test asserts that every ID used in
code exists in `sources.py` and every registered equation is used.

**C-11 Outputs.** Parquet by default when available (with a message otherwise); a documented column naming
scheme (`component:item:variable`); a summary hourly file plus per-component detail files instead of one
234-column CSV; optional single-file run archive.

**C-12 Packaging and documentation.** `LICENSE`, `NOTICE` (EnergyPlus datasets, ASHRAE correlations, test
EPW source), `CHANGELOG`, `CONTRIBUTING`; an API and method site (for example MkDocs with mkdocstrings) whose
equation pages come from the source register; semantic versioning and tagged releases with wheels.

**C-13 Web editor.** Add a headless browser smoke test in CI (load, edit, check, save) because the JS has no
tests. Add parity tests that run `deepMerge` and `expandMinimum` (JS) and `inputs.deep_merge` and
`inputs._expand_minimum` (Python) on the same fixtures, or return the merged project from `/api/check` so
the mirror can be removed. Limit `/api/weather` to files under the root like other reads (it currently
parses any absolute `.epw` path; low risk on a loopback bind).

**C-14 Parallel runs.** A process pool for `batch`, sweeps and sensitivity runs (P-05, P-06), with weather
parsing and sizing cached per unique input.

## 6. Product improvements

### 6.1 Close the remaining specification gaps

| ID | Priority | Improvement | Effort |
|-|-|-|-|
| P-01 | High | EnergyPlus equivalence, built plant first (D1, phases P3 and P6) | XL (start M) |
| P-02 | Medium | DCOPTEST Types 7 to 12 and [KO26] W17 / W45 validation cases and templates (V-O-1, V-O-2, REQ-UI-5) | M |
| P-03 | Medium | Climate library and design condition options | M |
| P-04 | Medium | Smaller specification items | M |

**P-01 EnergyPlus equivalence.** Build it in three steps so value arrives early:

1. Component harness: generate single-component epJSON models (chiller, pump, fan, tower, dry cooler) driven
   by `LoadProfile:Plant` and schedules for boundary conditions, run EnergyPlus, compare hourly (V-E-1 to
   V-E-4, V-E-7). Small models, fast, and they isolate equation differences.
2. Plant-level models: export the hourly loop loads that QuickPUE computes and let EnergyPlus plant loops
   serve them (chillers, free cooling, towers, pumps, multi-temperature arrangements). This covers most of the
   energy and avoids zone geometry.
3. Full system models last, including zones and loss gains, for 14.3.

Generate epJSON (JSON) from the resolved model rather than IDF text; run EnergyPlus through its command line
or Python API in a CI container with a pinned version. Web research found EnergyPlus releases up to 26.2.0
and an open feature request for liquid-cooled ITE, but did not confirm a released
`ElectricEquipment:ITE:LiquidCooled` object or locate the [KO26] paper; plan V-E-5 on the fallback in
requirements 5.4 (`LoadProfile:Plant` plus an air-side gain) until the object is confirmed.

**P-02 Validation cases.** Add "DCOPTEST compatible" and [KO26] W17 / W45 templates (REQ-UI-5) and the
corresponding validation scripts once the source data is available. Record differences in
`docs/VALIDATION.md` without adjusting defaults (CLAUDE.md rule).

**P-03 Climate library.** Ship a manifest of the 19 ASHRAE climate zone locations (requirements 2.2.8) and
fetch TMYx files on demand from climate.onebuilding.org (free, more than 16,100 locations, refreshed in 2026
with 2025 ASHRAE design conditions), with checksums. Add design condition options: 0.4 % wet bulb for
evaporative equipment, 1 %, extreme annual mean, and n-year return values, because data centre heat
rejection is often selected to extreme conditions (fixes part of F-05).

**P-04 Smaller items.** IP units and display (NF-6); designer PUE comparison (IN-P-6); CDU
effectiveness-NTU variable flow option and TCS return and LMTD outputs (REQ-C-CDU-2, 3); load-based loop
reset (IN-L-3); explicit lineups (IN-E-1); user-defined plant item with a PLR table (11.1); R-STAGE
hysteresis (11.5); profile timestamp and weekday alignment checks (IN-IT-5).

### 6.2 Workflow features (use cases UC-2 to UC-5)

| ID | Priority | Improvement | Effort |
|-|-|-|-|
| P-05 | High | Sensitivity and uncertainty command (UC-3) | M |
| P-06 | Medium | Climate screening sweep (UC-4) | S |
| P-07 | Medium | Option comparison and input diff (UC-2) | M |
| P-08 | High | Self-contained HTML report; later a results view in the editor | M |
| P-09 | Medium | Peak power and capacity outputs (UC-5) | S |
| P-10 | Low | Workflow report templates | M |

**P-05 Sensitivity and uncertainty.** `quickpue sensitivity project.yaml study.yaml` with three modes:
one-at-a-time low / high values producing a tornado chart; Morris screening; Monte Carlo or quasi-Monte Carlo
with Sobol indices. Default uncertainty bands can come from the source kind already attached to every input
(narrow for `document`, medium for `pending_manufacturer`, wide for `assumption`), which turns the register
into an uncertainty model. Outputs: P10 / P50 / P90 PUE, energy and water per scenario, ranked drivers.
A 2024 study found CRAH supply air temperature and air temperature difference the most influential inputs
for annual PUE, and a comparison in another field (power-system reliability) found Morris screening needed
about half the computation of Sobol for comparable results (Appendix C).

**P-06 Climate screening.** `quickpue sweep project.yaml` over a folder of EPW files or the climate library,
with a table and chart of PUE, WUE and peak per location; parallel (C-14).

**P-07 Option comparison.** A variants file in YAML (overlays on a base project, no Python needed), a
comparison report of end-use deltas, PUE, water and peaks, and `quickpue diff a.yaml b.yaml` that lists input
differences with their register origins.

**P-08 Results view.** First a self-contained HTML report written by `quickpue run` (summary, end uses,
monthly, carpet plots, plant modes, warnings, register, calculation report) with no server and no external
assets. Then, as a decision (Section 9), a Run button and results page in the editor; the engine's speed
makes this interactive.

**P-09 Peak and capacity.** Peak facility power for grid connection with coincident ambient, monthly maximum
demand, N and N+1 capacity at the selected extreme condition, and an extreme-year option.

**P-10 Report templates.** Markdown and HTML templates for a NABERS-style simulation report appendix and an
engineering design-check memo, filled from the output sets.

### 6.3 Modelling scope

| ID | Priority | Improvement | Effort |
|-|-|-|-|
| P-11 | High | Chillers at elevated chilled water: table model, lift-dependent part load, optimal staging, larger library | L |
| P-12 | Medium | Condenser water and tower control optimisation | M |
| P-13 | High | Heat reuse with heat pumps; ERF and ERE | L |
| P-14 | Medium | Indirect evaporative and air-side economiser plants | L |
| P-15 | Medium | AI-era liquid cooling presets and architectures | M |
| P-16 | Medium | Zone heating and humidification energy | M |
| P-17 | Medium | IT profile generator and multi-year phasing | M |
| P-18 | Medium | Water and carbon extensions | M |
| P-19 | Low | Energy cost and simple TCO for option comparison | M |
| P-20 | Low | Thermal storage and battery storage | M |

**P-11 Chillers.** The DOE-2 EIR form with `EIRFPLR(PLR)` cannot represent the strong lift dependence of
part-load efficiency in variable-speed and free-cooling chillers at 24 to 28 C chilled water, which is where
`docs/VALIDATION.md` places the DC_O1 gap. Options, in order of value:

1. A table model: capacity and power against leaving chilled water, condenser temperature and PLR, with
   multilinear interpolation and validity counts, read directly from manufacturer selection output.
2. A reformulated EIR option with `EIRFPLR(T_cond, PLR)` (the EnergyPlus `Chiller:Electric:ReformulatedEIR`
   form uses leaving condenser temperature and needs more points, about 12 full-load and 7 part-load).
3. Staging choices `min_units`, `all_duty` and `optimal` (choose the running count that minimises power each
   hour; cheap when vectorised).
4. A larger library: the DCOPTEST reference chiller promised in Section 17, more EnergyPlus dataset entries,
   and free-cooling chiller analogues, each with its rating conditions.

**P-12 Condenser and tower control.** An optimised condenser water setpoint that minimises chiller, tower
fan and condenser pump power each hour over a few candidate setpoints, alongside the fixed reset, plus
defaults that follow from the tower rating (F-05).

**P-13 Heat reuse.** Recover heat from the warm loop return (liquid cooling around 40 to 45 C), lift it with
a heat pump (COP against lift, part load) to a supply temperature, serve an hourly reuse demand (district
heating, on-site buildings), and report reused energy, ERF and ERE per EN 50600-4-6 / ISO/IEC 30134-6, with
the heat pump inside or outside the PUE boundary as a stated choice. Drivers: the German EnEfG requires
new data centres from July 2026 to plan for an ERF of at least 10 %, rising to 20 % for those starting in
2028, and EU reporting includes ERF; district heating often needs 45 to 55 C or more, so heat pumps are
usually needed (Appendix C).

**P-14 Air-side plants.** Indirect evaporative coolers, direct air-side economisers with evaporative assist
and heat wheels are common for air-cooled halls and absent from the 8.2 catalog. Model them as plant types
serving hall air directly: heat exchanger effectiveness, wet and dry modes, fan power at solved airflow,
mechanical trim, water use.

**P-15 AI-era liquid cooling.** Presets with facility water at W32, W40 and W45 (ASHRAE classes W17, W27,
W32, W40, W45, W+), liquid fractions of 0.85 to 0.95 and high rack densities; dry coolers with trim
chillers; rear-door heat exchangers; single-phase immersion as a CDU and loop variant; TCS temperatures
(TC 9.9 S classes) and CDU approach at part load. Keep them as presets and defaults, not new physics, where
possible (PR-6).

**P-16 Zone heating.** DC_O1 reports net heat loss without a heating model in the substation for 7,548 h
and the office for 5,254 h. Add a heating device per zone (electric, heat pump COP against ambient, or
recovered heat) and heating end uses, so office VRF energy is complete.

**P-17 IT profiles.** A generator for 8,760 h profiles: phased fit-out (halls commissioned by month),
ramp-up curves, diurnal inference patterns, steady training load, plus multi-year runs (year 1 to N) for
lifetime energy and GHG. Sub-hourly training power swings matter for electrical design, not for annual
energy; keep the hourly engine and report this limit (Section 7).

**P-18 Water and carbon.** Hourly emission factors (8,760 h CSV per grid region) for location-based
reporting and time-matched market-based reporting, which the GHG Protocol Scope 2 revision proposes (final
guidance expected in late 2027); CUE (ISO/IEC 30134-8); source WUE (water used to generate the grid
electricity, user factor); renewable energy factor inputs (on-site PV, contracted supply). All factors stay
user supplied (D14).

**P-19 Cost.** Tariffs (flat, time of use, demand charge), water cost, optional carbon price and simple
capital inputs, for option comparison only (no cost database).

**P-20 Storage.** Chilled water storage (DC_O1 has tanks, not modelled) and battery storage have small
annual energy effects; keep as later items unless a workflow needs them.

### 6.4 Output sets for current standards and regulation

| ID | Priority | Output set | Effort |
|-|-|-|-|
| P-21 | High | ASHRAE 90.4 MLC and ELC (LEED, IECC 2024) | M |
| P-22 | Medium | EU Energy Efficiency Directive KPIs and rating label inputs | M |
| P-23 | Medium | German EnEfG check | S (after P-13) |
| P-24 | Medium | ISO/IEC 30134 and EN 50600-4 alignment | S |
| P-25 | Medium | NABERS review pack | S |

**P-21 ASHRAE 90.4.** The engine already computes mechanical energy at several IT loads and electrical
losses by element. Add a scenario preset at 100 / 75 / 50 / 25 % of design ITE load, annualised MLC from the
mechanical end uses, and ELC by segment (UPS segment and ITE distribution segment; the incoming service
segment was removed in the 2022 edition, which also requires ELC compliance at all four load levels). Keep
D14: the user supplies the limit values (or loads a table they are licensed to use); the tool reports the
calculated values. Verify formulas against the purchased standard before release.

**P-22 EU EED.** Estimate, for a planned facility, the indicators the EU reporting regime derives (PUE, WUE,
ERF, REF) and the underlying quantities (total and IT energy, water input, reused heat, renewable energy).
The Commission's rating scheme (grades for PUE and WUE generated from reported data) was reported as adopted
in autumn 2026 by some sources and as proposed by others; confirm before building grade bands, which in any
case should be user-supplied data (D14).

**P-23 EnEfG.** Annual PUE against 1.2 for data centres starting operation from 1 July 2026, projected ERF
against 10 / 15 / 20 % by start year, and PUE trajectories for existing facilities (1.5 from 2027, 1.3 from
2030). Secondary sources disagree on some definitions and an amendment was reported in 2026; cite the
statute in the output.

**P-24 ISO/IEC 30134.** Label PUE by measurement category (IT energy at UPS output, PDU output or IT input,
mapped from the metering point), report CUE and WUE per parts 8 and 9, and add designed PUE (dPUE) once the
revised ISO/IEC 30134-2 (a 2026 draft includes a dPUE clause and calculation annex) is published.

**P-25 NABERS.** The NABERS Handbook for estimating ratings (v3.2) has data-centre chapters on simulation
and documentation, and commitment agreements require an independent design review. Add an export that
bundles inputs, register, calculation report, warnings, assumptions and a diff against the previous
submission.

### 6.5 After design stage

* **Operational comparison and calibration (P-26, Low, M).** Import metered hourly IT and facility energy
  after commissioning, compare with the model (NMBE and CV(RMSE), the metrics already named in 14.3), and
  re-run with as-built inputs. This supports the NABERS rating that follows 12 to 24 months of operation and
  later back-testing (D9).

## 7. Other ways to meet the original requirements

| Requirement | Current approach | Alternatives | Assessment and recommendation |
|-|-|-|-|
| D1 equivalence with EnergyPlus | Full exporter planned (P3, P6), not started | (a) Plant-first harness with `LoadProfile:Plant` (P-01); (b) LBNL Modelica Buildings data centre package as a second, open-source reference; (c) a published analytical test suite in the spirit of ASHRAE 140 that any tool can run; (d) full system exporter | Do (a) and (c) first: they deliver component and plant equivalence quickly and give third parties a way to check the tool. Keep (d) for 14.3. Use (b) only if a dynamic reference is needed |
| D8 formal acceptance | TBD | Equivalence report (D1); independent peer review; publication of the method and test suite; NABERS independent design review practice | Acceptance is about evidence: version-stamped equivalence reports, the open test suite and an independent review are the practical route |
| D2 library and CLI, no GUI in v1 | CLI plus input-only editor | (a) HTML report; (b) Run and results in the editor; (c) notebook widgets; (d) a dashboard framework | (a) now (no rule change); (b) as a decision; (c) and (d) add dependencies without clear gain |
| D10 YAML or Python input, no Excel | YAML, Python, JSON | Excel import adapter that converts an equipment schedule to YAML with attribution | Keeps YAML as the record while meeting how schedules arrive in practice |
| D5 hourly simulation | 8,760 h vectors | Sub-hourly engine; hourly engine plus a synthetic sub-hourly overlay for peaks | Keep hourly ([KO26] lesson 1); report sub-hourly AI power swings as out of scope for energy |
| PR-1 physics, 8.4.2 defaults | Fixed default rules | Defaults by size class from published datasets with citations | Improves first results without tuning to the reference cases |
| PR-3 traceability | Hand-maintained equation list | Code annotations generating the report (C-10) | Removes drift between code and report |
| Weather | One TMY EPW per run | Climate library (P-03); multi-year actual years for variability; morphed future weather (CCWorldWeatherGen has licence limits; an open-source Future Weather Generator exists) | Add the library and a multi-year option first; future weather as a later study option |
| NF-1 performance | numpy vectorisation | numba, JAX | Not needed at 0.1 s per scenario; JAX only if gradient-based optimisation becomes a goal |
| Quasi-steady physics | Algebraic, hourly | Modelica dynamic models | Quasi-steady is sufficient for annual energy; dynamic models only for controls and transients |

## 8. Roadmap

### Phase A: correctness and honesty (2 to 3 weeks)

| Work | Items |
|-|-|
| Register completeness | F-01, F-03, F-21, start of C-03 |
| Silent input handling | F-02, F-06, F-07, F-08, F-10 |
| Physics fixes | F-04, F-05, F-11, F-13, F-14 |
| Units | F-09 (composite fields first; IP units in Phase B) |
| Tests and CI | C-05 golden files and property tests, C-06, F-12 first-law check |
| Hygiene | F-15, F-19, F-20 |

Exit criteria: every field the engine reads appears in the register with an origin; property-based tests
(at least 500 generated projects) never raise; the first-law check closes within 0.5 % in every hour of every
preset; CI runs ruff, mypy on core modules and the coverage gate; `docs/VALIDATION_RESULTS.md` regenerated
and `docs/VALIDATION.md` and `docs/DESIGN_DECISIONS.md` updated for changed numbers (F-05 changes the
water-cooled presets).

### Phase B: structure and first workflow features (4 to 8 weeks)

| Work | Items |
|-|-|
| Engine structure | C-01, C-02, C-08, C-10 (behind golden results) |
| Issues and reproducibility | C-07, C-09, C-11 |
| Equivalence step 1 | P-01 component harness for chillers, pumps, fans, towers, dry coolers |
| Workflow | P-03, P-05, P-06, P-08 (HTML report), P-09 |
| Chillers | P-11 table model and staging options, P-12 |
| Units | C-04 IP units and display |

Exit criteria: no function above complexity 15 in `engine` and `sizing`; zero mypy errors in core modules;
V-E-1 to V-E-4 within the 14.2 targets; sensitivity and sweep commands documented with examples; HTML report
produced by `quickpue run`.

### Phase C: scope and regulation (3 to 6 months)

| Work | Items |
|-|-|
| New physics | P-13 heat reuse, P-14 air-side plants, P-16 zone heating |
| Presets and profiles | P-15, P-17 |
| Metrics and output sets | P-18, P-21, P-22, P-23, P-24, P-25 |
| Equivalence steps 2 and 3 | P-01 plant-level and system models, P-02 validation cases |
| Documentation | C-12 method site and release process |

Exit criteria: ERF and ERE reported with a documented boundary; 90.4 MLC and ELC reproduced on a worked
example; plant-level equivalence within 14.3 targets for at least one preset per plant family.

### Phase D: later

P-19 cost, P-20 storage, a Run button and results in the editor (if decided), P-26 operational
calibration, back-testing (D9).

### Quick wins (each S effort, high value)

F-02, F-03, F-04, F-07, F-08, F-10, F-20, C-06.

## 9. Decisions needed

| # | Question | Options | Recommendation |
|-|-|-|-|
| 1 | Should the editor run simulations and show results? | Keep input-only (CLAUDE.md rule, D2); allow Run and a results page | Ship the HTML report first; revisit after users try it |
| 2 | Is a plant-first equivalence harness acceptable as the first D1 deliverable? Which EnergyPlus version to pin? | Plant first; full system first | Plant first, pinned to the newest release at start of work |
| 3 | Which regulatory output set first? | ASHRAE 90.4; EU EED; EnEfG | ASHRAE 90.4 (largest market, uses existing results); EnEfG after heat reuse |
| 4 | Bundle limit values (90.4 tables, EU grade bands) or require user data? | Bundle; user supplied | User supplied, consistent with D14 and licensing |
| 5 | Heat reuse boundary | Heat pump inside or outside PUE; on-site use or district heating interface | Both boundaries as a stated option; district heating as an hourly demand profile |
| 6 | Accept default changes that move results (F-05 tower rating and reset, F-01 visibility of free-cooling defaults)? | Yes, with documented reasons; no | Yes: these are consistency fixes, not tuning, and are recorded in VALIDATION.md |
| 7 | Licence | BSD-3-Clause; other | BSD-3-Clause (compatible with DCOPTEST and EnergyPlus, NF-7) |
| 8 | Units library | Built-in table; optional `pint` | Built-in table with affine support; `pint` optional |

## Appendix A: probe evidence

Probe scripts were run against commit `bbbbaa1` with the test EPW and minimum-input projects at 4 MW
(liquid fraction 0.75, 90 % IT unless stated).

| Probe | Input | Observed |
|-|-|-|
| 1 | `ghg.electricity_kg_per_kwh: {value: 0.7, unit: kg/kWh}` | `ValueError: unit 'kg/kWh' not convertible to the field unit (kwh)`; register unit for the plain value is `kwh` |
| 2 | LC-ACC with chiller `standby: 0` | Sized quantity 5, duty 4, standby 1 |
| 3 | LC-WCC with condenser reset `wetbulb_offset`, `fixed`, `ambient_linear` (10 to 30 C, 20 to 30 C) | Setpoint 12.78 to 23.89 C (PUE 1.254); constant 12.78 C (PUE 1.254); constant 29.4 C (PUE 1.306) |
| 4 | Loop reset `ambient_linear` without parameters | `TypeError: Cannot cast array data from dtype('O') to dtype('float64')` |
| 4b | `t_amb_low_c: 30`, `t_amb_high_c: 20` | Accepted; supply range 24.0 to 28.0 C |
| 5 | Scenario `it_fraction: 0.0` | `ValueError: All-NaN slice encountered` |
| 10 | Dry cooler `quantity: 1, standby: 2` | Loaded with duty -1 |
| 11 | CP-7 plant with no WSE block | Runs with a hidden 2 K approach (PUE 1.121) |
| 12 | LC-ACC-IFC-AD timing | 0.11 s per scenario, 6 iterations |
| A | Register check for 15 defaults the engine uses | Missing: hall height, cold aisle, loop HX approach, chiller minimum PLR, free-cooling air-to-water ratio, rated capacity and fan power, zone height |
| B | Towers in water-cooled presets | LC-WCC: saturated 3,635 h, full fan 8,448 h; AIR-WCC: 3,618 h and 8,438 h; LC-WCC-WSE: 497 h; LC-WSE: 781 h |
| C | Pads at 20 C activation, `adiabatic_in_free_cooling` off and on | Water 7,316 kL and 4,124 kL; adiabatic hours 2,707 in both |
| D | Project-folder preset `extends: LC-ACC` | Loads with no plants |
| E | Loop supply `{value: 75, unit: F}` | `ValueError: unit 'F' not convertible` |
| F | `explain` for CDU, FWU, zone and loop names | `KeyError` for each |
| Tower sizing | Test EPW design data | Towers rated at 20.2 C (MCWB at 0.4 % DB); 0.4 % wet bulb is 23.1 C; T_wb exceeds 20.2 C in 544 h |
| Editor | Chiller page of the minimum example | Shows "Standby 0, tool default" and an empty "Minimum PLR" while the run uses 1 and 0.15; the register has no entry for either |

## Appendix B: measured metrics

Line coverage by module (pytest-cov, full suite):

| Module | Cover | Module | Cover |
|-|-|-|-|
| `engine.py` | 92 % | `tables.py` | 95 % |
| `sizing.py` | 98 % | `report.py` | 85 % |
| `schema.py` | 98 % | `outputs.py` | 91 % |
| `runner.py` | 96 % | `charts.py` | 93 % |
| `inputs.py` | 92 % | `cli.py` | 65 % |
| `partload.py` | 90 % | `scenarios.py` | 75 % |
| `chiller.py` | 88 % | `schedules.py` | 51 % |
| `curves.py` | 85 % | `weather.py` | 83 % |
| `heatx.py` | 97 % | `psychro.py` | 93 % |
| `webui/api.py` | 86 % | `webui/server.py` | 64 % |
| **Total** | **90 %** | | |

Functions above complexity 10 (ruff C901), largest first: `Engine._iterate` 66, `sizing._apply_sizes` 56,
`Engine._plant` 44, `Engine._check_links` 25, `runner._derived_warnings` 23, `Engine.simulate` 23,
`tables.design_check_tables` 19, `FanPumpGroup.evaluate` 19, `Engine._other_end_uses` 19,
`Engine._electrical` 18.

mypy errors by file: `sizing.py` 44, `schema.py` 17, `chiller.py` 10, `inputs.py` 7, `engine.py` 7,
`scenarios.py` 6, others 8. Typical causes: Optional schema fields used after sizing, positional unpacking
into `Biquadratic` that collides with keyword arguments, `deep_merge` reusing a variable for a dict and a
list.

Slowest tests: water-cooled presets from minimum input (about 3.8 s each), `nabers` export (3.8 s).

## Appendix C: research notes and references

### Standards and regulation

* **ASHRAE 90.4-2022.** Two checks: mechanical load component (MLC) from a full-year model at 25, 50, 75 and
  100 % of ITE design load (the design MLC option was removed in 2019) and electrical loss component (ELC);
  the 2022 edition removed the incoming service segment, lowered UPS segment limits and requires ELC at all
  four loads; the 2024 IECC references 90.4-2022; 90.1 points to 90.4 for large computer rooms.
  [CSE Magazine](https://www.csemag.com/ashrae-90.4-created-to-boost-data-center-energy-efficiency/),
  [ASHRAE 90.4-2022 fact sheet](https://www.ashrae.org/file%20library/about/government%20affairs/advocacy%20toolkit/virtual%20packet/standard-90.4-2022-fact-sheet.pdf),
  [TechTarget](https://www.techtarget.com/it-infrastructure/tip/ASHRAE-standard-904-updates-emphasize-green-energy),
  [CSE Magazine on IECC, 90.1 and 90.4](https://www.csemag.com/how-to-coordinate-iecc-ashrae-90-1-and-ashrae-90-4-for-data-centers/).
  LEED v5 data centre energy requirements were not confirmed by this research.
* **EU Energy Efficiency Directive.** Delegated Regulation (EU) 2024/1364 requires data centres with at least
  500 kW of installed IT power to report annually (by 15 May); PUE, WUE, ERF and REF are derived from the
  reports. A sustainability rating scheme with grades for PUE and WUE was proposed in September 2026 and
  reported as adopted by some sources in October 2026; minimum performance standards are at consultation
  stage.
  [DLA Piper](https://www.dlapiper.com/en/insights/publications/2024/09/new-data-centre-sustainability-reporting-obligations-introduced-through-eu-20241364-regulation),
  [EUDCA](https://www.eudca.org/energy-efficiency-directive),
  [Latham and Watkins](https://www.lw.com/en/insights/european-commission-proposes-mandatory-sustainability-label-for-data-centres),
  [Baker McKenzie](https://www.bakermckenzie.com/en/insight/publications/2026/10/european-union-sustainability-rating-scheme-for-data-centres),
  [Linklaters](https://sustainablefutures.linklaters.com/post/102o5fr/eu-commission-adopts-data-centre-sustainability-rating-scheme).
* **German EnEfG.** New data centres starting operation from 1 July 2026: PUE of 1.2 or less and an ERF of at
  least 10 % (15 % from July 2027, 20 % from July 2028); existing facilities PUE 1.5 from July 2027 and 1.3
  from July 2030. Sources differ on details and an amendment was reported in 2026; check the statute.
  [White and Case](https://www.whitecase.com/insight-alert/data-center-requirements-under-new-german-energy-efficiency-act),
  [Cundall](https://www.cundall.com/ideas/blog/has-the-german-energy-efficiency-act-become-a-thorn-in-the-side-of-german-data-centre-operators).
* **ISO/IEC 30134 and EN 50600-4.** PUE (part 2, EN 50600-4-2), ERF (part 6, EN 50600-4-6), CUE (part 8), WUE
  (part 9). A 2026 draft revision of ISO/IEC 30134-2 includes a clause on designed PUE (dPUE) and an informative
  calculation annex.
  [DIN draft contents](https://www.din.de/de/mitwirken/normenausschuesse/dke/veroeffentlichungen/wdc-beuth:din21:399194142/toc-3675648/download),
  [SDIA metrics overview](https://knowledge.sdialliance.org/data-center-metrics),
  [EN 50600-4-6](https://iteh.eu/catalog/standards/sist/8756dacc-5ad4-4b16-a8ed-224ea0f966cb/sist-en-50600-4-6-2020).
* **ASHRAE liquid cooling classes.** The 5th edition thermal guidelines (2021) define facility water classes
  W17, W27, W32, W40, W45 and W+; TC 9.9 has also presented technology cooling system classes.
  [Upsite](https://www.upsite.com/blog/major-changes-to-ashraes-fifth-edition-of-thermal-guidelines-part-3-liquid-cooling-chapter-updates/).
* **NABERS.** The Handbook for estimating NABERS ratings has data-centre simulation chapters; commitment
  agreements cover infrastructure, IT equipment or the whole facility and include an independent design
  review; ratings follow 12 to 24 months of operation.
  [Handbook](https://www.nabers.gov.au/sites/default/files/2022-11/Handbook%20for%20estimating%20NABERS%20ratings.pdf),
  [Commitment agreements](https://nabers.gov.au/ratings/commitment-agreements/what-commitment-agreement).
* **NSW SSDA.** The industry-specific assessment requirements for data storage centres ask how emissions are
  reduced in line with net zero by 2050 and for performance against recognised sustainability standards; no
  PUE figure was found.
  [Data Storage Centres SEARs](https://shared-drupal-s3fs.s3.ap-southeast-2.amazonaws.com/master-test/fapub_pdf/Industry-Specific+SEARs+-+Data+Storage+Centres+(1).pdf).
* **GHG Protocol Scope 2 revision.** Consultation closed December 2025; the proposal moves market-based
  reporting to hourly matching with deliverability; load profiles may estimate hourly use; final guidance
  expected late 2027.
  [Drax](https://energy.drax.com/insights/ghg-protocal-consult-scope-2/),
  [Inside Energy and Environment](https://www.insideenergyandenvironment.com/2025/11/the-greenhouse-gas-protocols-proposed-scope-2-guidance-key-changes-and-considerations-for-stakeholders/).

### Tools and libraries

* **EnergyPlus.** Releases up to 26.2.0 found; no liquid-cooled ITE object confirmed in release notes; a
  feature request for liquid-cooled ITE exists; NC State's BETlab describes an EnergyPlus framework for
  liquid-cooled data centres. The [KO26] paper was not found by search.
  [EnergyPlus 26.2.0](https://github.com/NatLabRockies/EnergyPlus/releases/tag/v26.2.0),
  [Issue 11408](https://github.com/NatLabRockies/EnergyPlus/issues/11408),
  [NCSU BETlab](https://research.design.ncsu.edu/betlab/?p=1784).
* **Reformulated EIR chiller.** Uses leaving condenser water temperature and a part-load curve of condenser
  temperature and PLR; needs more data points than the EIR model.
  [DesignBuilder help](https://designbuilder.co.uk/helpv7.2/Content/ChillerReformulatedEIR.htm).
* **Modelica Buildings library (LBNL).** Open-source data centre package (CRAH, CRAC, chillers with
  waterside economisers, templates).
  [LBNL Modelica](https://simulationresearch.lbl.gov/modelica/),
  [OSTI: data centre cooling systems](https://www.osti.gov/biblio/1543120).
* **Schneider Electric TradeOff Tools.** The Cooling Economizer Mode PUE Calculator takes location, IT
  capacity, density and temperature and returns PUE, energy cost, carbon and economiser hours by architecture.
  It is a screening tool; QuickPUE works at equipment-schedule level with attribution.
  [TradeOff Tools](https://www.se.com/ww/en/work/solutions/data-centers-and-networks/trade-off-tools/).
* **Weather.** climate.onebuilding.org provides free TMYx files for more than 16,100 locations, refreshed in
  2026 with 2025 ASHRAE design conditions; no API was documented. Morphing tools: CCWorldWeatherGen (licence
  limits) and an open-source Future Weather Generator.
  [climate.onebuilding.org](https://climate.onebuilding.org/),
  [news](https://www.climate.onebuilding.org/news/default.html),
  [CCWeatherGen](https://energy.soton.ac.uk/?p=10503),
  [Future Weather Generator](https://estudogeral.sib.uc.pt/bitstream/10316/105477/1/Rodrigues__Fernandes__Carvalho_-_2023_-_Future_weather_generator_for_building_performance_research_An_open-source_morphing_tool_and_an_a.pdf).

### Methods

* **Sensitivity and uncertainty.** A 2024 study built a PUE tool with sensitivity and uncertainty analysis
  and found CRAH supply temperature and temperature difference most influential; a 2022 study used
  quasi-Monte Carlo Sobol analysis across 60 regions; in a power-system reliability comparison, Morris
  screening needed about 49 % less computation than Sobol.
  [Buildings 2024](https://doaj.org/article/438d8ebf60b84510880291faa725b604),
  [Sensors 2022](https://www2.mdpi.com/1424-8220/22/10/3704),
  [Energy Proceedings](https://energy-proceedings.org/?p=11483).
* **Heat reuse.** ERF is reused energy over total energy (EN 50600-4-6); district heating at 45 to 55 C or
  above usually needs heat pumps to upgrade data centre heat.
  [Mitsubishi Electric](https://les.mitsubishielectric.co.uk/the-hub/energy-reuse-factor-redefining-data-centre-efficiency),
  [Frontiers in Sustainability](https://www.frontiersin.org/articles/10.3389/frsus.2022.1008583/pdf).
* **AI load behaviour.** Training creates repeated sub-minute power swings (modelled up to 4 kW per 8-GPU node);
  inference does not create similar patterns but shows diurnal variation.
  [Uptime Institute](https://intelligence.uptimeinstitute.com/resource/handling-ai-power-fluctuations-root-cause),
  [arXiv 2508.16457](https://arxiv.org/html/2508.16457v2).

### Market context

* Global average PUE has stayed near 1.54 for six years (Uptime Institute 2025 survey).
  [Uptime survey 2025](https://intelligence.uptimeinstitute.com/resource/uptime-institute-global-data-center-survey-2025),
  [Uptime PUE trends](https://intelligence.uptimeinstitute.com/resource/mapping-pue-trends-data-center-region-age-and-size).
* US data centres used 176 TWh in 2023 (about 4.4 % of US electricity), projected at 325 to 580 TWh by 2028
  (LBNL 2024 report).
  [LBNL news](https://newscenter.lbl.gov/2025/01/15/berkeley-lab-report-evaluates-increase-in-electricity-demand-from-data-centers/),
  [Report](https://datacenters.lbl.gov/publications/2024-lbnl-data-center-energy-usage-report).
