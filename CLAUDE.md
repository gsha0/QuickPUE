# CLAUDE.md

QuickPUE: quasi-steady 8,760 h data centre infrastructure energy and PUE estimator (Python package `quickpue`).
Specification: `docs/NEW_TOOL_REQUIREMENTS.md`. Reference cases: `docs/TEST_CASES.md`. Choices for items the
specification leaves TBD: `docs/DESIGN_DECISIONS.md`.

## Commands

```bash
pip install -e ".[dev]"                     # install with test, xlsx and chart dependencies
pytest                                      # full suite, about 40 s
pytest tests/test_components.py             # fast component checks only
python tests/cases/compare_reference.py     # regenerate docs/VALIDATION_RESULTS.md
quickpue run examples/minimum_input.yaml    # smoke run of the CLI
quickpue-ui examples/minimum_input.yaml     # web input editor at http://127.0.0.1:8765/
```

## Layout

| Path | Contents |
|-|-|
| `quickpue/engine.py` | Hourly engine: electrical loss chain, halls, CDUs, FWUs, zones, room units, loops, plants, coupling iteration, energy ledger |
| `quickpue/sizing.py` | Auto-sizing rules (8.4.2) driven by design passes |
| `quickpue/schema.py` | Pydantic input schema |
| `quickpue/inputs.py` | Loading, `{value, unit, source}` attribution, unit conversion, preset merge |
| `quickpue/runner.py` | Scenario runs, metrics, input register |
| `quickpue/tables.py`, `outputs.py`, `report.py`, `charts.py` | OUT-1 to OUT-12, exports, calculation report, `explain` |
| `quickpue/sources.py` | Equation and data source register (S-EQ / S-DEF IDs) |
| `quickpue/presets/`, `quickpue/output_sets/` | Topology presets and workflow output sets (YAML) |
| `tests/cases/` | DC_O1 and DC_S1 reference projects and the comparison script |
| `quickpue/webui/` | Optional web input editor (inputs and input visualisation only): `server.py` (stdlib HTTP), `api.py` (JSON API over `load_project` / `prepare`), `static/` (plain JS, no build step) |

## Rules for changes

* **Traceability (PR-1 to PR-3).** Every equation, curve and default cites an ID registered in
  `quickpue/sources.py`. Add a new ID there before using one, and add the equation to `EQUATIONS` in
  `quickpue/report.py` when it is user visible.
* **Defaults are assumptions.** A new default needs a `description` stating its basis in `schema.py`, or a
  `log.set(...)` rule in `sizing.py`, so it appears in the input register.
* **Units follow the field-name suffix:** `_kw`, `_kwh`, `_c`, `_k`, `_l_s`, `_pa`, `_m2`, `_m`, `_pct`.
  Internally flows are m3/s, heat kW, capacity rates kW/K.
* **Honest results (PR-5).** Unmet load, curve extrapolation, minimum-speed operation and capacity shortfall
  become warnings; never clip or hide them. The hourly energy ledger (`heat_in` vs `removed`) must close: any
  new heat source or sink must be added to both sides in `Engine._iterate`.
* **Do not tune to the reference cases.** DC_O1 / DC_S1 values are practice references, not ground truth.
  Where QuickPUE differs, report the cause in `docs/VALIDATION.md`; do not adjust defaults to match.
* **After engine, sizing or preset changes:** run `pytest`, regenerate `docs/VALIDATION_RESULTS.md`, and update
  `docs/VALIDATION.md` or `docs/DESIGN_DECISIONS.md` if a number or a choice changed.
* Engine code is vectorised over hours with numpy; avoid per-hour Python loops (target under 5 s per scenario).
* Web input editor: keep it a client of the package. It may call the loader, `prepare`, presets and the
  libraries, but engine, schema, sizing and preset code must not depend on it. The form is generated from the
  pydantic schema, so a new schema field appears without editor changes; add a hint in `static/js/form.js`
  only for special widgets. Run `pytest tests/test_webui.py` after changing it.
* Presets: shared defaults live in `quickpue/presets/_base_*.yaml`; every preset must still run from minimum
  input (`tests/test_system.py::test_every_preset_runs_from_minimum_input`).

## Writing style

No em dashes and no double dashes in code comments, docs or messages. Plain, specific engineering language.
Do not create .docx files unless asked.
