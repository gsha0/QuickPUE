"""Equation and data source register (requirements Section 15).

Every equation and default used by the engine carries one of these IDs in the
code, in the calculation report and in ``explain`` output.
"""

from __future__ import annotations

SOURCES: dict[str, dict[str, str]] = {
    "S-EQ-01": {
        "item": "Liquid / air heat split Q_liq = f_liq * P_IT",
        "source": "Decision D11; [KO26] Eq. 1 with f_liq = 1 - phi",
    },
    "S-EQ-02": {
        "item": "Loop and TCS energy balances, CDU approach, LMTD, junction temperature",
        "source": "[KO26] Eq. 2 to 9",
    },
    "S-EQ-03": {
        "item": "Chiller EIR model: Q_avail = Q_ref*CAPFT; P = Q_avail/COP_ref*EIRFT*EIRFPLR(PLR)",
        "source": "[EP-ER] Electric EIR chiller (DOE-2 formulation)",
    },
    "S-EQ-04": {
        "item": "Pump part-load power FFLP = C1 + C2*PLR + C3*PLR^2 + C4*PLR^3, PLR = V/V_nom",
        "source": "[EP-IO] Pump:VariableSpeed; [EP-ER] Variable Speed Pump",
    },
    "S-EQ-05": {
        "item": "Fan part-load power PLF = C1 + C2*FF + C3*FF^2 + C4*FF^3 + C5*FF^4",
        "source": "[EP-IO] Fan:VariableVolume; Fan:SystemModel with Curve:Quartic",
    },
    "S-EQ-06": {
        "item": "Fan coefficient sets (Var. Speed Motor, Inlet Vane Dampers, Discharge Dampers, VAV example)",
        "source": "[EP-IO] Table 'Fan Coefficient Values' and Fan:SystemModel example",
    },
    "S-EQ-07": {
        "item": "Differential pressure control curve s*f + (1 - s)*f^3",
        "source": "Derived from affinity laws and system curve (requirements 11.3.1)",
    },
    "S-EQ-08": {
        "item": "Motor and VFD part-load efficiency (k_drive)",
        "source": "[EP-ER] Fan:ComponentModel (Stein and Hydeman; DOE MotorMaster+; DOE 2008)",
    },
    "S-EQ-09": {
        "item": "Headered pump sequential power (R-EPSEQ)",
        "source": "[EP-ER] Headered pumps",
    },
    "S-EQ-10": {
        "item": "Cooling tower effectiveness-NTU with effective saturated-air specific heat (Merkel); "
        "UA scaled with air and water flow ratios; minimum air flow rate ratio 0.2; "
        "design air flow 2.76316e-5 m3/s per W and fan power 0.0105 W/W defaults",
        "source": "[EP-ER] cooling towers (SimpleTower / Merkel variable speed); [EP-IO] CoolingTower:VariableSpeed:Merkel",
    },
    "S-EQ-11": {
        "item": "Dry cooler / free cooling coil effectiveness-NTU, cross flow both fluids unmixed; UA(f) = UA_des*f^n",
        "source": "Heat transfer texts (Incropera, cross-flow both unmixed approximation); exponent n user editable, default 0.6 (assumption)",
    },
    "S-EQ-12": {
        "item": "Adiabatic effective entering temperature T_eff = T - eps*(T - T_wb); recirculation order configurable",
        "source": "Saturation efficiency definition; [NKB] adiabatic method; TEST_CASES R-1",
    },
    "S-EQ-13": {
        "item": "Psychrometrics (Hyland-Wexler saturation pressure, humidity ratio, enthalpy, wet bulb), WUE, COC, drift",
        "source": "ASHRAE Handbook Fundamentals (2017) Ch. 1; DCOPTEST README 9.1 and 9.2",
    },
    "S-EQ-14": {
        "item": "Scenario set (90 / 75 / 50 / 25), infiltration, internal loads, loss allowances used as defaults",
        "source": "[NKB]",
    },
    "S-EQ-15": {
        "item": "ASHRAE 90.1 Appendix G VAV fan curve",
        "source": "ASHRAE 90.1 Appendix G; verify edition (requirements 11.3.1)",
    },
    "S-EQ-16": {
        "item": "Generator diesel energy 0.01076 MWh/L; jacket heater ramp clamp((T_off - T)/(T_off - T_on), 0, 1)",
        "source": "[NKB]",
    },
    "S-EQ-17": {
        "item": "PUE (energy ratio), WUE, optional GHG = energy x user factor",
        "source": "The Green Grid PUE definition; [KO26] Eq. 10 and 11; D14",
    },
    "S-EQ-18": {
        "item": "UPS loss: physical P_out*(1/eta - 1) (default) or simplified P_out*(1 - eta)",
        "source": "Efficiency definition eta = P_out/P_in; simplified convention per TEST_CASES R-2",
    },
    "S-EQ-19": {
        "item": "Transformer loss: percent of named throughput, or no-load + full-load*(S/S_rated)^2",
        "source": "IEC 60076 loss definition; basis per element per TEST_CASES R-3",
    },
    "S-EQ-20": {
        "item": "Zone sensible load: losses + equipment + lighting + people + UA*(T_out - T_set) + infiltration + OA + fan heat",
        "source": "Steady-state heat balance (requirements 10.9)",
    },
    "S-EQ-21": {
        "item": "DX / PAC power P = Q / COP(T, PLR); condenser heat Q + P",
        "source": "First law; [NKB] room unit practice (COP 3.0 default)",
    },
    "S-EQ-22": {
        "item": "Lift energy E = trips * P * t_trip / 3600 * running_factor + standby_kW * standby_h",
        "source": "Approximation of the GBCA lift calculator; running_factor default 0.75 (assumption); "
        "reproduces TEST_CASES O-08 within 0.3 percent",
    },
    "S-EQ-23": {
        "item": "Chiller curve normalization to a project rated point by temperature shift and inputs clamped to curve limits",
        "source": "EnergyPlus curve input limiting behaviour; requirements IN-CH-4(c)",
    },
    "S-EQ-24": {
        "item": "Loop blending (DT-A), HX cascade (DT-B), dedicated (DT-C), split duty (DT-D) mass and energy balances",
        "source": "Requirements Section 12",
    },
    "S-DEF-01": {
        "item": "Default chiller curve analogues",
        "source": "EnergyPlus datasets AirCooledChiller.idf and Chillers.idf (NREL/EnergyPlus develop); "
        "rated near standard CHW conditions; extrapolation flagged",
    },
    "S-DEF-02": {
        "item": "Default pump design power 348,701.1 W per m3/s (22 W/gpm)",
        "source": "[EP-IO] Pump:VariableSpeed Design Electric Power per Unit Flow Rate default",
    },
    "S-DEF-03": {
        "item": "Default fan design power 1.66667 W per (m3/s * Pa)",
        "source": "[EP-IO] Fan:SystemModel Electric Power Per Unit Flow Rate Per Unit Pressure default",
    },
    "S-DEF-04": {
        "item": "Water and glycol properties (rounded cp, density vs concentration)",
        "source": "ASHRAE Handbook Fundamentals Ch. 31 (rounded values near 20 C; assumption)",
    },
    "S-DEF-05": {
        "item": "Preset defaults and auto-sizing rules",
        "source": "Requirements 8.4.2 (proposed rules, to confirm)",
    },
}


def describe(source_id: str) -> str:
    s = SOURCES.get(source_id)
    if not s:
        return source_id
    return f"{source_id}: {s['item']} [{s['source']}]"
