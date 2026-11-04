# QuickPUE v0.1: design decisions and defaults

The requirements (`docs/NEW_TOOL_REQUIREMENTS.md` v0.4) leave several items TBD and `docs/TEST_CASES.md`
raises four findings (R-1 to R-4). This page records what v0.1 implements so the choices can be confirmed or
changed. Every default is overridable per project and is listed in the input register when applied.

## Open questions (requirements Section 20)

| # | Question | v0.1 choice |
|-|-|-|
| 1 | D13 defaults per equipment type (11.6) | Implemented as proposed: FWU M2 + K-VSM + f_min 0.3 + R-ALL; CDU pumps M3 + K-CONST; loop pumps M2 + K-DP(0.3) + f_min 0.3; integral chiller pumps M2 + K-DP(0.3), f_min 0.5 in presets, running on all duty units (R-ALL); dry cooler / tower / free-cooling fans M5 + K-CUBE + f_min 0.2; CRAH / FCU fans M2 + K-VSM; CRAC / VRF fans M3 + K-CONST; OAF / EAF constant |
| 2 | FWU curve without vendor data | K-VSM |
| 3 | D12 default loop arrangement | DT-A blending (LC-ACC-IFC-DUAL preset). DT-B, DT-C and DT-D are available per loop |
| 4 | M4 server airflow method | Available (`part_load.method: M4`, `server_airflow_l_s_per_kw`, `bypass_fraction`); M2 is the default |
| 5 | D8 acceptance | Not addressed (not blocking) |
| 6 | Auto-sizing rules and fan pressure rises | 8.4.2 rules as proposed. Pressure rises: FWU 500 Pa, CRAH 400 Pa, FCU 300 Pa, dry cooler 150 Pa. Chillers N = 4 + 1, rated COP 4.0 air cooled / 6.5 water cooled at the loop supply and design ambient (or 29.4 C ECW). CDU default 1,500 kW net. FWUs N + 1 per hall on coil load including fan heat. Dry coolers max(2, ceil(Q / 1,500 kW)) + 1, towers max(2, ceil(Q / 3,000 kW)) + 1. Room units: 1.1 x load. Zone areas 0.02 m2 per kW of IT when omitted. Hall areas from 2.5 kW/m2 when omitted |
| 7 | Output set contents | As proposed in 13.2, plus a `full` set. Output sets are YAML in `quickpue/output_sets/` |

## Test-case findings (TEST_CASES Section 5) and open items (Section 6)

| ID | Finding | v0.1 implementation |
|-|-|-|
| R-1 | Recirculation added after the pads in DC_O1 | `recirculation_order: after_pads` (default) or `before_pads` per chiller and dry cooler |
| R-2 | UPS loss `P_out (1 - eta)` in the sources | `electrical.loss_convention: physical` (default, `P_out (1/eta - 1)`) or `simplified`; per-UPS override |
| R-3 | Transformer / switchboard loss basis | Per element `basis`: `facility` (default), `it`, `it_path`, `mechanical`, `infrastructure`; transformers also `no_load_load` |
| R-4 | Linear CDU pumps, square-law integral pumps with 70 % floor | Expressed with M1 + K-LIN and M6 + K-SQUARE (new library entry) + f_min 0.7 |
| Open 3 | Reproduce source conventions or use physical defaults | The tool defaults to physical conventions; `tests/cases/dc_o1.yaml` switches to the source conventions to reproduce the reference |

## Other choices made during implementation

* **Annual PUE** is energy weighted; hourly PUE spreads annual-only diesel evenly (`settings.annual_items_hourly`).
* **Contingency** applies to gross infrastructure electricity before the PV credit (`contingency.basis: gross`),
  which matches the reference practice (O-09); `net_of_pv` follows the requirements 10.12 formula literally.
* **Adiabatic activation** is `T_db > activation` by default; `activation_inclusive: true` gives `>=`. The
  strict form reproduces the 157 h of O-11 (three EPW hours are exactly 31.0 C).
* **Integrated free cooling** coils are rated by one point (default 50 % of chiller capacity at 10 K return
  minus air) and use the dry-cooler effectiveness-NTU model. In partial mode the condenser air is preheated by
  the free-cooling coil heat, and fans of units running compressors are counted inside the chiller EIR.
* **Chiller library curves** are normalised to the project rated point by shifting the curve inputs by the
  difference between the project and library rating temperatures, then clamped to the curve limits as
  EnergyPlus does (S-EQ-23). Default analogues: `EP-ACC-SCROLL-434` (air cooled; widest ambient range and a
  part-load curve) and `EP-WCC-CENT-VSD-1495` (water cooled).
* **CP-5 / CP-6** use air-cooled trim chillers in series behind the dry coolers. DCOPTEST Type 11 shares the dry
  cooler between the economiser and the condenser; this is noted in the preset.
* **Cooling towers** use an effectiveness-NTU model with the effective saturated-air specific heat (EnergyPlus
  simple tower formulation) and UA modifiers `f^0.6` (air) and `(m_w / m_w,des)^0.4` (water), not the full
  Merkel variable-speed object with its curve set.
* **Discrete limit cycles**: in a few hours the equipment count flips between states (no fixed point exists).
  These hours are detected (periods 2 to 4), reported separately from non-convergence, and the last state is
  kept. The difference is usually below 1 % of that hour's infrastructure power.
* **Glycol**: presets with outdoor water coils (free cooling, dry coolers) use PG 25 %; a warning is raised when
  a water loop sees outdoor air within 1 K of its freezing point.
* **Lifts** use `trips * P * t / 3600 * 0.75 + standby`, an approximation of the GBCA method that reproduces
  O-08 within 0.3 %. The exact GBCA formula was not available.
* **Office profiles**: the NCC Class 5 table is not bundled; `office_simple` is a stated assumption. Custom
  24 h weekday / weekend profiles or 8,760 h CSV profiles can be supplied.
* **PV**: annual yield distributed by EPW global horizontal irradiance (or an hourly CSV). PVWatts is not built in.
