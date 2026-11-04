"""Batch study example (REQ-UI-2: `quickpue batch examples/studies.py`).

Design option comparison (UC-2): one preset, CHW supply temperature and adiabatic pads varied.
Each entry is a project dict (or a path to a YAML file).
"""

import copy

EPW = "../tests/data/AUS_NSW_Horsley.Equestrian.Centre.947600_TMYx.2011-2025.epw"

BASE = {
    "preset": "LC-ACC-IFC-AD",
    "project": {"name": "Option study"},
    "weather": {"epw": EPW},
    "it": {"installed_kw": 10000, "liquid_fraction": 0.8},
    "scenarios": [{"name": "90%", "it_fraction": 0.9}, {"name": "50%", "it_fraction": 0.5}],
}


def variant(supply_c, adiabatic=True):
    d = copy.deepcopy(BASE)
    d["project"]["name"] = f"CHW {supply_c} C, adiabatic {'on' if adiabatic else 'off'}"
    d["loops"] = [{"name": "CHW", "supply_c": supply_c, "return_c": supply_c + 10}]
    if not adiabatic:
        d["plants"] = [{"name": "Plant", "chillers": [{"name": "ACC", "adiabatic": {"enabled": False,
                                                                                   "activation_c": 30,
                                                                                   "efficiency": 0.8}}]}]
    return d


STUDIES = {
    "chw20": variant(20.0),
    "chw24": variant(24.0),
    "chw28": variant(28.0),
    "chw24_dry": variant(24.0, adiabatic=False),
}
