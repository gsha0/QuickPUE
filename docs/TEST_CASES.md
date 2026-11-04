# QuickPUE Reference Test Cases

Status: Draft v0.1
Date: 2026-11-04
Companion to: `docs/NEW_TOOL_REQUIREMENTS.md`

Two reference test cases extracted from delivered design-stage data centre energy assessment reports. Project-specific information (client, project and site names, addresses, equipment tags, document references, manufacturer model names) has been omitted. The cases are named **DC_O1** and **DC_S1**.

## Contents

1. [Purpose and conventions](#1-purpose-and-conventions)
2. [Common data](#2-common-data)
3. [DC_O1: 62 MW, dual CHW loops, adiabatic air-cooled chillers](#3-dc_o1-62-mw-dual-chw-loops-adiabatic-air-cooled-chillers)
4. [DC_S1: 192 MW, single 28 to 38 °C loop, free-cooling air-cooled chillers](#4-dc_s1-192-mw-single-28-to-38-c-loop-free-cooling-air-cooled-chillers)
5. [Implications for the requirements](#5-implications-for-the-requirements)
6. [Open items](#6-open-items)

## 1. Purpose and conventions

The source reports were produced with a detailed dynamic simulation package plus manual calculations. Their results are **practice reference values, not ground truth**. Each case lists its inputs with a status, deterministic checks, simulated-result comparisons, missing data and source inconsistencies found during extraction.

Status codes:

| Code | Meaning |
|-|-|
| S | Stated in the source report |
| D | Derived here from stated values (derivation shown) |
| C | Conflicting statements in the source report |
| M | Missing; needed before the case is complete |

Check tiers:

| Tier | Meaning | Acceptance |
|-|-|-|
| T1 | Deterministic arithmetic or a single-point physics check reproducible exactly from stated inputs | Within 0.5 percent (or 0.1 K) |
| T2 | Simulated end uses that depend on plant, weather and part-load behaviour | Each end use above 5 percent of infrastructure energy within ±10 percent; total infrastructure electricity within ±3 percent; energy-ratio PUE within ±0.02 at every IT load. Applies once all M items are supplied |
| T3 | Robustness: the case runs end to end with preset defaults filling M items | Completes; hourly energy balance closes; every default and every C item appears in the warnings and input register |

Both source reports express results partly as NABERS emissions. The tool reports energy only (requirements D14), so emissions are converted back to energy where needed and emissions-ratio values are recorded for information only.

## 2. Common data

### 2.1 Weather (both cases)

Test weather file: `AUS_NSW_Horsley.Equestrian.Centre.947600_TMYx.2011-2025` (EPW; station 947600; lat -33.85, lon 150.86; altitude 100 m). The EPW is not yet in the repository and must be added as test data. Monthly summary from the source reports, usable as weather reader check **W-01**:

| Month | DBT max (°C) | DBT min (°C) | DPT max (°C) | DPT min (°C) | RH mean (%) |
|-|-|-|-|-|-|
| Jan | 43.1 | 14.4 | 20.9 | 6.2 | 68 |
| Feb | 34.4 | 13.7 | 20.9 | 11.0 | 74 |
| Mar | 34.5 | 9.9 | 21.0 | 0.0 | 72 |
| Apr | 29.3 | 9.3 | 19.3 | 2.5 | 72 |
| May | 24.3 | 1.6 | 15.6 | -2.6 | 72 |
| Jun | 19.4 | 2.1 | 12.9 | -2.7 | 72 |
| Jul | 24.1 | 0.6 | 13.9 | -3.5 | 68 |
| Aug | 26.3 | 2.8 | 11.3 | -3.0 | 62 |
| Sep | 28.4 | 4.2 | 15.5 | -5.2 | 62 |
| Oct | 29.4 | 8.0 | 18.1 | -1.0 | 67 |
| Nov | 40.0 | 9.5 | 22.8 | 6.5 | 68 |
| Dec | 36.5 | 10.1 | 22.9 | -1.3 | 67 |
| Annual | 43.1 | 0.6 | 22.9 | -5.2 | 69 |

### 2.2 Fan part-load curve (both cases)

Used by both source reports for all supply and return fans, read from the chart data embedded in the DC_S1 report; 30 percent minimum turndown. Entered in the test cases as a project K-USER table attributed to the source, not as a library curve:

| Flow fraction | 0.0 | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | 1.0 |
|-|-|-|-|-|-|-|-|-|-|-|-|
| Power fraction | 0.08 | 0.08 | 0.11 | 0.16 | 0.22 | 0.29 | 0.37 | 0.47 | 0.61 | 0.78 | 1.00 |

The same chart carries a "90.1 Full Setpoint Reset" series (0.02, 0.02, 0.03, 0.06, 0.11, 0.18, 0.27, 0.39, 0.55, 0.75, 1.00) and a square law, for comparison only.

### 2.3 Common modelling conventions in both sources

| Item | Value |
|-|-|
| IT load | Flat 8,760 h at 90 (base), 75, 50 and 25 percent of installed IT |
| Infiltration | 0 ACH pressurised data halls and critical areas; 0.7 ACH zones without mechanical outdoor air; 0.35 ACH otherwise |
| Data centre lighting and occupancy profile | 5 percent 00:00 to 08:00 and 18:00 to 24:00; 15 percent 08:00 to 18:00 |
| Occupant gains | 70 W sensible, 60 W latent per person |
| Concrete fabric | U 1.1 W/m²K (200 mm) and 1.4 W/m²K (300 mm), no insulation |
| Room DX / VRF / split units | COP 3.0 assumed where no vendor data |
| Distribution and switchboard losses | Stated as 1 percent of infrastructure electricity (see DC_O1 check O-06) |
| Generator jacket heaters | 8 kW per generator; on below 10 °C, ramping off by 32 °C; EFLH 3,680 h |
| Lifts | 2 passenger (36,500 trips, 13.5 m, 1.0 m/s, 13 s, 1,275 kg, 13.6 kW) and 2 goods (18,250 trips, 13.5 m, 0.8 m/s, 15.4 s, 5,000 kg, 51.2 kW); regenerative; standby 0.08 kW, 24 h × 365 d; 4,068 + 7,390 = 11,458 kWh/yr |
| PV | Fixed roof, azimuth 10°, tilt 3°, 19 percent module, -0.37 %/°C, 96 percent inverter, 14 percent losses; specific yield 1,299 kWh/kW (PVWatts) |

## 3. DC_O1: 62 MW, dual CHW loops, adiabatic air-cooled chillers

Closest preset: `LC-ACC-IFC-DUAL` with adiabatic (WS-2 dual loops from a common plant; CP-2 if the chillers have integrated free cooling, otherwise CP-1 with adiabatic; see M-O3).

### 3.1 IT, scenarios and space

| Input | Value | Status |
|-|-|-|
| Data halls | 2 × 9.4 MW and 4 × 10.84 MW; total 62.16 MW | S |
| IT basis used for energy | 62.0 MW (488,808 MWh/yr at 90 percent = 62 × 0.9 × 8,760) | D (see I-O2) |
| Liquid / air split | CDUs "up to 70 percent", FWUs "up to 40 percent" of hall heat; modelled split not stated | C, M-O1 |
| Cold aisle | 27 ± 1 °C; RH 20 to 80 percent, dew point below 17 °C | S |
| Floor areas | Data centre 21,875 m²; office 1,970 m²; substation 1,282 m²; total 25,127 m² | S |
| Boundary | Office energy included (conservative) | S |

### 3.2 Cooling plant and loops

| Input | Value | Status |
|-|-|-|
| Chillers | 38 air-cooled chillers with adiabatic pads in 3 blocks: 13 (11 duty + 2 standby), 12 (11 + 1), 13 (11 + 2); 33 duty / 5 standby; plant sized to 90 percent IT | S |
| Rated point | 2,200 kW (wet mode); COP 4.80 at 32 °C entering condenser air and 24 °C CHW supply; CHW flow 52.6 L/s (ΔT 10.0 K, D) | S |
| Part-load curves | Manufacturer data fitted to COP vs PLR and ambient DB; the data table is not in the source; only a COP surface chart (load 220 to 2,200 kW, ambient 17 to 35 °C) | M-O2 |
| Integral CHW pump | 37 kW per chiller at design, minimum flow 70 percent of design | S |
| Recirculation | +5 K on condenser entering air, dry and wet modes (from CFD) | S |
| Adiabatic | Activation 31 °C DB; efficiency 78 percent; 157 h/yr; chiller energy reduction 4 to 6 percent vs dry | S |
| Staging | Minimum number of duty chillers for the load; standby only on fault or rising load | S |
| Free cooling | Not described; COP surface rises to about 55 at low load and 17 °C, which suggests integrated free cooling in the data | M-O3 |
| Thermal storage tanks | Present, not modelled | S |
| Loops | Medium temperature 24 / 34 °C to FWUs; high temperature 26 / 36 °C to CDUs and water-cooled DX units; both from the same chillers | S; arrangement M-O4 |
| CHW reset | Not stated | M-O5 |

### 3.3 Terminal and room equipment

| Input | Value | Status |
|-|-|-|
| CDUs | 60 installed, 30 active; high temperature loop; pumps described as constant; 25 kW per unit in the two 9.4 MW halls, 23 kW per unit in the four 10.84 MW halls | S |
| CDUs per hall | 5 active per hall, so active pump power = 10 × 25 + 20 × 23 = 710 kW | D (check O-04) |
| FWU type A (9.4 MW halls) | 31,000 L/s; 580 Pa; 31.0 kW fan; 330 kW coil | S; quantity M-O6 |
| FWU type B (10.84 MW halls) | 29,000 L/s; 580 Pa; 29.0 kW fan; 326 kW coil | S; quantity M-O6 |
| FWU operation | EC fans, 11 K air ΔT, 30 percent minimum turndown, fan curve 2.2; medium temperature loop | S |
| PAC (water-cooled) | Battery: 261 L/s supply, 40 L/s OA, COP 3.0, 0.19 kW fan, 4.6 kW cooling, 1.8 kW heating. Pressurisation type A: 840 / 420 L/s, COP 3.0, 0.79 kW, 17.9 / 8.7 kW. Pressurisation type B: 900 / 450 L/s, COP 3.0, 0.79 kW, 17.9 / 8.7 kW | S; quantities M-O6 |
| Water-cooled CRAC (high temperature loop, COP 3.0 assumed) | PTU rooms: 6,500 L/s, 50 L/s OA, 3.3 kW fan, 80.0 kWr, off-coil 16 °C. TX rooms: 2,400 / 30 L/s, 1.2 kW, 29.5 kWr, 16 °C. MMR: 4,200 / 50 L/s, 2.1 kW, 53.8 kWr, 16 °C | S; quantities M-O6 |
| Humidifiers | Type A: 840 / 420 L/s, 15.8 kg/h, 11.9 kW. Type B: 840 / 420 L/s, 16.9 kg/h, 12.7 kW | S; quantities, run hours M-O6 |
| Air-cooled VRF / split | MSR, MSR battery, comms, office, substation; COP 3.0 assumed | S; capacities M-O6 |
| Ventilation | 30 L/s fresh air per switch, PTU, TX, MMR and FCR room via OAFs and outdoor air FCUs; battery room EAFs continuous; constant flow and absorbed power | S; powers M-O6 |
| Room setpoints | TX < 27 °C; PTU / electrical < 27 °C; PTU battery, MSR, MSR battery, MMR, FCR, comms, corridors, tech space, substation rooms < 25 °C; RH < 80 percent, no active humidity control | S |

### 3.4 Electrical, internal loads and other end uses

| Input | Value | Status |
|-|-|-|
| UPS efficiency | 25 percent 95.0; 50 percent 96.0; 75 percent 96.5; 100 percent 97.0 | S |
| UPS losses | Heat to PTU and battery rooms; IT path and non-IT path reported separately | S; non-IT UPS topology M-O7 |
| Transformers | 1 percent for 11 to 22 kV / 400 V; 0.8 percent for 132 / 22 kV; heat to TX rooms | S |
| Distribution | 1 percent of infrastructure electricity; heat to PTU rooms, switch rooms, data halls | S (see I-O7) |
| Internal loads | Office 8 m²/person, 10 W/m² equipment, 8 W/m² lighting; data hall 100 m²/person, 5 W/m²; plant / stairs 5 W/m²; office Class 5 weekday / weekend profiles | S |
| Office fabric | Roof R 3.2, floors R 2.0, glazing U 3.5 and SHGC 0.23 | S; walls R 1.0 vs 1.4 is C (I-O10) |
| Generators | 37 × 3,200 kW / 4,000 kVA and 1 × 680 kW; tests: 875 L/h per generator, 38 generators, 100 percent load, 1 h, 4 per year | S |
| Jacket heaters | 8 kW × 38 generators | S |
| DHW | 9 instantaneous electric heaters, 174.6 kW total, 100 percent efficiency, 60 °C, 8 percent distribution losses, 80,898 kWh/yr | S |
| Ancillary / misc house power | 86.1 MWh/yr (value only) | S |
| PV | 154 kW; 200,095 kWh/yr | S |
| Contingency | 2.5 percent of infrastructure electricity | S |

### 3.5 Reference results (MWh/yr)

The 90 percent column is the source energy table. The 75 / 50 / 25 percent columns are derived (D) from the source emissions table divided by 0.700 kg CO2-e/kWh, the factor implied by 342,166 t / 488,808 MWh; rounding ±1 MWh.

| End use | 90 % | 75 % | 50 % | 25 % | Tier |
|-|-|-|-|-|-|
| IT electricity | 488,808 | 407,340 | 271,560 | 135,780 | T1 |
| Air-cooled chillers | 24,157.8 | 25,699 | 18,611 | 12,730 | T2 (see I-O5) |
| Chilled water pumps (chiller integral) | 10,696.0 | 7,427 | 5,241 | 5,241 | T1 (O-05) |
| CDU pumps | 5,597.6 | 4,664 | 3,110 | 1,554 | T1 (O-04) |
| Transformer losses HV (0.8 %) | 5,234.9 | 4,363 | 2,909 | 1,454 | T1 (O-06) |
| Transformer losses MV/LV (1 %) | 6,543.7 | 5,453 | 3,636 | 1,817 | T1 (O-06) |
| UPS losses IT | 14,664.2 | 14,121 | 10,863 | 7,060 | T1 (O-03) |
| UPS losses non-IT | 1,194.4 | 1,549 | 1,770 | 2,211 | T2 (see I-O6) |
| Switchboard and cable losses (1 %) | 6,543.7 | 5,453 | 3,636 | 1,817 | T1 (O-06) |
| FWU fans | 9,890.8 | 7,151 | 3,950 | 2,010 | T2 |
| Water-cooled DX units | 8,638.6 | 7,241 | 4,891 | 2,523 | T2 |
| Air-cooled DX units and VRF | 1,261.7 | 1,120 | 813 | 496 | T2 |
| Office VRF and split units | 169.7 | 170 | 170 | 170 | T2 |
| Ventilation / central fans | 135.0 | 136 | 136 | 136 | T2 |
| Terminal / local fans | 10,854.2 | 7,781 | 4,189 | 2,091 | T2 (composition M-O8) |
| Exhaust fans | 11.4 | 11 | 11 | 11 | T2 |
| Office lighting | 103.5 | 103 | 103 | 103 | T2 |
| Non-office lighting | 861.3 | 861 | 861 | 861 | T2 |
| Domestic hot water | 80.9 | 81 | 81 | 81 | T1 (input) |
| Lifts | 11.5 | 11 | 11 | 11 | T1 (O-08) |
| Office equipment | 129.4 | 130 | 130 | 130 | T2 |
| Miscellaneous house power | 86.1 | 86 | 86 | 86 | T1 (input) |
| Generator jacket heaters | 1,119.0 | 1,119 | 1,119 | 1,119 | T1 (O-07) |
| Design contingency (2.5 %) | 2,699.6 | 2,404 | 1,694 | 1,129 | T1 (O-09) |
| **Total infrastructure electricity** | **110,685** | **97,134** | **68,021** | **44,841** | T2 |
| PV generation (credit) | 200.1 | 200.1 | 200.1 | 200.1 | T1 (input) |
| Diesel (generator testing) | 133,000 L = 1,426 MWh | same | same | same | T1 (O-02; see I-O4) |
| PUE as reported (emissions ratio) | 1.227 | 1.241 | 1.255 | 1.339 | record only |
| PUE energy ratio, recomputed (incl. diesel 1,426 MWh, net of PV) | 1.229 | 1.241 | 1.255 | 1.339 | T2 |

### 3.6 Deterministic checks (T1)

| ID | Check | Expected |
|-|-|-|
| O-01 | IT energy = installed IT × scenario fraction × 8,760 h | 488,808 MWh at 90 percent with 62.0 MW (490,069 MWh with 62.16 MW; the test sets 62,000 kW, I-O2) |
| O-02 | Diesel = 875 L/h × 38 × 1 h × 4 | 133,000 L; 1,426 MWh at the source's implied 0.010722 MWh/L (0.01076 MWh/L gives 1,431 MWh) |
| O-03 | UPS IT loss with the simplified convention `P_loss = P_out · (1 - η)`, UPS load = IT fraction, efficiency interpolated from the table | Implied loss fractions 3.47 / 4.00 / 5.20 percent of IT at 75 / 50 / 25 percent match `1 - η` at 96.5 / 96.0 / 95.0 percent within 0.2 points; the 90 percent case used 3.00 percent (η = 97.0 percent, the 100 percent point) rather than the interpolated 96.8 percent |
| O-04 | CDU pumps = 710 kW × IT fraction × 8,760 h (power linear with IT load) | 5,597.6 / 4,664 / 3,110 / 1,554 MWh, exact |
| O-05 | Integral CHW pumps = 33 duty × 37 kW × max(f, 0.7)² × 8,760 h, with f = IT fraction / 0.9 (square law, minimum flow 70 percent) | 10,696.0 / 7,427 / 5,241 / 5,241 MWh, within 0.1 percent |
| O-06 | MV/LV transformer and switchboard losses = 1.3387 percent of IT energy; HV = 0.8 / 1.0 of that | Exact at all four loads |
| O-07 | Jacket heaters = 8 kW × 38 × EFLH; EFLH from the EPW with ramp 10 °C (on) to 32 °C (off) | EFLH 3,680 h; 1,119 MWh |
| O-08 | Lifts per GBCA method from the lift table (2.3) | 4,068 + 7,390 = 11,458 kWh |
| O-09 | Contingency = 2.5 percent of the sum of all other infrastructure electricity end uses | 2,699.6 MWh at 90 percent (0.025 × 107,985.4) |
| O-10 | Adiabatic worked point, recirculation added after the pads: T_db 41.4 °C, T_wb 24.0 °C, ε 0.78, +5 K (18 Jan 13:00) | Pad outlet 27.8 °C (source 27.9), condenser inlet 32.8 °C (source 32.9) |
| O-11 | Hours with T_db ≥ 31 °C in the EPW | 157 h |

### 3.7 Missing data

| ID | Item |
|-|-|
| M-O1 | Modelled liquid / air split per hall |
| M-O2 | Chiller manufacturer performance table at the project CHW temperatures (24 / 34 and 26 / 36 °C) |
| M-O3 | Whether the chillers have integrated free cooling |
| M-O4 | How one plant produces 24 °C and 26 °C supply (requirements Section 12 arrangement) |
| M-O5 | CHW supply temperature reset |
| M-O6 | Quantities and schedules of FWUs, PACs, CRACs, humidifiers, VRF / split units, OAFs, EAFs, outdoor air FCUs |
| M-O7 | UPS topology and which loads sit on the non-IT UPS |
| M-O8 | What "terminal / local fans" contains (10,854 MWh at 90 percent, larger than the FWU fans) |

### 3.8 Inconsistencies in the source

| ID | Inconsistency |
|-|-|
| I-O1 | Design stage stated differently in the document label (75 percent) and the text (60 percent) |
| I-O2 | Installed IT 62.16 MW, but IT energy uses 62.0 MW |
| I-O3 | CDU "up to 70 percent" plus FWU "up to 40 percent" exceeds 100 percent |
| I-O4 | Reduced-load tables use 998 t CO2-e for generator testing; base case uses 450 t for the same 133,000 L |
| I-O5 | Air-cooled chiller energy at 75 percent IT (25,699 MWh) exceeds that at 90 percent (24,158 MWh) |
| I-O6 | Non-IT UPS losses rise as IT load falls (1,194 to 2,211 MWh) |
| I-O7 | Switchboard loss is stated as 1 percent of infrastructure electricity (about 1,080 MWh) but equals the MV/LV transformer loss (6,543.7 MWh) |
| I-O8 | CDU pumps are described as constant but scale linearly with IT load (O-04) |
| I-O9 | The 90 percent UPS IT loss uses the 100 percent efficiency point (O-03) |
| I-O10 | Office external wall R 1.0 (input summary) vs R 1.4 (fabric table) |

## 4. DC_S1: 192 MW, single 28 to 38 °C loop, free-cooling air-cooled chillers

Closest preset: `LC-ACC-IFC` (WS-1, CP-2); adiabatic status conflicting.

**Use of this case**: input-definition, scale and robustness case (T1 checks on inputs, T3). The source's results section is **not usable as a reference**: its result tables use 488,808 MWh/yr of IT energy (a 62 MW basis, identical to DC_O1) and many end uses identical to DC_O1, while 192 MW at 90 percent gives 1,513,728 MWh/yr. The source appears to be a work-in-progress draft carrying over another project's results. Reported headline values, for information only: PUE 1.30 at 90 percent; 1.31 / 1.34 / 1.45 at 75 / 50 / 25 percent; peak instantaneous PUE 1.40. DC_S1 is promoted to a full reference case (T2 bands as DC_O1) when corrected results are available.

### 4.1 Inputs

| Input | Value | Status |
|-|-|-|
| Data halls | 16 × 12 MW (8 per level on two levels); 192 MW; base case 172.8 MW | S |
| Hall types | Network halls modelled FWU 50 % / CDU 50 %; server halls modelled FWU 40 % / CDU 60 % (design: CDU up to 90 %, FWU up to 46 % network, 40 % server) | S; number of each hall type M |
| Cold aisle | 27.5 °C supply, air ΔT 10.6 K, RH < 80 %; FWU table states supply / return 32 / 43 °C | C |
| Chillers | 168 free-cooling air-cooled chillers, 1,200 kW each, 295 kW absorbed at design including 27 kW integral CHW pump; 8 loops × 21 (20 duty + 1 standby), each loop serving 2 paired 12 MW halls; sized to 90 % IT | S |
| Chiller derived values | COP 4.07 including pump (1,200 / 295), 4.48 excluding pump (1,200 / 268); rating conditions not stated | D; M |
| Chiller conflicting text | A paragraph repeats DC_O1's chiller data (COP 4.80 at 32 / 24 °C, 2,200 kW nominal unit, 37 kW pump) and the chiller block table (38 units) is DC_O1's | C |
| Loop | Single CHW loop 28 / 38 °C to CDUs and room units | S |
| CHW reset | 24 °C at ambient ≤ 26 °C, linear to 28 °C at 41 °C, 28 °C above (chart) | S |
| Recirculation | +2.7 K on condenser entering air (from CFD) | S |
| Adiabatic | Input summary and recommendations mention adiabatic chillers; chiller table says "Dry"; no adiabatic parameters | C |
| CDUs | 6 per hall, 4 active + 2 standby (text also says "2N+1, 3 per system"); 2,700 kW (text) or 2,752 kW (table) net; 52 kW absorbed; primary 28 / 38 °C; TCS 32 / 42 °C, propylene glycol 25 %; UPS-backed | S / C |
| FWUs | Type 1: 37,000 L/s, 475 kW coil, 34 kW. Type 2: 35,000 L/s, 450 kW, 28.1 kW. EC, 30 % minimum turndown, fan curve 2.2 | S; quantities M |
| CRAC (4 types) | 6,383 L/s, 80.7 kW total / 60 net, 24.2 kW; 9,787 L/s, 127 / 92 kW, 38.5 kW; MMR type 1 3,420 L/s, 41.1 / 38.1 kW, 17.9 kW incl. condenser; MMR type 2 2,780 L/s, 36.51 / 34.4 kW, 13.9 kW incl. condenser | S; air-cooled vs water-cooled description C; quantities M |
| CRAH | 6,638 L/s, 64 / 60 kW, 3.4 kW fan; on CHW loop | S; quantity M |
| Data hall air units | 26.5 kW, 1,400 L/s, 0.81 kW; 2 OA fans per hall at fixed volume | S |
| FCUs | MV switchboard room: 12.8 kW, 485 L/s, 0.2 kW. Battery room: 6.5 kW, 265 L/s, 0.1 kW | S; quantities M |
| DX / VRF | COP 3.0 assumed | S |
| Room setpoints | IT / mechanical lineup and catcher electrical rooms < 40 °C; mechanical lineup and catcher UPS battery rooms < 28 °C; MV rooms < 35 °C; MMR < 27 °C | S |
| UPS | 2 × 1,500 kW 415 V in parallel per lineup, supporting 3,000 kW of critical mechanical load (FWUs, CDUs), 4 min battery | S; number of lineups M |
| UPS efficiency | 25 to 100 % in 5 % steps: 88.0, 89.5, 91.0, 92.0, 92.5, 92.7, 93.1, 93.6, 94.0, 94.2, 94.5, 94.9, 95.3, 95.5, 95.7, 96.0 | S |
| Transformers | 1 % for 11 kV / 415 V; 0.5 % for 330 / 11 kV (results label 0.8 %) | C |
| Distribution | 1 % of infrastructure electricity | S |
| Areas | Data hall 21,875 m²; electrical / supporting 1,970 m²; circulation 1,282 m²; total 25,127 m² (same figures as DC_O1's different space types) | C |
| Internal loads | 5 W/m² data hall and electrical / plant / circulation | S |
| Generators | Test table: 38 generators at 102,968 L/h (not plausible per generator), 411,872 L/yr; jacket heater total 944 kW, which implies 118 × 8 kW; results use DC_O1's 133,000 L and 1,119 MWh | C; generator count M |
| Jacket heaters | 944 kW total, EFLH 3,680 h, 3,474 MWh/yr | S (count C) |
| Lifts | As 2.3: 11,458 kWh/yr | S |
| PV | 135 kW; 175,407 kWh/yr (same specific yield as DC_O1) | S |
| Contingency | 5 % (text) vs 10 % (results row) | C |

### 4.2 Deterministic checks (T1)

| ID | Check | Expected |
|-|-|-|
| S-01 | IT energy | 1,513,728 / 1,261,440 / 840,960 / 420,480 MWh at 90 / 75 / 50 / 25 % |
| S-02 | UPS efficiency interpolation at table points | Exact table values |
| S-03 | CHW reset | 24.0 °C at 26 °C ambient and below; 26.0 °C at 33.5 °C; 28.0 °C at 41 °C and above |
| S-04 | Dry mode condenser entering air | T_db + 2.7 K |
| S-05 | Jacket heaters | 944 kW × EFLH (3,680 h from the EPW, O-07 method) = 3,474 MWh |
| S-06 | Loop capacity (design-check output) | Per loop 20 × 1,200 = 24,000 kW duty against 2 × 12 MW × 0.9 = 21,600 kW IT plus air-side gains, fan and pump heat; the margin at design ambient + 2.7 K is reported |

### 4.3 Missing data before DC_S1 can be a full reference

Corrected results; number of network vs server halls; chiller performance data and rating conditions; adiabatic yes / no; CDU count and capacity; quantities of FWUs, CRACs, CRAHs, FCUs, VRF / split units; UPS lineup count; generator count and fuel rate; contingency; transformer HV percentage; floor areas.

## 5. Implications for the requirements

Findings from the extraction that the requirements do not yet cover. Listed here for decision; not yet applied to `docs/NEW_TOOL_REQUIREMENTS.md`.

| ID | Finding | Suggested requirement |
|-|-|-|
| R-1 | DC_O1 adds condenser recirculation **after** the adiabatic pads (O-10); the requirements currently add it before | Make the order configurable, default after the pads |
| R-2 | Both sources compute UPS loss as `P_out · (1 - η)`, not the physical `P_out · (1/η - 1)` | UPS loss convention option, physical by default, simplified to reproduce references |
| R-3 | DC_O1 transformer and switchboard losses scale with IT energy (1.339 percent of IT) instead of the stated basis | Loss basis stated explicitly per element (named throughput or loss model) |
| R-4 | DC_O1 CDU pumps scale linearly with IT load and CHW pumps follow a square law with a 70 percent floor (O-04, O-05) | Confirms the part-load framework; both are expressible with existing curves and PLR methods |

## 6. Open items

1. DC_O1 missing data M-O1 to M-O8, and the test EPW file.
2. A corrected revision of the DC_S1 source, if available.
3. Whether the test cases should reproduce the sources' conventions (R-2, R-3, R-4) or use the tool's physical defaults and report the differences.
4. Whether R-1 to R-3 should be added to the requirements.
