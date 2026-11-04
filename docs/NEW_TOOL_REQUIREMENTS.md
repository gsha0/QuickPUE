# Rapid Data Center Energy and PUE Estimator: Requirements and Product Design

Working title: **QuickPUE** (placeholder name)

Status: Draft v0.4, requirements and product design only (no code yet)
Date: 2026-11-04

A generic, adaptable engineering tool for data centre cooling and electrical infrastructure energy. It serves several workflows (for example NABERS design-stage estimates, LEED early-stage energy analysis, SSDA greenhouse gas estimation and engineering design checks) without being tied to any one of them.

## Change log

| Version | Change |
|-|-|
| v0.1 | First draft: findings from DCOPTEST and [KO26]; inputs, dropdowns, calculations, outputs. |
| v0.2 | Decisions D1 to D5. NABERS Infrastructure rating as primary use case. Python engine first. Equipment by unique type. Electrical losses, other end uses, supporting rooms and room units. Annual 8,760 h with hourly reporting. NABERS outputs. |
| v0.3 | IES VE removed from scope: the tool stands on its own as a transparent engineering calculator; equivalence is demonstrated against EnergyPlus only. Formal NABERS acceptance recorded as TBD. Back-testing against past projects deferred. Fan and pump inputs are design absorbed power per unit × quantity, with PLR and part-load curves applicable to every fan and pump; part-load curve library sourced from the EnergyPlus documentation; PLR calculation methods proposed (Section 11). Liquid fraction redefined as the share of IT heat captured by liquid (φ removed). Multi-temperature loop arrangements described and confirmed modelable (Section 12), default TBD. Input files YAML or Python. Equation and data source register added (Section 15). |
| v0.4 | Tool reframed as **generic and adaptable**: NABERS is one workflow alongside LEED early-stage analysis, SSDA GHG estimation and engineering design checks. Emissions-ratio PUE and star ratings removed; GHG is an optional energy × user factor output. Every equipment type (not only fans and pumps) supports PLR and a part-load curve (Section 11.1). Supporting room cooling loads are driven by electrical loss heat gains. UC-6 added: 8,760 h IT load profile input with corresponding hourly energy. Topology presets with default parameters and a minimum-input mode added (Section 8.4), covering the DCOPTEST topologies. Output table sets made workflow adaptable (Section 13.2). |

## Sources reviewed

1. This repository (DCOPTEST): `README.md`, `master_run.py`, `Run_Type10_3A.py`, `unit_test.py`, `it_profile.csv`, `test_data/ref_arch1_24h.csv`, and the parameter set inside `Model/DataCenterFMU.fmu` (`modelDescription.xml`, 3,471 variables, Dymola 2026x export).
2. Ko, Sur, Napier, Díaz-Marín, Jain, *Modeling Liquid-Cooled Data Centers in EnergyPlus*, arXiv:2610.33148v1 (23 Oct 2026). Referred to as **[KO26]**.
3. *NABERS Energy for Data Centres: Infrastructure Rating, Design-Stage Assessment* knowledge base (user supplied). Used as a reference for one application workflow and as a source of practical defaults (end-use categories, loss allowances, internal loads, infiltration, room unit practice). Referred to as **[NKB]**.
4. EnergyPlus documentation source, `NREL/EnergyPlus` GitHub repository, `develop` branch, commit `c068bdb` (2026-10-29). Referred to as **[EP-IO]** (Input Output Reference, `doc/input-output-reference/src/overview/group-fans.tex`, `group-pumps.tex`, `group-condenser-equipment.tex`) and **[EP-ER]** (Engineering Reference, `doc/engineering-reference/src/simulation-models-encyclopedic-reference-003/pumps.tex`, `...-002/air-system-fans.tex`, `cooling-towers-and-evaporative-fluid-coolers.tex`). The rendered site (bigladdersoftware.com) is blocked in this environment, so the LaTeX source was read directly.

## Table of Contents

1. [Purpose, Principles and Decisions](#1-purpose-principles-and-decisions)
2. [Findings from DCOPTEST](#2-findings-from-dcoptest)
3. [Findings from the EnergyPlus Liquid Cooling Paper](#3-findings-from-the-energyplus-liquid-cooling-paper)
4. [Findings from the NABERS Methodology](#4-findings-from-the-nabers-methodology)
5. [Engine Architecture and Equivalence Strategy](#5-engine-architecture-and-equivalence-strategy)
6. [Capability Coverage](#6-capability-coverage)
7. [Interface and Input File Design](#7-interface-and-input-file-design)
8. [System Type Catalogs](#8-system-type-catalogs)
9. [Input Requirements](#9-input-requirements)
10. [Calculation Requirements](#10-calculation-requirements)
11. [Fans and Pumps: PLR and Part-Load Curves](#11-fans-and-pumps-plr-and-part-load-curves)
12. [Loops at Different Temperatures](#12-loops-at-different-temperatures)
13. [Output and Reporting Requirements](#13-output-and-reporting-requirements)
14. [Verification and Equivalence Plan](#14-verification-and-equivalence-plan)
15. [Equation and Data Source Register](#15-equation-and-data-source-register)
16. [Non-Functional Requirements](#16-non-functional-requirements)
17. [Mapping: DCOPTEST to the New Tool](#17-mapping-dcoptest-to-the-new-tool)
18. [Phased Delivery Plan](#18-phased-delivery-plan)
19. [Risks](#19-risks)
20. [Open Questions](#20-open-questions)
21. [Glossary](#21-glossary)

## 1. Purpose, Principles and Decisions

### 1.1 Problem

Data centre energy and PUE estimates are needed at many points in a project: NABERS design-stage estimates, LEED early-stage energy analysis, SSDA greenhouse gas estimates, and routine engineering design checks (plant selection, part-load behaviour, free cooling hours, peak power). Today each of these is usually produced with a full dynamic energy model plus manual spreadsheets for electrical losses and other end uses. Building, checking and re-running such a model for each design change and each IT load case takes days, and most of the effort goes into geometry, zoning and HVAC network set-up that have little effect on data centre energy ([NKB]: fabric has negligible impact; IT load dominates).

### 1.2 Goal

A **generic, standalone Python engineering tool** that takes **equipment schedule level inputs** (unique equipment types with quantities, design absorbed powers, capacities, temperatures, part-load curves), or only a topology preset plus a few key inputs (Section 8.4), and a weather file. It simulates **8,760 hours** for each IT load scenario or hourly IT profile and produces annual and hourly energy by end use, PUE, water use, optional GHG, and equipment level detail, with **90 percent or more of the capability of a detailed energy model** for data centre infrastructure energy (Section 6). Workflow-specific outputs (NABERS, LEED, SSDA, design check) are adaptable output sets on top of one engine (Section 13.2).

### 1.3 Principles

| ID | Principle |
|-|-|
| PR-1 | **Solid physics**: every quantity comes from a stated energy balance, heat transfer relation or documented performance curve. No hidden tuning factors. |
| PR-2 | **Clear inputs and assumptions**: every input has a unit, a default (if any) with its basis, and a source attribution (Section 7.2). |
| PR-3 | **Traceable equations**: every equation used is listed with its source (Section 15) and can be printed for any result. |
| PR-4 | **Standalone**: no dependency on any commercial simulation package. EnergyPlus is used only as an independent reference for verification. |
| PR-5 | **Honest results**: unmet loads, curve extrapolation and assumptions are reported, never hidden. |
| PR-6 | **Generic but adaptable**: one engine and one input schema; workflow needs (NABERS, LEED, SSDA, design check) are met by presets, defaults and output sets, never by workflow-specific physics. |
| PR-7 | **Minimum input to first result**: a topology preset, IT load and liquid fraction are enough to run; every default is visible and replaceable. |

### 1.4 Decisions recorded

| ID | Decision | Source |
|-|-|-|
| D1 | Python engine first, physically robust. Results must be shown equivalent to EnergyPlus for matching inputs. | User |
| D2 | Delivery as Python code (library + CLI). No GUI in v1. | User |
| D3 | Each unique equipment type has its own inputs. Fans and pumps are entered as **design absorbed power per unit × quantity**. **Every equipment type is capable of a PLR and a part-load curve** (fans, pumps, chillers, CDUs, dry coolers, towers, room units, UPS, transformers; Section 11.1). Per loop: one primary pump type and one secondary pump type; one pump power per CDU type; one fan power per FWU type. | User |
| D4 | PUE includes electrical losses and other end uses entered by the user ([NKB] categories as the default list). | User |
| D5 | Annual 8,760 h simulation with hourly reporting in v1. | User |
| D6 | The tool is **generic**: NABERS, LEED early-stage analysis, SSDA GHG estimation and engineering design checks are application workflows, none of them primary. Supporting rooms and their cooling units are in scope; their cooling loads are driven mainly by the heat gains from the electrical losses defined in the electrical section (Section 10.9, 10.10). | User, 2026-11-04 |
| D7 | IES VE is not relevant to this tool. No IES comparison or IES specific curves. | User, 2026-11-03 |
| D8 | Formal acceptance of the tool for any regulatory submission: **TBD**. Design does not depend on it. | User |
| D9 | Back-testing against past projects: **deferred**. Focus is the physics foundation. | User |
| D10 | Input files are YAML or Python. No Excel input. | User |
| D11 | **Liquid fraction** is a key input and means the share of IT heat captured by liquid. The remainder goes to air. | User |
| D12 | Multiple loops at different temperatures are modelled (Section 12); default arrangement **TBD**. | User |
| D13 | PLR for fans and pumps derives from IT load through the served heat load; final default method **TBD** from the options in Section 11.4. | User |
| D14 | No emissions-ratio PUE and no star ratings or thresholds in the tool. PUE is an energy ratio. GHG is an optional output (energy × user supplied factors) for workflows such as SSDA. | User, 2026-11-04 |
| D15 | Topology presets with default parameters (including the DCOPTEST topologies). The tool runs with minimum input after a topology is selected and key information (IT load, liquid fraction, location) is given. | User, 2026-11-04 |
| D16 | Scheduled IT load: an 8,760 h IT load profile is a first-class input and produces corresponding hourly energy (UC-6). | User, 2026-11-04 |

### 1.5 Use cases

| ID | Use case | Notes |
|-|-|-|
| UC-1 | Design-stage PUE at IT load levels | e.g. 90 / 75 / 50 / 25 percent flat loads; the NABERS-style scenario set is one preset |
| UC-2 | Design option comparison | e.g. dry vs adiabatic, CHW temperatures, fan selections, reset strategies |
| UC-3 | Sensitivity and risk | Contingency, recirculation correction, curve uncertainty, low occupancy |
| UC-4 | Climate screening | Same design across many EPW files |
| UC-5 | Peak PUE and peak power | Worst hour at design load and at lowest load, with ambient condition stated |
| UC-6 | Scheduled IT load | Take an 8,760 h IT load profile (kW or fraction of installed, per hall type or total) and produce the corresponding hourly and annual energy, PUE and end uses |
| UC-7 | Quick topology screening | Preset topology + IT load + liquid fraction + location only (Section 8.4); defaults flagged as assumptions |
| UC-8 | Workflow outputs | NABERS design-stage estimate, LEED early-stage energy analysis, SSDA GHG estimate, engineering design check, each as an adaptable output set (Section 13.2) |

## 2. Findings from DCOPTEST

### 2.1 What DCOPTEST is

DCOPTEST is a Python batch driver around a single compiled Modelica FMU (`DataCenterFMU.fmu`, FMI 2.0 co-simulation, Dymola with the LBNL Buildings library). It simulates **12 fixed topologies** (Types 1 to 6 air cooled, Types 7 to 12 liquid cooled) across **19 ASHRAE climate zones** at a 1 hour step for 8,760 hours, and reports PUE, WUE, CUE, operating modes and ASHRAE thermal compliance.

| DCOPTEST Type | Medium | Chiller | WSE | Wet tower | Dry cooler | CHW | AHU | CDU |
|-|-|-|-|-|-|-|-|-|
| 7 | Liquid | | X | X | | X | | X |
| 8 | Liquid | X | X | X | | X | | X |
| 9 | Liquid | X | | X | | X | | X |
| 10 | Liquid | | X | | X | X | | X |
| 11 | Liquid | X | X | | X | X | | X |
| 12 | Liquid | X | | | X | X | | X |

Types 1 to 6 are the same plants serving an AHU instead of a CDU.

The new tool provides the same kind of ready-made topologies, as presets with default parameters (Section 8.4): selecting a topology and giving IT load, liquid fraction and location is enough to run. Unlike DCOPTEST, every preset default is visible, attributed and replaceable, and sizing scales with the IT load instead of being fixed at 500 kW.

### 2.2 Knowledge worth carrying forward

1. **Topology taxonomy** underpinning the plant catalog and the presets (Section 8).
2. **KPI set**: PUE, WUE, CUE, mode hours, ASHRAE W and A class compliance.
3. **Mode classification** from chiller and WSE states, extended with adiabatic modes.
4. **Condenser water reset**: `T_wb + 3 K` (wet) or `T_db + 3 K` (dry), clamped 12.78 to 23.89 °C, range 3 K.
5. **Psychrometrics and WUE**: Tetens saturation pressure, enthalpy based evaporation with exit air saturated at `T_wb + 3 K`, COC 5, drift. Stull wet bulb as fallback.
6. **Chiller model form**: DOE-2 `CAPFT`, `EIRFT`, `EIRFPLR` (FMU reference COP 8.0, `PLRMin` 0.08), identical in form to EnergyPlus `Chiller:Electric:EIR`.
7. **Engineering hygiene**: golden reference regression tests with per-variable tolerances, error log, parallel batch runs, vector KPI plots.
8. **Climate library**: the 19 ASHRAE zone locations as a default EPW set.

### 2.3 Limitations observed

Items marked *(verify)* are inferred from FMU parameter values.

| # | Observation | Evidence | Impact | New tool requirement |
|-|-|-|-|-|
| L1 | Sizing compiled in: 500 kW IT, room 50 m × 30 m × 3 m, one 1,104 kW chiller | `roo.QRoo_flow`, `roo.rooLen/rooWid/rooHei`, `chi.per.QEva_flow_nominal` | Cannot model a real project | All sizing is input |
| L2 | Air and liquid paths mutually exclusive | `master_run.py` sets `ITAir = 0` for liquid Types | Residual air load and FWU fans missing | Liquid fraction per hall type (D11) |
| L3 | Fixed flow pumps and dry cooler fans | Reference run: CW pump constant 65.5 kg/s, **48.0 kW** all day; CHW pump constant head 130 kPa (7.3 kW); CDU pump 15 kg/s; DCT fan 49.75 kg/s *(verify)* | Part load PUE overstated | PLR and curves for all fans and pumps (Section 11) |
| L4 | Generic efficiencies | Hydraulic 0.7 × motor 0.7 = 0.49 | Not traceable | Absorbed power from schedules (D3) |
| L5 | One chiller, no staging, no redundancy | Single `chi` | PLR ≤ 0.45 at full IT | Unique chiller types, quantity, staging |
| L6 | PUE excludes electrical and other losses | `PUE = 1 + PHVAC / PIT` | Only a cooling pPUE, not a facility PUE | Full end-use set (D4) |
| L7 | WUE constants differ | Python drift 0.0002; FMU `Drift = 0.001`, `Eva_Factor = 0.85` | Not reproducible | One documented water model |
| L8 | Missing plant | No air-cooled chillers, integrated free cooling or adiabatic | Most used plants absent | Section 8 catalog |
| L9 | Temperature range capped | CW clamp 12.78 to 23.89 °C; CDU 27 °C fixed | No elevated CHW or W40 / W45 | User setpoints and resets |
| L10 | Ideal CDU heat exchanger | `CDU.heatExchanger_TSet.eta = 1` *(verify)* | No approach | CDU approach input |
| L11 | Tooling friction | FMU binaries per OS, DASSL, solver failures | Slow, opaque | Closed-form quasi-steady engine |
| L12 | Supporting rooms absent | Single room volume | Room units and their losses missing | Supporting zones and room units |

Magnitude check from the Type 1 reference run: AHU fan 55 to 73 kW and CW pump 48 kW at roughly 240 to 270 kW IT give PUE 1.22 to 1.26 with no chiller running. Fan and pump part-load behaviour dominates PUE once free cooling is available.

## 3. Findings from the EnergyPlus Liquid Cooling Paper

### 3.1 Summary of [KO26]

* Adds `ElectricEquipment:ITE:LiquidCooled` to EnergyPlus (26.1 field set). Source: `github.com/Urban-Informatics-Lab/energyplus-liquid-cooling`.
* The object sits on the demand side of the facility water (FWS) plant loop, so standard EnergyPlus plant rejects the liquid heat.
* The liquid path is quasi-steady and algebraic. Validated against an independent Modelica model over 21 conditions; loop temperature RMSE ≤ 0.021 K.

### 3.2 Equations adopted (with [KO26] numbering)

[KO26] splits CPU power with an air leakage fraction φ. Under D11 the tool uses the liquid heat fraction `f_liq` directly; for a fully liquid-cooled rack population `f_liq = 1 - φ`.

```
Eq 1   Q_liq      = f_liq · P_IT              ([KO26]: (1 - φ) · P_cpu)
       Q_air      = (1 - f_liq) · P_IT + Q_ups,loss,zone
Eq 2   m_fws      = ρ_fws(T_fws,sup,des) · V_fws
Eq 3   T_fws,ret  = T_fws,sup + Q_liq / (m_fws · cp_fws)
Eq 4   T_rack,sup = T_fws,sup + ΔT_approach
Eq 5   m_rack     = ρ_rack(T_rack,sup,des) · V_rack
Eq 6   T_rack,ret = T_rack,sup + Q_liq / (m_rack · cp_rack)
Eq 7   ΔT_lm      = (ΔT1 - ΔT2) / ln(ΔT1 / ΔT2)
Eq 8   ΔT1 = T_rack,ret - T_fws,ret ;  ΔT2 = T_rack,sup - T_fws,sup
Eq 9   T_junc     = T_rack,sup + (Q_liq / N_units) · R_th
Eq 10  PUE        = E_facility / E_IT
Eq 11  WUE        = V_w / E_IT
Eq 12  EUE        = (E_compute + E_reused) / E_facility
```

### 3.3 Published benchmark ([KO26] Table 4 and Section 5)

| Parameter | Chilled water (W17) | Warm water (W45) |
|-|-|-|
| Data hall floor area | 557.42 m² | same |
| IT power density | 3,844.69 W/m² | same |
| Peak IT power | 2,143.10 kW | same |
| Rack units | 71 | same |
| UPS efficiency | 0.94 | same |
| FWS flow | 0.097 m³/s | same |
| CDU approach | 2.0 K | same |
| FWS supply | 12.0 °C | 45.0 °C |
| Rack coolant supply | 14.0 °C | 47.0 °C |
| Liquid heat rejection | 2.5 MW water-cooled chiller (COP 5.5) + wet tower | 3.0 MW dry cooler |
| Air leakage φ (so `f_liq` = 0.80) | 0.20 | 0.20 |
| Room air system | CRAH fan coil, 18 °C supply, main CHW loop | CRAH on a dedicated air-cooled chiller (COP 3.2) at 8 °C |
| Lighting | 6.89 W/m² | same |
| Weather / schedule | Tampa FL TMY3; quarterly IT steps 0.25 to 1.00 | same |

Published annual PUE: 1.43 (air-cooled baseline), 1.31 (W17), 1.25 (W45). Peak PUE 1.68 / 1.50 / 1.48. WUE 3.45 / 2.46 / 0 L/kWh.

### 3.4 Lessons

1. **Quasi-steady is sufficient for annual PUE**; differences against a dynamic model only appear in 1 minute load-step transients.
2. **The liquid / air split is the key hybrid parameter**; the residual air load and how it is cooled matter.
3. **Warm water is not always better**: W45 exceeded W17 hourly PUE for 785 h, all at 25 percent IT in cool dry weather. Reduced IT load cases must be simulated, not scaled.
4. **Fixed CDU approach over-predicts approach at part load**; scale with load.
5. **Plant feasibility must be checked**: a dry cooler cannot hold 32 °C supply in Tampa summer. Report unmet hours.

## 4. Findings from the NABERS Methodology

NABERS is one of several workflows the tool serves. [NKB] is used as a reference for that workflow and as a source of practical defaults; nothing in the engine is NABERS specific. Emissions-ratio PUE and star ratings are out of scope (D14).

### 4.1 Practices the tool supports (generic form)

| Area | [NKB] practice | Consequence for this tool |
|-|-|-|
| Metric | Annual PUE; diesel reported separately from electricity | PUE as energy ratio; diesel in its own columns; optional GHG with user factors (D14) |
| IT load | Flat 8,760 h; base case 90 percent of installed IT; off-axis 75 / 50 / 25 percent | One scenario preset among others; hourly profiles also supported (UC-6) |
| Peak PUE | Worst ratio (lowest load) and worst instantaneous at design load (high ambient); state ambient | Both reported with conditions |
| Weather | TMY EPW, nearest representative station; monthly summary table | EPW reader and summary table |
| Geometry and fabric | Negligible PUE impact; concrete U about 1.1 to 1.4 W/m²K | Box per zone with UA |
| Infiltration | 0 ACH pressurised critical areas; 0.7 ACH zones without mechanical OA; 0.35 ACH others | Per zone defaults |
| Internal loads | Lighting 5 W/m²; 100 m²/person; 70 W sensible / 60 W latent; profile 5 percent (00:00 to 08:00, 18:00 to 24:00), 15 percent (08:00 to 18:00) | Defaults and profile library |
| Air-cooled chillers | CAPFT / EIRFT / EIRFPLR anchored to project CHW temperatures (often 24 to 28 °C supply); condenser inlet recirculation correction (+2.7 to +5 °C) in dry and adiabatic modes; integrated free cooling; adiabatic pads (activation DB, efficiency, hours, energy reduction often 2 to 3 percent); CHW reset with ambient; staging to minimum duty count; integral CHW pump with minimum flow | All required |
| CHW loops | Often dual: medium temperature (about 24 / 34 °C) to FWUs; high temperature (about 26 / 36 °C) to CDUs and water-cooled CRAC / PAC; or single elevated loop (about 28 / 38 °C) | Section 12 |
| CDUs | Load set by IT; liquid fraction 60 to 90 percent; pump usually fixed absorbed power; pump heat to secondary loop; installed vs active count | Required |
| FWUs | EC fans, VSD, minimum turndown 30 percent; air-side fraction per hall type; containment; cold aisle setpoint | Required, curves from Section 11 |
| Room units | CRAH (CHW), CRAC (DX, dedicated condenser), PAC (water-cooled), VRF / split; assumed COP 3.0 when vendor data absent | Supporting zones and room unit types |
| Redundancy | 2N active rooms: both sides on load 8,760 h; 0.5N+0.5N both on load; derate only genuine standby | Redundancy modes per type |
| Ventilation | OAF / EAF / filtration constant flow and power; DX dehumidifiers to hold RH below a limit; battery room EAF continuous | Required |
| Electrical losses | UPS (curve 25 to 100 percent in 5 percent steps; IT path and mechanical path), transformers (HV 0.5 to 0.8 percent, MV/LV 1.0 percent, or vendor data), distribution 1 percent of infrastructure electricity; heat gains to rooms | Electrical loss chain with heat allocation |
| Other end uses | Generator test diesel (Format A or B), jacket heaters (EFLH from EPW ramp), ancillary, DHW, lifts (GBCA method), PV credit | Required |
| Contingency | 2.5 to 10 percent of infrastructure energy, own line, before PUE | Required |
| Metering | Point A (rack) or Point B (PDU input, 3 percent PDU loss deduction); exclusions | Boundary flags per end use |
| Attribution | Document-stated, inference, designer-confirmed, assumption, "pending manufacturer confirmation" | Source metadata on every input |
| Outputs | Scenario summaries, granular or coarse end-use table with diesel columns, pie chart, input overview, weather tables, UPS table, equipment tables | NABERS-style output set (Section 13.2) |

### 4.2 Implications

1. The parts of a detailed data centre model that drive energy and PUE are **plant performance, part-load behaviour, losses and their heat gains, and room units**. All are equipment-schedule data the tool takes directly.
2. Geometry, fabric, shading and office zoning are simplified; [NKB] states their PUE impact is negligible.
3. Electrical loss heat gains create a coupling (losses heat rooms, rooms need cooling, cooling consumes power, power creates losses). The engine iterates this loop (Section 10.2).

## 5. Engine Architecture and Equivalence Strategy

### 5.1 Architecture

* **Core engine (Python)**: quasi-steady, hourly, physics based, deterministic. Hours are independent (no thermal storage), so the 8,760 hours are solved as vectors with a per-hour fixed-point iteration. Target under 5 s per scenario.
* **Reference exporter (EnergyPlus)**: generates an EnergyPlus model from the same input file. Used to demonstrate equivalence (D1). Built alongside the engine because it is the verification instrument.

### 5.2 Why quasi-steady physics is sufficient and robust

* [KO26] shows an algebraic liquid loop reproduces a dynamic Modelica model to within 0.03 K except during load-step transients.
* Data centre runs use flat or hourly IT load and hourly weather; plant controls hold setpoints. Envelope gains, the only part affected by thermal mass, are a negligible share of load.
* Robustness: closed-form or bracketed (bisection / Brent) solutions for every unknown, explicit capacity limits, explicit unmet load accounting, hourly energy balance checks, and no stiff ODE solver (removes DCOPTEST failure class L11).

### 5.3 Equivalence strategy (D1)

| Level | Reference | Purpose |
|-|-|-|
| Component | Analytical solution and EnergyPlus component objects | Each model reproduces the reference equations |
| System, annual | EnergyPlus model auto-generated from the same input | Integrated plant, controls and loss coupling give the same annual and hourly results |

Where EnergyPlus has no native object for a feature (Section 5.4), the reference model uses EnergyPlus EMS to implement the same documented equation, and the comparison is labelled accordingly. Acceptance targets are in Section 14.

### 5.4 EnergyPlus mapping and known gaps

| Tool element | EnergyPlus object(s) | Gap and handling |
|-|-|-|
| Liquid cooled IT | `ElectricEquipment:ITE:LiquidCooled` ([KO26]) | Confirm availability in the official release; fallback `LoadProfile:Plant` on the loop plus `ElectricEquipment` zone gain for the air share |
| Air cooled IT and losses as gains | `ElectricEquipment:ITE:AirCooled`, `ElectricEquipment`, `OtherEquipment` | None |
| Air-cooled chiller | `Chiller:Electric:EIR` | Recirculation correction via EMS on condenser inlet |
| Integrated free cooling chiller | `HeatExchanger:FluidToFluid` + `FluidCooler` + chiller in series, EMS for fan sharing | Fan sharing via EMS |
| Adiabatic pads | No native object | EMS adjusts condenser entering air temperature |
| Variable speed dry cooler | `FluidCooler:SingleSpeed` / `TwoSpeed` only | EMS fan power, or `CoolingTower:VariableSpeed:Merkel` structure |
| Cooling tower | `CoolingTower:VariableSpeed:Merkel` | None |
| Pumps | `Pump:VariableSpeed` (cubic part-load curve), `Pump:ConstantSpeed`, `HeaderedPumps:*` (sequential loading) | Equal-speed parallel operation needs individual pumps or EMS |
| Fans (FWU, CRAH, CRAC) | `Fan:SystemModel` (curve of flow fraction), `ZoneHVAC:FourPipeFanCoil` | None |
| CRAC / VRF / split DX | `ZoneHVAC:PackagedTerminalAirConditioner`, `AirConditioner:VariableRefrigerantFlow`, `Coil:Cooling:DX:SingleSpeed` | None |
| PAC (water-cooled) | `Coil:Cooling:WaterToAirHeatPump:EquationFit` on the loop | None |
| Loops at different temperatures | Separate `PlantLoop`s, `HeatExchanger:FluidToFluid`, common pipe | Blending arrangement (Section 12) needs a tertiary loop or EMS |
| Electrical losses | Computed outside the HVAC solution in both engines and applied as zone gains | Same equations both sides |

## 6. Capability Coverage

Target: **90 percent or more** of the capability of a detailed whole-building energy model for data centre PUE, weighted by typical share of infrastructure energy.

| Capability | Typical share of infrastructure energy | Coverage | Section |
|-|-|-|-|
| Chiller plant (curves, staging, reset, free cooling, adiabatic, recirculation) | 25 to 45 percent | Full | 10.6, 10.7 |
| CHW / FWS / CW pumps, integral chiller pumps | 3 to 8 percent | Full | 11 |
| CDU pumps | 2 to 6 percent | Full | 10.4, 11 |
| FWU fans | 5 to 15 percent | Full | 11 |
| Room units, ventilation, dehumidifiers | 3 to 10 percent | Full at unit level; zone simplified to box | 10.9 |
| UPS, transformer, distribution, PDU losses | 20 to 40 percent | Full | 10.10 |
| Heat gains from losses into rooms | Coupled | Full (iterated) | 10.2 |
| Generator diesel, jacket heaters | 1 to 3 percent | Full | 10.11 |
| Lighting, ancillary, lifts, DHW, PV | 1 to 3 percent | Full (calculation or direct input) | 10.11 |
| Contingency | 2.5 to 10 percent | Full | 10.12 |
| Envelope conduction | Under 1 percent | Simplified (box UA, steady state) | 10.9 |
| Solar gains, shading, glazing | Under 1 percent | Not modelled (optional roof sol-air term) | |
| Thermal mass, zone temperature float | Under 1 percent annually | Not modelled; setpoints held, unmet load reported | |
| Humidity and latent loads | Small | Simplified: OA latent, dehumidifier activation; coils dry at elevated CHW | 10.9 |
| Duct / pipe networks | Represented by absorbed power and part-load curves | Simplified | 11 |
| Sub-hourly controls, transients | Nil annually | Not modelled | |

Everything above about 1 percent of infrastructure energy is covered in full.

## 7. Interface and Input File Design

### 7.1 Interface (v1)

* REQ-UI-1: Python package (`quickpue`) with a documented API: `load_project(path)`, `run(project, scenarios)`, `export(results, formats)`, `explain(results, item, hour)`.
* REQ-UI-2: CLI: `quickpue run project.yaml`, `quickpue batch studies.py`, `quickpue export-eplus project.yaml`, `quickpue validate project.yaml`.
* REQ-UI-3: Inputs as YAML (data) or Python (scripted studies that build or vary a project object). Both validated against the same versioned schema (pydantic models).
* REQ-UI-4: System choices are enumerated `type` fields (Section 8). Invalid combinations fail validation with a clear message.
* REQ-UI-5: Topology presets (Section 8.4) and project templates for common configurations, including air-cooled chillers with integrated free cooling and adiabatic pads, dual CHW loops, CDUs, FWUs, CRAH / CRAC / PAC / VRF support rooms, the DCOPTEST topologies and the [KO26] cases.
* REQ-UI-6: Workflow output sets selectable at run time (Section 13.2): `-o nabers`, `-o leed`, `-o ssda`, `-o design-check`, or a user-defined set.

### 7.2 Source attribution on every input

* REQ-ATTR-1: Any input value may be written as a plain value or as `{value, unit, source}` with `source.kind` (document | inference | designer | assumption | pending_manufacturer) and `source.ref`.
* REQ-ATTR-2: Defaults applied by the tool are recorded as `kind: assumption` with the default's basis (Section 15).
* REQ-ATTR-3: Export an **input register** listing every input, value, unit and source, plus all `pending_manufacturer` and `assumption` items.

### 7.3 Equipment data model (D3)

| Entity | Unique type rule | Key links |
|-|-|-|
| Hall type | One entry per hall type, with count | Served by FWU and CDU types |
| Water loop | One entry per loop (e.g. CHW-MT, CHW-HT, FWS, CW) | Max one primary pump type and one secondary pump type |
| Chiller type | Any number | Serves loops; staging priority |
| Heat rejection type | Dry cooler, adiabatic dry cooler, cooling tower | Serves a loop or chiller group |
| CDU type | Any number; one pump power per type | Serves hall types; one loop |
| FWU type | Any number; one fan power per type | Serves hall types; one loop |
| Supporting zone type | One per room type, with count | Served by room unit types |
| Room unit type | CRAH, CRAC, PAC, VRF / split, FCU, dehumidifier, OAF, EAF, humidifier | Serves zone types; CRAH / PAC / FCU on a loop |
| Electrical element type | Transformer (HV, MV/LV), UPS system, PDU, distribution | Loss chain |
| Other end use | Generator set, lifts, DHW, ancillary, PV, office | Boundary flag |

* REQ-DM-1: Quantity as installed, duty and standby counts plus redundancy mode: `N+x` (standby off), `2N_active` (all energised, load shared), `0.5N+0.5N` (two groups on load).
* REQ-DM-2: Every fan and pump (FWU fans, CDU pumps, primary and secondary pumps, integral chiller pumps, dry cooler / tower / condenser fans, CRAH / CRAC / PAC / FCU fans, OAF / EAF) is entered as **design absorbed power per unit**, **design flow per unit**, **quantity**, and a **part-load model** (PLR method + curve + minimum, Section 11). Constant operation is a curve choice, not a separate model.
* REQ-DM-2b: Every other equipment type also carries a part-load model with a defined PLR and a curve (Section 11.1 table): chillers (EIRFPLR), CDUs (approach vs load, pump), dry coolers and towers (fan curve at solved speed), room units (COP vs PLR), UPS (efficiency vs load), transformers (no-load + load loss vs load²).
* REQ-DM-3: One unique type has one performance definition. Variation needs a second type.
* REQ-DM-4: All links validated: no orphan equipment, unserved zone or loop without a source.

## 8. System Type Catalogs

### 8.1 Water system arrangement (`water_system.type`)

| ID | Name | Description | Typical class |
|-|-|-|-|
| WS-1 | Single elevated loop | One loop serves FWUs, CDUs and water-cooled room units (e.g. 28 / 38 °C) | W27 to W32 |
| WS-2 | Multiple loops, common plant | e.g. medium temperature loop to FWUs (24 / 34 °C), high temperature loop to CDUs and PAC (26 / 36 °C), from the same chillers; arrangement per Section 12 | W27 to W32 |
| WS-3 | Multiple loops, dedicated plants | Each loop has its own chiller / heat rejection group | Any |
| WS-4 | Chilled water to all | Low temperature CHW to CDUs and FWUs | W17 |
| WS-5 | Warm loop to CDU, separate air plant | Warm FWS to CDUs; FWUs on their own chiller loop ([KO26] W45) | W40 to W45 |
| WS-6 | Air only | No CDU | Air baseline |

### 8.2 Cooling plant (`plant.type`)

| ID | Name | Free cooling path | DCOPTEST analogue |
|-|-|-|-|
| CP-1 | Air-cooled chillers | None | none |
| CP-2 | Air-cooled chillers with integrated free cooling (optional adiabatic pads) | Coil ahead of evaporator; full / partial / mechanical; adiabatic in mechanical modes | none |
| CP-3 | Dry coolers only | Always | Type 10 |
| CP-4 | Adiabatic dry coolers only | Dry, then adiabatic | none |
| CP-5 | Dry coolers + trim chillers | Full / partial / mechanical | Type 11 |
| CP-6 | Adiabatic dry coolers + trim chillers | Dry / adiabatic / partial / mechanical | none |
| CP-7 | Water-cooled chillers + towers + WSE | Full / partial / mechanical | Type 8 |
| CP-8 | Water-cooled chillers + towers | None | Type 9 |
| CP-9 | Towers + plate HX only | Always | Type 7 |
| CP-10 | Water-cooled chillers with dry cooler heat rejection | None | Type 12 |

### 8.3 Room unit types (`room_unit.type`)

| Type | Energy model | Heat path |
|-|-|-|
| CRAH | Fan (Section 11); coil load to connected loop | Loop |
| CRAC (DX, air-cooled condenser) | Compressor `Q / COP(T_amb, PLR)` + evaporator fan + condenser fan | Outdoors |
| PAC (water-cooled) | Compressor `Q / COP(T_loop, PLR)` + fan | `Q + P_comp` to connected loop |
| VRF / split | `Q / COP(T_amb, PLR)` + indoor fan | Outdoors |
| FCU / OA unit | Fan + coil on loop; OA sensible and latent load | Loop |
| DX dehumidifier | Fixed power when active | Zone |
| OAF / EAF / filtration | Fan (Section 11), usually constant | Zone / outdoors |
| Humidifier | Power when active | Zone |

### 8.4 Topology presets and minimum-input mode (D15)

A **topology preset** is a named combination of water system (8.1), cooling plant (8.2), equipment types and default parameters. With a preset the tool runs from the **minimum input set**:

| Minimum input | Example |
|-|-|
| Topology preset | `LC-ACC-IFC-AD` |
| Location (EPW) | Sydney TMY |
| Installed IT load | 10,000 kW |
| Liquid fraction | 0.8 |
| IT scenario or 8,760 h profile | 90 / 75 / 50 / 25 percent, or `it_profile.csv` |
| Data hall area and height (optional) | 4,000 m², 4.5 m; default from an IT density assumption if omitted |

Everything else is filled by the preset's defaults and auto-sizing rules, each recorded in the input register as `kind: assumption` with its basis. Any default can be overridden individually, so a project can move from minimum input to full equipment schedules gradually.

#### 8.4.1 Preset catalog (initial)

| Preset | Water system | Plant | Description | DCOPTEST |
|-|-|-|-|-|
| AIR-WCC-WSE | WS-6 | CP-7 | Air cooled, water-cooled chillers, towers, WSE | Type 2 |
| AIR-WCC | WS-6 | CP-8 | Air cooled, water-cooled chillers, towers | Type 3 |
| AIR-WSE | WS-6 | CP-9 | Air cooled, towers + WSE only | Type 1 |
| AIR-DC | WS-6 | CP-3 | Air cooled, dry coolers + WSE only | Type 4 |
| AIR-DC-CH | WS-6 | CP-5 | Air cooled, dry coolers + chillers | Type 5 |
| AIR-CH-DC | WS-6 | CP-10 | Air cooled, chillers with dry cooler heat rejection | Type 6 |
| LC-WSE | WS-1 | CP-9 | Liquid + air, towers + WSE only | Type 7 |
| LC-WCC-WSE | WS-1 | CP-7 | Liquid + air, water-cooled chillers, towers, WSE | Type 8 |
| LC-WCC | WS-1 | CP-8 | Liquid + air, water-cooled chillers, towers | Type 9 |
| LC-DC | WS-1 | CP-3 | Liquid + air, dry coolers only | Type 10 |
| LC-DC-CH | WS-1 | CP-5 | Liquid + air, dry coolers + chillers | Type 11 |
| LC-CH-DC | WS-1 | CP-10 | Liquid + air, chillers with dry cooler heat rejection | Type 12 |
| LC-ACC | WS-1 | CP-1 | Liquid + air, air-cooled chillers | new |
| LC-ACC-IFC | WS-1 | CP-2 | Liquid + air, air-cooled chillers with integrated free cooling | new |
| LC-ACC-IFC-AD | WS-1 | CP-2 + adiabatic | As above with adiabatic pads | new |
| LC-ACC-IFC-DUAL | WS-2 | CP-2 | Dual CHW loops (FWU loop, CDU / PAC loop) from common plant | new |
| LC-ADC-CH | WS-1 | CP-6 | Adiabatic dry coolers + trim chillers | new |
| LC-W45-DC | WS-5 | CP-3 + CP-1 | Warm loop on dry coolers to CDUs; FWUs on air-cooled chiller loop ([KO26] W45) | new |

Each preset ships with a default supporting-room set (optional in minimum-input mode) whose cooling load follows the electrical loss heat gains (Section 10.9).

#### 8.4.2 Default auto-sizing rules (proposed, to confirm)

Design cooling load `Q_des` is computed by the engine at the design ambient condition from installed IT, liquid fraction and the default losses and gains, then:

| Item | Default rule | Basis / source ID |
|-|-|-|
| Liquid / air split | `Q_liq = f_liq · P_IT`; air side gets the remainder plus gains | D11, S-EQ-01 |
| Chillers | N+1; N = 4 unless overridden; unit capacity = `Q_des / N`; curves from an EnergyPlus dataset analogue (`AirCooledChiller.idf`: 111 `Chiller:Electric:EIR` entries; `Chillers.idf`: 162 entries) or the DCOPTEST reference chiller, normalized to a rated COP input | S-EQ-03, S-DEF-01; rated COP is an assumption to replace |
| Pumps (all loops, CDU) | Flow from load and design ΔT; design power 348,701.1 W per m³/s (22 W/gpm), the EnergyPlus `PowerPerFlow` default | [EP-IO] Pump:VariableSpeed, S-DEF-02 |
| Fans (FWU, CRAH, dry cooler) | Airflow from load and design air ΔT; design power = 1.66667 W per (m³/s · Pa) × flow × pressure rise (EnergyPlus `Fan:SystemModel` `PowerPerFlowPerPressure` default, i.e. total efficiency 0.6) with a default pressure rise per fan type | [EP-IO] Fan:SystemModel, S-DEF-03; pressure rises are assumptions (Q6) |
| Redundancy | FWU N+1, CDU N+1, pumps N+1, dry coolers N+1 | Assumption |
| Part-load models | Section 11.6 defaults | Section 11 |
| CDU approach | 3 K at rated capacity | Assumption ([KO26] used 2 K, swept 4 to 10 K) |
| Dry cooler | Rated at design ambient with 5 K approach; UA back-calculated | Assumption |
| UPS | 0.94 flat or a default curve | [KO26] / [NKB] |
| Transformers, distribution | MV/LV 1.0 percent, HV 0.5 percent, distribution 1.0 percent | [NKB] |
| Lighting | 5 W/m², [NKB] data centre profile | [NKB] |
| Room units | CRAH on the loop, or DX with COP 3.0 | [NKB] |
| Contingency | 0 percent | Assumption |

* REQ-PRE-1: A preset run prints a one page "assumptions applied" list before results.
* REQ-PRE-2: Preset definitions are YAML files in the package; users can add their own presets.
* REQ-PRE-3: Auto-sized values are reported in the equipment tables like user inputs, flagged as auto-sized.

## 9. Input Requirements

All inputs accept source attribution (REQ-ATTR-1).

### 9.1 Project and workflow settings

| ID | Input | Notes |
|-|-|-|
| IN-P-1 | Project name, location text | |
| IN-P-2 | Energy boundary | Which end uses count as infrastructure, IT, or excluded (e.g. office); default per [NKB] categories |
| IN-P-3 | Workflow output set and reference documents | e.g. `nabers`, `leed`, `ssda`, `design-check`; reference document names and versions as free text stamped on outputs |
| IN-P-4 | GHG factors (optional) | Electricity (kg CO2-e/kWh) and diesel (kg CO2-e/L) supplied by the user for GHG outputs; no built-in factor tables (D14) |
| IN-P-5 | IT metering point | A (rack) or B (PDU input, PDU loss default 3 percent) |
| IN-P-6 | Designer's PUE estimate (optional) | Comparison only |

### 9.2 Weather

| ID | Input | Notes |
|-|-|-|
| IN-W-1 | EPW file | Station name, number, lat / lon, altitude, years from header |
| IN-W-2 | Distance to site | Reported |
| IN-W-3 | Design / extreme conditions | From EPW / STAT; capacity checks and peak framing |

### 9.3 IT and scenarios

| ID | Input | Notes |
|-|-|-|
| IN-IT-1 | Hall types | Name, count, design IT capacity per hall (kW), floor area, height, cold aisle setpoint |
| IN-IT-2 | **Liquid fraction** per hall type | Share of IT heat captured by liquid, 0 to 1 (D11). Remainder `1 - f_liq` is air-side heat. |
| IN-IT-3 | Scenarios | Flat load levels (preset: 90, 75, 50, 25 percent of installed IT, 8,760 h), and / or scheduled profiles (IN-IT-5) |
| IN-IT-5 | **8,760 h IT load profile** (UC-6, D16) | CSV with hourly IT load in kW or as a fraction of installed IT, for the total or per hall type; optional separate liquid fraction profile. Shorter series (e.g. one typical week or day) can be repeated to 8,760 h with an explicit flag. Timestamps aligned to the EPW year; leap day handling stated |
| IN-IT-4 | Junction check (optional) | `R_th`, `T_junc,max`, units per hall ([KO26] Eq. 9) |

### 9.4 Water loops

| ID | Input | Notes |
|-|-|-|
| IN-L-1 | Loop id, medium, glycol percent | Water, PG, EG |
| IN-L-2 | Design supply / return | e.g. 24 / 34 °C |
| IN-L-3 | Supply temperature reset | Fixed; ambient linear (low setpoint below `T_amb,1`, high above `T_amb,2`, linear between); load based |
| IN-L-4 | Connection to plant | Direct, blended, via HX, dedicated (Section 12) |
| IN-L-5 | Primary pump type (max 1) | Absorbed power per pump × quantity, design flow per pump, part-load model (Section 11) |
| IN-L-6 | Secondary pump type (max 1) | As IN-L-5 |

### 9.5 Chiller types

| ID | Input | Notes |
|-|-|-|
| IN-CH-1 | Type | Air-cooled; air-cooled with integrated free cooling; water-cooled |
| IN-CH-2 | Quantity, redundancy, loops served, staging priority | |
| IN-CH-3 | Rated point | Capacity (kWr), absorbed power (kW), CHW supply, entering condenser air / water temperature; COP derived |
| IN-CH-4 | Curves | (a) Manufacturer table at project CHW conditions fitted to CAPFT / EIRFT / EIRFPLR; (b) direct coefficients; (c) library analogue normalized to the rated point, flagged `pending_manufacturer` |
| IN-CH-5 | Curve validity ranges | LWT and ECT / ambient ranges |
| IN-CH-6 | Minimum PLR, cycling or false loading | |
| IN-CH-7 | Integral CHW pump | Absorbed power × 1 per chiller, design flow, part-load model, minimum flow |
| IN-CH-8 | Condenser inlet correction | +°C (CFD or designer); dry and adiabatic modes |
| IN-CH-9 | Integrated free cooling | Capacity vs (return minus ambient) ΔT; fan power at full speed; enable ΔT; glycol derate |
| IN-CH-10 | Adiabatic pads | Activation DB threshold, saturation efficiency, water model |
| IN-CH-11 | Staging logic | Minimum duty count (stage-up PLR, stage-down hysteresis) or all duty units share load |
| IN-CH-12 | Operating limits | Max ambient, LWT range, high-ambient derate |

### 9.6 Heat rejection types

| ID | Input | Notes |
|-|-|-|
| IN-HR-1 | Dry cooler | Quantity, rated capacity, rated water in / out and ambient, fan absorbed power per unit at full speed, fan curve and minimum speed (Section 11), control |
| IN-HR-2 | Adiabatic | Efficiency, activation logic, water model |
| IN-HR-3 | Cooling tower | Quantity, capacity, design WB, approach, range, fan power, fan curve, COC, drift, CW reset |
| IN-HR-4 | Plate HX (WSE) | Approach |
| IN-HR-5 | Recirculation correction | +°C on entering air |

### 9.7 CDU types

| ID | Input | Notes |
|-|-|-|
| IN-CDU-1 | Quantity installed, active in normal operation, redundancy | e.g. 60 installed, 30 active |
| IN-CDU-2 | Net capacity per CDU | |
| IN-CDU-3 | Pump absorbed power per CDU (one value per type), design TCS flow per CDU | |
| IN-CDU-4 | Pump part-load model | Default fixed ([NKB]); options per Section 11 |
| IN-CDU-5 | TCS supply setpoint, approach at rated capacity | |
| IN-CDU-6 | Connected loop, on mechanical UPS (yes / no) | |

### 9.8 FWU types

| ID | Input | Notes |
|-|-|-|
| IN-FWU-1 | Quantity, redundancy, hall types served | |
| IN-FWU-2 | Fan absorbed power per unit at design airflow (one value per type), design airflow per unit, total static pressure, coil capacity | |
| IN-FWU-3 | Fan part-load model | Section 11; minimum turndown default 30 percent |
| IN-FWU-4 | Supply air temperature, air ΔT, containment | |
| IN-FWU-5 | Connected loop, coil water ΔT, on mechanical UPS (yes / no) | |

### 9.9 Supporting zone types

| ID | Input | Notes |
|-|-|-|
| IN-Z-1 | Name, room category, count | UPS, battery, MV, LV / switch, transformer, MMR, comms, FCR, load bank, catcher, corridor, office |
| IN-Z-2 | Area, height, exposure | Box: external wall fraction, roof exposed, U-values (default 1.1 to 1.4 W/m²K concrete) |
| IN-Z-3 | Setpoint and humidity limit | |
| IN-Z-4 | Infiltration | Default 0 / 0.7 / 0.35 ACH per [NKB] |
| IN-Z-5 | Lighting, occupancy and profiles | Default 5 W/m², 100 m²/person, 70 / 60 W, [NKB] profile |
| IN-Z-6 | Fixed equipment heat | kW |
| IN-Z-7 | Allocated losses | Fractions of each electrical loss element (UPS, transformer, distribution, PDU, battery) released into this zone type. This is normally the dominant load of electrical and battery rooms, so these rooms need no separate cooling load input |
| IN-Z-8 | Served by | Room unit type(s) and share of load |
| IN-Z-9 | Boundary | Infrastructure or Excluded |

### 9.10 Room unit types

| ID | Input | Notes |
|-|-|-|
| IN-RU-1 | Type, quantity, redundancy mode, zones served | |
| IN-RU-2 | Capacity (total and net sensible), supply air, off-coil temperature, OA flow | |
| IN-RU-3 | Fan absorbed power per unit, fan part-load model | Section 11 |
| IN-RU-4 | COP at rating and curves (DX / VRF / PAC) | Default COP 3.0 flagged as assumption |
| IN-RU-5 | Connected loop (CRAH, PAC, FCU) | |
| IN-RU-6 | Dehumidifier / humidifier: capacity, power, activation | |
| IN-RU-7 | OAF / EAF: flow, power, schedule | |

### 9.11 Electrical

| ID | Input | Notes |
|-|-|-|
| IN-E-1 | Lineups | IT and mechanical lineups; which end uses each feeds |
| IN-E-2 | UPS types | Rating per module, modules per system, topology, efficiency table vs load (25 to 100 percent in 5 percent steps), path, share of losses to zones |
| IN-E-3 | Transformer types | Voltage pair, rating, quantity; percent of throughput or no-load + full-load loss |
| IN-E-4 | Distribution / switchboard / busduct | Percent of infrastructure electricity (default 1.0) and zone allocation |
| IN-E-5 | PDU loss | Percent (default 3 at Point B) |

### 9.12 Other end uses

| ID | Input | Notes |
|-|-|-|
| IN-O-1 | Generator testing | Format A or Format B |
| IN-O-2 | Jacket heaters | kW per generator, count, activation band (default on below 10 °C, ramp off at 32 °C) |
| IN-O-3 | Ancillary | Security, BMS, DCS / SCADA kW |
| IN-O-4 | Lifts | GBCA calculator inputs or annual kWh |
| IN-O-5 | DHW | Office in scope only |
| IN-O-6 | PV | Annual or hourly kWh (v1) |
| IN-O-7 | Data hall lighting | W/m² and profile per hall type |
| IN-O-8 | Contingency | Percent of infrastructure energy, basis text |

## 10. Calculation Requirements

### 10.1 General

* REQ-C-1: Hourly, 8,760 h per scenario, quasi-steady energy balance; no thermal mass.
* REQ-C-2: Temperatures, flows and powers solved from physics; setpoints are controls, not outputs, unless a capacity limit is reached.
* REQ-C-3: Unmet load recorded per hour and per device; unmet hours and kWh reported.
* REQ-C-4: Motor heat to the stream it serves (CDU pump heat to TCS, fan heat to air, pump heat to loop), consistent with [EP-ER] (pump heat to fluid equals shaft power for closed loops; fan motor in airstream fraction).
* REQ-C-5: Hourly energy balance closure within 0.5 percent or the hour is flagged.
* REQ-C-6: Bounded root finding (bisection or Brent) or closed forms only.

### 10.2 Per hour solution sequence and coupling

```
1  Weather, schedules, setpoint resets
2  IT power per hall type -> liquid share f_liq and air share (1 - f_liq)
3  Guess infrastructure power (previous iteration or hour)
4  Electrical loss chain from current loads (10.10) -> loss heat to zones
5  Zone sensible / latent loads: halls and supporting zones (10.3, 10.9)
6  Terminal equipment: FWUs, CDUs, room units -> loop loads (incl. fan / pump heat, PAC condenser heat)
7  Loops: flows, temperatures, pumps (Section 11, Section 12)
8  Plant: free cooling devices, chiller staging, heat rejection, fans (10.6 to 10.8)
9  Sum infrastructure power; if change > 0.01 percent go to 4 (relaxation 0.5 to 1.0, max 20 iterations)
```

* REQ-C-7: Non-convergence after 20 iterations is a warning with the hour listed.

### 10.3 Data hall loads

```
P_IT         = scenario fraction · installed IT, or the hourly profile value (UC-6), per hall type
Q_liq        = f_liq · P_IT
Q_air,hall   = (1 - f_liq) · P_IT + P_light + allocated losses + Q_env + Q_inf + P_FWU,fan,heat
Q_TCS        = Q_liq + P_CDU,pump,heat
```

### 10.4 CDU

* REQ-C-CDU-1: Active units share `Q_TCS` equally; thermal PLR per unit reported.
* REQ-C-CDU-2: `T_loop,sup,req = T_TCS,sup - ΔT_approach(Q)`, with `ΔT_approach(Q) = ΔT_approach,des · Q / Q_des` at fixed flows, or ε-NTU with `UA ∝ m^0.8` per side for variable flow. "Fixed approach" option reproduces [KO26].
* REQ-C-CDU-3: TCS return and LMTD per [KO26] Eq. 6 to 8; junction check per Eq. 9.
* REQ-C-CDU-4: Pump power per Section 11.
* REQ-C-CDU-5: If the loop supply exceeds `T_loop,sup,req`, report TCS supply drift and hours.

### 10.5 Fans and pumps

All fans and pumps follow Section 11.

### 10.6 Chillers

* REQ-C-CH-1: EIR model ([EP-ER] Electric EIR chiller; DOE-2):

  ```
  Q_avail = Q_ref · CAPFT(T_lwt, T_cond)
  PLR     = Q / Q_avail
  P       = (Q_avail / COP_ref) · EIRFT(T_lwt, T_cond) · EIRFPLR(PLR)
  ```

  `T_cond` = entering condenser air (air-cooled, after recirculation and adiabatic corrections) or entering condenser water.
* REQ-C-CH-2: Curve fit from manufacturer tables by bounded least squares; fit error reported; curves normalized to 1.0 at the rated point.
* REQ-C-CH-3: Staging: minimum number of duty units such that PLR ≤ stage-up threshold; equal loading; standby off; multiple types by priority.
* REQ-C-CH-4: Below minimum PLR: cycling degradation or false loading.
* REQ-C-CH-5: Integral pump per running chiller (Section 11).
* REQ-C-CH-6: Curve validity warnings with hour counts.
* REQ-C-CH-7: Condenser heat `Q + P` passed to heat rejection or ambient.

### 10.7 Integrated free cooling and adiabatic (CP-2)

* REQ-C-IFC-1: Free cooling capacity at full fan `Q_fc,max = f(T_ret - T_db,eff)` from input data.
* REQ-C-IFC-2: Modes: full free cooling (compressor off, fans modulate to setpoint); partial (coil at full fan, compressor trims); mechanical.
* REQ-C-IFC-3: Adiabatic: `T_db,eff = T_db + ΔT_recirc - ε_ad · (T_db + ΔT_recirc - T_wb)` when `T_db ≥ T_activation`.
* REQ-C-IFC-4: Report adiabatic hours, water use (net and gross), and the annual chiller energy reduction versus dry by an automatic counterfactual run with adiabatic disabled.

### 10.8 Dry coolers and towers

* REQ-C-HR-1: Dry cooler UA from rated point (ε-NTU cross flow); `UA(f) = UA_des · f^0.6` (editable); fan speed solved to meet leaving water setpoint; unmet if `f = 1` is insufficient. Fan power per Section 11 at the solved speed.
* REQ-C-HR-2: Adiabatic dry cooler per REQ-C-IFC-3.
* REQ-C-HR-3: Tower per [EP-ER] Merkel / Scheier variable speed model: `UA_e = UA_des · f_UA,wetbulb · f_UA,airflow · f_UA,waterflow`; fan speed solved for the target, minimum air flow rate ratio default 0.2 ([EP-IO]); fan power from a curve of air flow rate ratio.
* REQ-C-HR-4: WSE full / partial / off logic as DCOPTEST.

### 10.9 Supporting zones and room units

* REQ-C-Z-0: Supporting room cooling loads are **derived from the electrical loss chain** (10.10): each hour the losses computed for UPS, transformers, distribution and PDUs are released as heat into the zones they are allocated to (IN-Z-7). Room loads therefore rise and fall with IT and mechanical load, and the room unit energy closes the loop back into the infrastructure total (coupling in 10.2).
* REQ-C-Z-1: Zone sensible load: allocated losses + fixed equipment + lighting · profile + occupants · profile + `UA_env · (T_out - T_set)` + infiltration + OA sensible + fan heat.
* REQ-C-Z-2: Latent from occupants, infiltration and OA; handled by DX units or dehumidifiers where present; FWU / CRAH coils dry when coil surface is above zone dew point.
* REQ-C-Z-3: Load shared across serving unit types by input share, then equally across energised units.
* REQ-C-Z-4: CRAC / VRF / split: `P = Q / COP(T_amb + ΔT_recirc, PLR) + fans`; PAC: COP vs loop temperature, condenser heat to loop.
* REQ-C-Z-5: Ventilation and dehumidifiers per schedule and activation logic.

### 10.10 Electrical loss chain

* REQ-C-E-1: Loads assigned to lineups: IT to IT lineups; mechanical loads to mechanical lineups; flagged equipment on mechanical UPS.
* REQ-C-E-2: Per hour, from load outwards: PDU loss (Point B), UPS loss from efficiency at per-module load fraction, transformer MV/LV loss, transformer HV loss, distribution loss as percent of infrastructure electricity.
* REQ-C-E-3: IT path and mechanical path UPS losses reported separately.
* REQ-C-E-4: Loss heat released into zones per IN-Z-7; unallocated heat warns.

### 10.11 Other end uses

* REQ-C-O-1: Generator diesel from Format A or B; 0.01076 MWh/L (38.6 MJ/L) unless overridden; separate from electricity.
* REQ-C-O-2: Jacket heaters: hourly fraction `clamp((T_off - T_db) / (T_off - T_on), 0, 1)`; EFLH reported.
* REQ-C-O-3: Ancillary continuous; lifts per GBCA method or input; DHW per input; PV credit subtracted as net.

### 10.12 Metrics

```
E_infra       = Σ infrastructure electricity end uses (incl. losses) - PV
E_infra,cont  = E_infra · (1 + contingency)
PUE           = (E_IT + E_infra,cont + E_diesel) / E_IT        (energy ratio)
pPUE_cool     = (E_IT + E_cooling) / E_IT
WUE           = water use / E_IT
GHG (optional)= E_elec,net · EF_e + V_diesel · EF_d           (user factors, IN-P-4)
```

* REQ-C-M-1: Annual PUE is energy weighted, never a mean of hourly PUE. The same applies to PUE from an hourly IT profile (UC-6).
* REQ-C-M-2: Hourly PUE reported for every hour (annual-only items spread evenly or reported separately, user choice).
* REQ-C-M-3: Peak PUE in both framings (worst ratio, usually at lowest load; worst instantaneous at design load and high ambient) with hour, ambient and powers.
* REQ-C-M-4: No emissions-ratio PUE, star ratings or thresholds (D14). Workflows that need them post-process the exported energy results.

## 11. Fans and Pumps: PLR and Part-Load Curves

This section answers D3 and D13: every fan and pump is entered as design absorbed power × quantity and gets a PLR and a part-load curve, and every other equipment type also has a defined PLR and part-load curve.

### 11.1 Part-load capability and definitions

Part-load model for every equipment type (REQ-DM-2b):

| Equipment | PLR definition | Part-load curve (default form) | Section |
|-|-|-|-|
| Fans and pumps (all) | Flow fraction `f` (11.4) | `FFLP(f)` polynomial or table (11.3) | 11 |
| Chillers | `Q / Q_avail` per running unit | `EIRFPLR(PLR)` with `CAPFT`, `EIRFT` | 10.6 |
| Integrated free cooling coil | Free cooling share of load | Coil capacity vs ΔT; fan curve at solved speed | 10.7 |
| CDUs | `Q_TCS / (N_active · Q_unit)` | Approach vs load; pump per 11 | 10.4 |
| Dry coolers, towers | Heat rejected / rated capacity; fan speed solved | Fan `FFLP(f)` at solved speed; UA vs airflow | 10.8 |
| Room units (CRAC, PAC, VRF, split) | Zone load / (N_energised · capacity) | COP or EIR vs PLR and temperature; fan per 11 | 10.9 |
| UPS | Output / (active modules · module rating) | Efficiency vs load table (e.g. 25 to 100 percent in 5 percent steps) | 10.10 |
| Transformers | Throughput / rating | No-load loss + full-load loss · PLR², or percent of throughput | 10.10 |
| User defined plant item | User defined | Table vs PLR | |

Definitions for fans and pumps:

| Symbol | Meaning |
|-|-|
| `P_des` | Design absorbed electrical power per unit (kW), from the equipment schedule |
| `V_des` | Design flow per unit (m³/s or L/s) |
| `N_inst`, `N_duty`, `N_run` | Installed, duty and running unit count |
| `Q_served` | Heat load served by the equipment group this hour (kW), derived from IT load and other gains |
| `PLR_th` | Thermal part-load ratio of the group: `Q_served / Q_group,des` |
| `f` | Flow fraction per unit: `V_req / (N_run · V_des)`. This is what EnergyPlus calls PLR for pumps (`PartLoadRatio = VolFlowRate / NomVolFlowRate`, [EP-ER] Variable Speed Pump) and flow fraction for fans (`f_flow = m / m_design`, [EP-ER] fans) |
| `f_min` | Minimum flow fraction for power (fan / pump turndown limit) |
| `FFLP(f)` | Fraction of full-load power, the part-load curve |

### 11.2 Power equation

```
f_eff  = max(f, f_min)
P      = N_run · P_des · FFLP(f_eff) · k_drive(f_eff)
FFLP(f) = C1 + C2·f + C3·f² + C4·f³ + C5·f⁴
```

* The polynomial is the EnergyPlus form: quartic for `Fan:VariableVolume` and `Curve:Quartic` used by `Fan:SystemModel` ([EP-IO] group-fans), cubic (C5 = 0) for `Pump:VariableSpeed` "Coefficient 1 to 4 of the Part Load Performance Curve", whose defaults are 0, 1, 0, 0 ([EP-IO] group-pumps). Constant speed equipment has `FFLP = 1` ([EP-ER] Constant Speed Pump).
* Minimum flow for power: EnergyPlus `Fan:VariableVolume` "Fan Power Minimum Flow Fraction" default 0.25; `Fan:SystemModel` "Electric Power Minimum Flow Rate Fraction" default 0.2; `Pump:VariableSpeed` "Design Minimum Flow Rate Fraction" default 0.0 ([EP-IO]). The tool requires `f_min` explicitly per type (default 0.3 for FWUs per [NKB]).
* `k_drive(f)` is an optional motor and VFD part-load efficiency correction (11.3.2). It defaults to 1 and must only be used with shaft-power curves, never with empirical wire-to-air curves that already include drive losses (avoids double counting).

### 11.3 Curve library (with sources)

#### 11.3.1 Fraction of full-load power curves

| ID | Curve | C1 | C2 | C3 | C4 | C5 | Source |
|-|-|-|-|-|-|-|-|
| K-CONST | Constant speed | 1 | 0 | 0 | 0 | 0 | [EP-ER] Constant Speed Pump (`FracFullLoadPower = 1.0`) |
| K-LIN | Linear (EnergyPlus pump default) | 0 | 1 | 0 | 0 | 0 | [EP-IO] Pump:VariableSpeed defaults. Physically: constant head at constant efficiency, `P ∝ Q` |
| K-CUBE | Ideal affinity (cube law) | 0 | 0 | 0 | 1 | 0 | Fan / pump affinity laws; [EP-ER] multi-speed fan power ratio exponent "typically equal to 3" |
| K-DP(s) | Differential pressure control with control head fraction `s` | 0 | s | 0 | 1 - s | 0 | Derived (below); reduces to K-CUBE at `s = 0` and K-LIN at `s = 1` |
| K-VSM | EnergyPlus "Var. Speed Motor" fan | 0.0015302446 | 0.0052080574 | 1.1086242 | -0.11635563 | 0 | [EP-IO] Table "Fan Coefficient Values" |
| K-IVD | EnergyPlus "Inlet Vane Dampers" fan | 0.35071223 | 0.30850535 | -0.54137364 | 0.87198823 | 0 | [EP-IO] Table "Fan Coefficient Values" |
| K-DD | EnergyPlus "Discharge Dampers" fan | 0.37073425 | 0.97250253 | -0.34240761 | 0 | 0 | [EP-IO] Table "Fan Coefficient Values" |
| K-EPVAV | EnergyPlus Fan:SystemModel example "VAV Fan Curve" | 0.0407598940 | 0.08804497 | -0.072926120 | 0.9437398230 | 0 | [EP-IO] Fan:SystemModel example IDF |
| K-90.1G | ASHRAE 90.1 Appendix G VAV fan part-load curve | 0.0013 | 0.1470 | 0.9506 | -0.0998 | 0 | ASHRAE 90.1 Appendix G (Table G3.1.3.15). Not in the EnergyPlus documentation; **verify against the edition used** before release |
| K-USER | User polynomial or table (e.g. manufacturer part-load selections) | any | any | any | any | any | Project data, attributed |

Derivation of K-DP(s): a variable speed pump or fan controlled to hold a differential pressure (or static pressure) setpoint sees a system head `H = H_des · [s + (1 - s) · f²]`, where `s = H_setpoint / H_des` is the controlled (fixed) share of design head and the rest is friction that scales with flow squared. At constant efficiency `P ∝ Q · H`, so

```
P / P_des = f · [s + (1 - s) · f²] = s·f + (1 - s)·f³
```

which is the EnergyPlus cubic with `C2 = s`, `C4 = 1 - s`. This gives a physical meaning to the EnergyPlus default pump curve (linear: all head is controlled head) and to the cube law (no controlled head).

Comparison at selected flow fractions (fraction of design power, rounded):

| f | K-CUBE | K-DP(0.3) | K-LIN | K-VSM | K-90.1G |
|-|-|-|-|-|-|
| 1.0 | 1.000 | 1.000 | 1.000 | 0.999 | 0.999 |
| 0.8 | 0.512 | 0.598 | 0.800 | 0.656 | 0.676 |
| 0.6 | 0.216 | 0.331 | 0.600 | 0.379 | 0.410 |
| 0.4 | 0.064 | 0.165 | 0.400 | 0.174 | 0.206 |
| 0.3 | 0.027 | 0.109 | 0.300 | 0.100 | 0.128 |

Values computed from the coefficients above (to be regenerated by the test suite as golden values). The empirical curves K-VSM and K-90.1G sum to 0.999 at `f = 1`; the engine normalizes every curve to exactly 1.0 at `f = 1` so that design absorbed power is reproduced, and reports the normalization factor.

#### 11.3.2 Optional motor and VFD part-load efficiency (`k_drive`)

From [EP-ER] Fan:ComponentModel (Stein and Hydeman; DOE MotorMaster+ and DOE 2008 data), single rectangular hyperbola form:

```
η_VFD(x)                = a_VFD · x / (b_VFD + x) + c_VFD · x        (x = fraction of full-load motor input power)
η_motor(x) / η_motor,max = a_PL · x / (b_PL + x) + c_PL · x           (x = motor fractional output power)
k_drive(f) = [η_motor(1) · η_VFD(1)] / [η_motor(x(f)) · η_VFD(x(f))]
```

Example coefficients from [EP-ER]:

| Item | Rating | a | b | c |
|-|-|-|-|-|
| VFD | 10 hp | 0.978715 | 0.022227 | 0.001941 |
| VFD | 50 hp | 0.987910 | 0.018376 | -0.001692 |
| VFD | ≥ 200 hp | 0.984476 | 0.009828 | -0.004560 |
| Motor (4 pole) | 10 hp, η_max 0.8745 | 1.146258 | 0.045766 | -0.110367 |
| Motor (4 pole) | 25 hp, η_max 0.8991 | 1.137209 | 0.050236 | -0.08915 |
| Motor (4 pole) | 100 hp, η_max 0.9499 | 1.035294 | 0.012948 | -0.024708 |

`k_drive` is applied only with K-CUBE, K-DP(s) and K-LIN (shaft-power shapes). EC fan data from manufacturers is normally wire-to-air and should use K-USER without `k_drive`.

### 11.4 How PLR (flow fraction) is derived from IT load

The user does not enter PLR. The engine derives the served heat load each hour from the IT load (and the other gains on that path), then converts it to a flow fraction by one of the methods below, selected per equipment type. Default method per equipment is **TBD** (D13); a proposal is in 11.5.

| ID | Method | Equation | When it fits |
|-|-|-|-|
| M1 | Load proportional at design ΔT | `f = (Q_served / Q_group,des) · (N_des / N_run)` | ΔT held at design (ΔT control, containment, CDU constant rack ΔT). Simplest and fully transparent |
| M2 | Physics, actual ΔT | `V_req = Q_served / (ρ · cp · ΔT_actual)`; `f = V_req / (N_run · V_des)` | ΔT varies with resets (CHW reset, supply air reset, mixed returns). Collapses to M1 when ΔT is constant |
| M3 | Fixed flow | `f = 1` for every running unit | Constant speed, or vendor fixed absorbed power (typical CDU pump per [NKB]) |
| M4 | Server airflow (FWUs) | `V_req = (1 - f_liq) · P_IT · v_IT · (1 + β_bypass)`; `f = V_req / (N_run · V_des)` | Airflow tracks server fan demand: `v_IT` is server specific airflow (m³/s per kW), `β_bypass` the containment bypass / leakage margin |
| M5 | Heat-transfer solved | `f` solved so the device meets its leaving temperature setpoint (Section 10.8) | Dry cooler, tower and condenser fans: not proportional to IT load; depends on ambient |
| M6 | User table vs IT load | `f = table(IT load fraction)` per type, interpolated | Designer or vendor part-load selections, sequence of operations values |

Rules common to all methods:

* `Q_served` includes every gain on that path (e.g. FWU: air-side IT heat, lighting, allocated losses, envelope, fan heat), so the energy balance holds; this is the link from IT load to equipment PLR.
* Minimum flow: `f_eff = max(f, f_min)`. If `f < f_min` for a pump, the excess flow bypasses and the loop ΔT falls; the reduced ΔT is reported. For a fan, the surplus airflow is reported as bypass air.
* Chiller minimum evaporator flow overrides primary pump `f_min` where higher.
* Pump power curve choice (K-DP(s) etc.) is independent of the PLR method; for example M2 + K-DP(0.3) is a variable flow secondary pump on ΔP control.

### 11.5 Running units: equal speed versus staged

| Option | Rule | Source / rationale |
|-|-|-|
| R-ALL (proposed default for fans and parallel VSD pumps) | All energised units run at equal speed: `N_run = N_duty` (+ standby if redundancy mode is `2N_active` or `0.5N+0.5N`) | Common practice for EC fan walls and parallel VSD pumps; minimizes power when `FFLP` is convex |
| R-STAGE | Minimum `N_run` such that `f ≤ f_stage,up`, with hysteresis | Staged pumps and fans per SOO |
| R-EPSEQ | EnergyPlus sequential loading: all units full flow except one at part load | [EP-ER] HeaderedPumps (`Power = (PR_FL·N_FL + PR_PL·N_PL)·P_Nom`, `N_PL = 1` for variable speed); used to match EnergyPlus in equivalence tests |

Worked example (cube law, 4 duty + 1 standby energised, `f_min = 0.3`, units of `P_des`):

| IT load | R-ALL (5 running) | R-STAGE (minimum units, f ≤ 1) |
|-|-|-|
| 90 percent | f = 0.9 × 4 / 5 = 0.72 → 5 × 0.373 = **1.87** | 4 units at f = 0.9 → 4 × 0.729 = **2.92** |
| 25 percent | f = 0.2 → clamped 0.3 → 5 × 0.027 = **0.14** | 1 unit at f = 1.0 → **1.00** |

The example shows why the running-unit rule and `f_min` matter as much as the curve, especially at 25 percent IT load.

### 11.6 Proposed defaults (for confirmation, D13)

| Equipment | PLR method | Curve | f_min | Running rule |
|-|-|-|-|-|
| FWU fans | M2 (air ΔT) | K-USER if vendor data, else K-VSM | 0.3 | R-ALL |
| CDU pumps | M3 (fixed) | K-CONST | n/a | Active units |
| Integral chiller CHW pumps | M3 when constant primary; M2 when variable primary | K-CONST or K-DP(s) | Chiller minimum evaporator flow | Per running chiller |
| Loop secondary pumps | M2 | K-DP(0.3) | 0.3 | R-ALL |
| Dry cooler / ACC condenser / tower fans | M5 | K-USER or K-CUBE | 0.2 | R-ALL |
| CRAH / FCU fans | M2 | K-VSM | 0.3 | R-ALL |
| CRAC / VRF indoor fans | M3 (constant) or M2 if EC | K-CONST or K-VSM | 0.5 | R-ALL |
| OAF / EAF | M3 | K-CONST | n/a | All |

## 12. Loops at Different Temperatures

Answer to D12: yes, two or more loops at different supply temperatures can be modelled with plain mass and energy balances. A chiller produces one leaving temperature at a time, so the arrangement that creates the second temperature must be stated. Four arrangements are proposed; the default is **TBD**.

| ID | Arrangement | Physics | Energy consequences |
|-|-|-|-|
| DT-A | **Blending from a common plant**: chillers run at the lowest setpoint (e.g. 24 °C); the higher temperature loop (e.g. 26 °C) is made by mixing its own return into its supply through a blending valve | `m_draw = m_HT · (T_HT,ret - T_HT,sup) / (T_HT,ret - T_MT,sup)`; plant return `T_ret = (m_MT·T_MT,ret + m_draw·T_HT,ret) / (m_MT + m_draw)` | Chillers evaluated at the lower LWT (small COP penalty); the warmer mixed return helps free cooling; one plant |
| DT-B | **Heat exchanger cascade**: the higher temperature loop is isolated from the lower loop by a plate HX | `T_HT,sup = T_MT,sup + ΔT_HX,approach` (e.g. 24 + 2 = 26 °C); HX load = `Q_HT`; the HT loop has its own (secondary) pump | Lower loop carries all load; extra HX pump power; HT loop temperature tied to MT loop plus approach |
| DT-C | **Dedicated chiller groups**: each loop has its own chillers (and free cooling) at its own setpoint | Each loop solved as an independent plant | Each group at its best LWT; staging and redundancy per group; more equipment |
| DT-D | **Split duty**: free cooling devices (dry coolers) serve the higher temperature loop directly; chillers serve the lower loop and trim the higher loop through an HX when free cooling is insufficient | DT-C plus DT-B for trim | Maximizes free cooling hours on the warm loop |

Requirements:

* REQ-DT-1: Each loop declares `connection` (direct, DT-A blended, DT-B via HX, DT-C dedicated, DT-D split) and the loop it draws from.
* REQ-DT-2: Mass and energy balances are solved at every junction and HX each hour; achieved supply temperatures are reported per loop.
* REQ-DT-3: If a loop cannot reach its setpoint (e.g. DT-B with insufficient approach), unmet hours are reported.
* REQ-DT-4: EnergyPlus reference: DT-B, DT-C, DT-D map to separate `PlantLoop`s and `HeatExchanger:FluidToFluid`; DT-A needs a tertiary loop arrangement or EMS (documented in the equivalence report).

## 13. Output and Reporting Requirements

### 13.1 Hourly (D5)

* REQ-OUT-H-1: Per scenario, an 8,760 row file (CSV and Parquet): weather, IT power, every end use, every loss element, PUE, zone loads, loop temperatures and flows, chiller units running and PLR, free cooling / adiabatic mode, `f`, `f_eff`, `N_run` and power for every fan and pump type, unmet load, water use, iteration count.
* REQ-OUT-H-2: Column presets (summary, plant, fans and pumps, electrical, full).
* REQ-OUT-H-3: Daily and monthly aggregates.

### 13.2 Core tables and workflow output sets

Core tables are produced for every run; workflow output sets select, order and label them (PR-6). Output sets are YAML definitions, so users can add their own.

| ID | Core table |
|-|-|
| OUT-1 | Scenario summary: IT energy, infrastructure energy, diesel, PUE, pPUE, WUE, peak PUE (and GHG if factors given) per scenario or profile |
| OUT-2 | End-use breakdown, granular and coarse, with electricity (MWh/yr), diesel (L/yr and MWh/yr) and percent columns, PV credit, totals, PUE |
| OUT-3 | End-use breakdown per scenario (one column per scenario) |
| OUT-4 | Monthly energy by end use |
| OUT-5 | Weather file parameters and monthly weather table |
| OUT-6 | Input overview and input register with attribution, assumptions applied and pending items |
| OUT-7 | UPS efficiency table and electrical loss summary (IT path and mechanical path) |
| OUT-8 | Chiller configuration and data, operating adjustments, adiabatic mode parameters |
| OUT-9 | CDU, FWU, room unit, ventilation / dehumidifier tables, including part-load model per equipment type |
| OUT-10 | Generator testing, jacket heater, lift, DHW, PV tables |
| OUT-11 | Floor areas by space type; internal loads; profiles; setpoints |
| OUT-12 | Design check: peak powers by end use, installed vs required capacity per equipment type (N and N+x), unmet hours, minimum-speed hours |

| Output set | Contents (initial proposal) |
|-|-|
| `nabers` | OUT-1 (90 percent base case and 75 / 50 / 25 percent), OUT-2, OUT-3, OUT-5 to OUT-11, energy-ratio PUE only |
| `leed` | OUT-1, OUT-2, OUT-4 (monthly end uses), OUT-5, OUT-6; annual energy by end use and fuel for the proposed design |
| `ssda` | OUT-1 with GHG, OUT-2 with GHG columns using the user factors, OUT-6 |
| `design-check` | OUT-1, OUT-8, OUT-9, OUT-12, plus hourly plant files |

* REQ-OUT-13: Export as XLSX, CSV, Markdown and JSON.
* REQ-OUT-14: Charts: end-use pie, PUE vs IT load, monthly stacked energy, hourly PUE carpet plot, hourly IT profile vs infrastructure power (UC-6), chiller PLR histogram, fan / pump flow fraction histograms, mode hours.

### 13.3 Calculation transparency

* REQ-OUT-T-1: A **calculation report** listing every equation used with its source ID from Section 15, every curve and its coefficients, and every default applied.
* REQ-OUT-T-2: `explain(item, hour)` prints the equation chain and input values for any result.

### 13.4 Warnings (always exported)

Capacity shortfall; unmet loop or zone setpoints; chiller curves outside validity; chiller below minimum PLR for more than a set share of hours; fans or pumps at `f_min` for more than a set share of hours; bypass flow; glycol missing below 0 °C; unallocated loss heat; non-convergence; pending manufacturer data used; preset defaults applied; IT profile gaps or values above installed IT.

## 14. Verification and Equivalence Plan

### 14.1 Component verification (analytical)

| ID | Test | Acceptance |
|-|-|-|
| V-C-1 | Chiller at rated point returns rated capacity and COP; curve evaluation equals hand calculation | 1e-9 relative |
| V-C-2 | Every curve in 11.3 at test points; K-DP(s) equals `s·f + (1 - s)·f³` | Exact |
| V-C-3 | PLR methods M1 to M6 against hand calculations, including `f_min` clamp and running-unit rules | Exact |
| V-C-4 | Dry cooler at rated point returns rated capacity; ε-NTU limits | 0.1 percent |
| V-C-5 | UPS and transformer losses at table points | Exact |
| V-C-6 | Psychrometrics against ASHRAE Fundamentals tables | 0.1 K, 0.5 percent |
| V-C-7 | Loop junction mass and energy balances (Section 12) | 1e-9 relative |

### 14.2 Component equivalence against EnergyPlus

| ID | Component | EnergyPlus object | Acceptance (hourly) |
|-|-|-|-|
| V-E-1 | Chillers | `Chiller:Electric:EIR` | Power within 1 percent |
| V-E-2 | Pumps (each curve in 11.3) | `Pump:VariableSpeed`, `Pump:ConstantSpeed`, `HeaderedPumps:VariableSpeed` (R-EPSEQ) | 1 percent |
| V-E-3 | Fans (each curve in 11.3) | `Fan:SystemModel` with `Curve:Quartic` | 1 percent |
| V-E-4 | Cooling tower | `CoolingTower:VariableSpeed:Merkel` | Leaving temperature 0.1 K, fan power 2 percent |
| V-E-5 | Liquid ITE loop | `ElectricEquipment:ITE:LiquidCooled` | Temperatures 0.05 K |
| V-E-6 | DX units | `Coil:Cooling:DX:SingleSpeed`, VRF | 2 percent |
| V-E-7 | Gap components (VS dry cooler, adiabatic, integrated FC, DT-A blending) | EnergyPlus with EMS | 2 percent |

### 14.3 System equivalence against EnergyPlus

| Metric | Acceptance |
|-|-|
| Annual PUE (each scenario) | ±0.01 |
| Annual energy per major end use | ±2 percent |
| Hourly infrastructure power | NMBE ±1 percent, CV(RMSE) ≤ 5 percent |
| Free cooling / adiabatic hours | ±2 percent of hours |

### 14.4 Other validation

* V-O-1: DCOPTEST Types 7 to 12 reproduced with fixed flows and the FMU chiller curves: pPUE within ±0.02.
* V-O-2: [KO26] Tampa W17 and W45: loop temperatures within 0.1 K; annual PUE within ±0.03 (assumptions for unpublished pump and fan powers documented).
* V-O-3: Energy balance closure ≤ 0.5 percent every hour of every regression case.
* V-O-4: Randomized valid inputs never raise; infeasibilities become warnings.
* V-O-5: Golden reference results per template in CI with per-variable rtol / atol.
* V-O-6 (deferred, D9): back-testing against past delivered projects.

## 15. Equation and Data Source Register

Every equation and default in the engine carries one of these IDs in code and in the calculation report.

| ID | Item | Source |
|-|-|-|
| S-EQ-01 | Liquid / air heat split `Q_liq = f_liq · P_IT` | D11; [KO26] Eq. 1 with `f_liq = 1 - φ` |
| S-EQ-02 | Loop and TCS energy balances, CDU approach, LMTD, junction temperature | [KO26] Eq. 2 to 9 |
| S-EQ-03 | Chiller EIR model (CAPFT, EIRFT, EIRFPLR) | [EP-ER] Electric EIR chiller (DOE-2 formulation) |
| S-EQ-04 | Pump part-load power `FFLP = C1 + C2·PLR + C3·PLR² + C4·PLR³`, `PLR = V / V_nom` | [EP-IO] Pump:VariableSpeed; [EP-ER] Variable Speed Pump |
| S-EQ-05 | Fan part-load power `PLF = C1 + C2·FF + C3·FF² + C4·FF³ + C5·FF⁴` | [EP-IO] Fan:VariableVolume; Fan:SystemModel with Curve:Quartic |
| S-EQ-06 | Fan coefficient sets (Var. Speed Motor, Inlet Vane Dampers, Discharge Dampers, VAV example) | [EP-IO] Table "Fan Coefficient Values" and Fan:SystemModel example |
| S-EQ-07 | Differential pressure control curve `s·f + (1 - s)·f³` | Derived from affinity laws and system curve (Section 11.3.1) |
| S-EQ-08 | Motor and VFD part-load efficiency | [EP-ER] Fan:ComponentModel (Stein and Hydeman; DOE MotorMaster+; DOE 2008) |
| S-EQ-09 | Headered pump sequential power | [EP-ER] Headered pumps |
| S-EQ-10 | Cooling tower Merkel / Scheier UA adjustments; minimum air flow rate ratio 0.2 | [EP-ER] cooling towers; [EP-IO] CoolingTower:VariableSpeed:Merkel |
| S-EQ-11 | Dry cooler ε-NTU, UA vs airflow exponent | Heat transfer texts (ε-NTU cross flow); exponent user editable, default 0.6 (assumption, attributed) |
| S-EQ-12 | Adiabatic effective entering temperature | Saturation efficiency definition; [NKB] adiabatic method |
| S-EQ-13 | Psychrometrics, WUE, COC, drift | ASHRAE Fundamentals; DCOPTEST README 9.1 and 9.2 |
| S-EQ-14 | Scenario set (90 / 75 / 50 / 25), infiltration, internal loads, loss allowances used as defaults | [NKB] |
| S-EQ-15 | ASHRAE 90.1 Appendix G VAV fan curve | ASHRAE 90.1 Appendix G; verify edition (Section 11.3.1) |
| S-EQ-16 | Generator diesel energy 0.01076 MWh/L; jacket heater ramp | [NKB] |
| S-EQ-17 | PUE (energy ratio), WUE, optional GHG = energy × user factor | The Green Grid PUE definition; [KO26] Eq. 10 and 11; D14 |
| S-DEF-01 | Default chiller curve analogues | EnergyPlus datasets `AirCooledChiller.idf` and `Chillers.idf` (same commit as [EP-IO]); DCOPTEST FMU chiller coefficients. Note: dataset curves are rated near standard chilled water conditions; extrapolation to elevated CHW is flagged (REQ-C-CH-6) |
| S-DEF-02 | Default pump design power 348,701.1 W per m³/s (22 W/gpm) | [EP-IO] Pump:VariableSpeed `Design Electric Power per Unit Flow Rate` default |
| S-DEF-03 | Default fan design power 1.66667 W per (m³/s · Pa) | [EP-IO] Fan:SystemModel `Electric Power Per Unit Flow Rate Per Unit Pressure` default |

## 16. Non-Functional Requirements

* NF-1 Performance: one scenario or one 8,760 h IT profile under 5 s; four load scenarios plus the adiabatic counterfactual under 30 s on a laptop.
* NF-2 Determinism: identical inputs give identical outputs.
* NF-3 Transparency: Section 13.3; every module documents its equations with Section 15 IDs.
* NF-4 Portability: pure Python core (`numpy`, `pandas`, `pydantic`, `pyyaml`, `scipy`); EnergyPlus only for the verification exporter.
* NF-5 Versioning: schema and tool version stamped on every output; results reproducible from the archived input file.
* NF-6 Units: SI internal; SI / IP display.
* NF-7 Licensing: compatible with BSD 3-Clause (DCOPTEST) and EnergyPlus.
* NF-8 Code quality: typed, unit tested (target 90 percent line coverage of the engine).

## 17. Mapping: DCOPTEST to the New Tool

| DCOPTEST element | New tool | Action |
|-|-|-|
| `DataCenterFMU.fmu` | Python quasi-steady engine; EnergyPlus exporter for equivalence | Replace |
| Types 1 to 12 | `water_system.type` + `plant.type` | Replace (Types 7 to 12 map to CP-9, CP-7, CP-8, CP-3, CP-5, CP-10) |
| `.mos` climate files | EPW (same 19 locations) | Replace |
| Stull wet bulb | EPW wet bulb / dew point; Stull fallback | Keep as fallback |
| `it_profile.csv` | Flat scenarios or profile | Replace |
| Setpoints (CHW 15 °C, CDU 27 °C, air 18 / 25 °C) | "DCOPTEST compatible" template | Keep as template |
| CW reset | Tower / dry cooler control option | Keep |
| Chiller EIR coefficients | Library entry "DCOPTEST reference chiller" | Keep |
| Fixed speed pumps and fans | K-CONST with M3 | Extend |
| `PUE = 1 + PHVAC / PIT` | pPUE (cooling) plus full facility PUE (energy ratio) | Extend |
| WUE method | Same method, single constant set | Keep, fix L7 |
| Mode classification | Plus adiabatic modes | Extend |
| ASHRAE compliance bins | Same | Keep |
| Golden reference tests, error log | Same practice | Keep |
| Multi-climate batch | CLI batch | Keep in spirit |

## 18. Phased Delivery Plan

| Phase | Content | Exit criteria |
|-|-|-|
| P0 Spec | This document; schema; templates; answers to Section 20 | Sign-off |
| P1 Physics foundation | Weather, psychrometrics, curve library, fan / pump part-load module (Section 11), chiller EIR, ε-NTU heat exchangers, dry cooler, tower, loop junctions (Section 12) | V-C tests pass |
| P2 Plant and halls | CDU, FWU, loops, chillers with free cooling and adiabatic, hourly engine and coupling loop, 8,760 h IT profile input, topology presets and auto-sizing (8.4) | V-C tests pass; energy balance closes; every preset runs from minimum input |
| P3 EnergyPlus exporter and component equivalence | V-E suite | V-E targets met |
| P4 Electrical, other end uses, metrics | Loss chain, heat allocation to supporting rooms, diesel, PV, contingency, PUE, WUE, optional GHG | V-C tests pass |
| P5 Supporting zones and room units | Zones, CRAH, CRAC, PAC, VRF, ventilation, dehumidifiers, redundancy modes | V-C tests pass |
| P6 System equivalence | Templates run in both engines | 14.3 targets met |
| P7 Outputs | Core tables, workflow output sets (`nabers`, `leed`, `ssda`, `design-check`), hourly files, charts, calculation report, input register | Reviewed |
| P8 Water-cooled plants and towers | CP-7 to CP-10; DCOPTEST comparison | V-O-1 |
| Later | Back-testing (D9), GUI, PVWatts, cost, immersion, heat reuse | As prioritized |

## 19. Risks

| Risk | Impact | Mitigation |
|-|-|-|
| Formal acceptance of a new engine for regulatory submissions (D8 TBD) | High where a scheme requires an accepted simulation package | EnergyPlus exporter and documented equivalence; decision deferred |
| Preset defaults taken as project data | Medium | Defaults always listed as assumptions before results (REQ-PRE-1) and in the input register |
| Chiller curves at elevated CHW temperatures extrapolated | High | Validity warnings; manufacturer table fit; attribution as pending |
| Fan / pump part-load assumptions dominate low-load PUE | High | Explicit PLR method, curve, `f_min` and running rule per type; sensitivity output |
| Equivalence gaps where EnergyPlus lacks native objects | Medium | EMS reference models implementing the same equations, labelled as such |
| ASHRAE 90.1 Appendix G coefficients quoted from memory | Low | Verify against the standard edition before release (S-EQ-15) |
| Workflow rule changes (NABERS, LEED, SSDA) | Low | Engine is workflow neutral; output sets and defaults are versioned YAML |

## 20. Open Questions

1. **D13 defaults**: confirm or change the proposed PLR method, curve, `f_min` and running rule per equipment type in Section 11.6. In particular: should FWUs default to all energised units at equal speed (R-ALL)?
2. **FWU curve when no vendor data**: K-VSM (EnergyPlus "Var. Speed Motor"), K-90.1G, or K-DP(s) with a stated `s`? K-VSM is proposed as a moderately conservative default.
3. **D12 default**: which loop arrangement (DT-A blending, DT-B HX cascade, DT-C dedicated, DT-D split) should be the default for multi-temperature designs?
4. **M4 server airflow method**: is it useful to offer FWU airflow from server specific airflow (m³/s per kW) and a bypass margin, or is the air ΔT method (M2) enough?
5. **D8** (TBD, not blocking): formal acceptance route where a scheme requires an accepted simulation package.
6. **Preset defaults (8.4.2)**: confirm the auto-sizing rules, and give default fan pressure rises (FWU, CRAH, dry cooler) and the default N for chillers, or point to typical values you use.
7. **Output sets (13.2)**: are the proposed `leed` and `ssda` contents right? For example, does SSDA GHG estimation need anything beyond annual energy by source × user factors (such as scope split or monthly values)?

## 21. Glossary

| Term | Meaning |
|-|-|
| ACC | Air-cooled chiller |
| CDU / TCS | Coolant distribution unit / technology cooling system (secondary loop to racks) |
| CHWP / CWP | Chilled water pump / condenser water pump |
| CRAC / CRAH / PAC | DX computer room air conditioner / chilled water air handler / packaged (often water-cooled) air conditioner |
| DTC | Direct-to-chip liquid cooling |
| EFLH | Equivalent full load hours |
| EIR | Energy input ratio (1 / COP) |
| `f`, `f_min`, `FFLP` | Flow fraction, minimum flow fraction for power, fraction of full-load power (Section 11) |
| `f_liq` | Liquid fraction: share of IT heat captured by liquid (D11) |
| FWS | Facility water system |
| FWU | Fan wall unit |
| Lineup | Modular power train (generator, transformer, switchboard, UPS) serving a load group |
| NABERS | National Australian Built Environment Rating System |
| PLR | Part load ratio. Thermal PLR for chillers and CDUs; flow fraction for fans and pumps (EnergyPlus convention) |
| pPUE | Partial PUE |
| SOO | Sequence of operations |
| WSE | Water-side economizer |
| W17 to W45 | ASHRAE 2021 liquid cooling classes by facility water supply temperature |
| [EP-IO] / [EP-ER] | EnergyPlus Input Output Reference / Engineering Reference (source files listed under Sources) |
| [KO26] | Ko et al., arXiv:2610.33148v1 |
| [NKB] | NABERS DC Infrastructure Rating knowledge base (user supplied) |
