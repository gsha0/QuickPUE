"""Project loading: YAML / Python inputs, source attribution (REQ-ATTR-1 to 3), unit conversion,
topology presets and minimum-input expansion (8.4)."""

from __future__ import annotations

import copy
import importlib.util
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from .schema import Project

SOURCE_KINDS = ("document", "inference", "designer", "assumption", "pending_manufacturer")
_ATTR_KEYS = {"value", "unit", "source", "note"}

# unit conversion to the unit implied by the field-name suffix
_CONV = {
    "kw": {"w": 1e-3, "kw": 1.0, "mw": 1e3},
    "kwh": {"wh": 1e-3, "kwh": 1.0, "mwh": 1e3, "gwh": 1e6},
    "l_s": {"l/s": 1.0, "m3/s": 1e3, "m3/h": 1.0 / 3.6, "l_s": 1.0},
    "pa": {"pa": 1.0, "kpa": 1e3},
    "m2": {"m2": 1.0, "m²": 1.0},
    "m": {"m": 1.0, "mm": 1e-3},
    "c": {"c": 1.0, "degc": 1.0, "°c": 1.0},
    "k": {"k": 1.0},
    "l": {"l": 1.0, "kl": 1e3, "ml": 1e6},
    "pct": {"%": 1.0, "percent": 1.0},
}


@dataclass
class RegisterEntry:
    path: str
    value: Any
    unit: str = ""
    kind: str = "unspecified"
    ref: str = ""
    note: str = ""
    origin: str = "user"  # user | preset | default | auto


@dataclass
class LoadedProject:
    project: Project
    register: dict[str, RegisterEntry]
    base_dir: Path
    source_path: str
    preset: dict | None = None
    assumptions: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
def _unit_for(key: str) -> str | None:
    k = key.lower()
    for suf in ("kwh", "l_s", "kw", "pa", "m2", "pct"):
        if k.endswith("_" + suf):
            return suf
    for suf in ("c", "k", "m", "l"):
        if k.endswith("_" + suf):
            return suf
    return None


def _convert(value, unit, key, path):
    if unit is None or value is None or isinstance(value, (str, bool, list, dict)):
        return value, unit or ""
    target = _unit_for(key)
    u = str(unit).strip().lower().replace(" ", "")
    if target is None:
        return value, unit
    table = _CONV.get(target, {})
    if u not in table:
        raise ValueError(f"{path}: unit {unit!r} not convertible to the field unit ({target})")
    return float(value) * table[u], target


def _strip(obj, path: str, register: dict, origin: str, preset_id: str | None = None):
    """Replace {value, unit, source} dicts with plain values and record them in the register."""
    if isinstance(obj, dict):
        if "value" in obj and set(obj) <= _ATTR_KEYS:
            key = path.rsplit(".", 1)[-1]
            val, unit = _convert(obj["value"], obj.get("unit"), key, path)
            src = obj.get("source") or {}
            if isinstance(src, str):
                src = {"kind": src}
            kind = src.get("kind", "unspecified")
            if kind not in SOURCE_KINDS and kind != "unspecified":
                raise ValueError(f"{path}: source.kind must be one of {SOURCE_KINDS}")
            if origin == "preset" and kind == "unspecified":
                kind = "assumption"
            register[path] = RegisterEntry(path, val, unit, kind, src.get("ref", preset_id or ""),
                                           obj.get("note", ""), origin)
            return _strip(val, path, register, origin, preset_id) if isinstance(val, (dict, list)) else val
        return {k: _strip(v, f"{path}.{k}" if path else k, register, origin, preset_id) for k, v in obj.items()}
    if isinstance(obj, list):
        out = []
        for i, v in enumerate(obj):
            tag = v.get("name") if isinstance(v, dict) and isinstance(v.get("name"), (str, dict)) else i
            if isinstance(tag, dict):
                tag = tag.get("value", i)
            out.append(_strip(v, f"{path}[{tag}]", register, origin, preset_id))
        return out
    if origin == "preset" and path not in register:
        register[path] = RegisterEntry(path, obj, _unit_for(path.rsplit(".", 1)[-1]) or "", "assumption",
                                       preset_id or "preset", "preset default", "preset")
    return obj


def _flatten_user(obj, path: str, register: dict):
    """Record plain user leaf values (not already attributed)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten_user(v, f"{path}.{k}" if path else k, register)
    elif isinstance(obj, list) and obj and isinstance(obj[0], dict):
        for i, v in enumerate(obj):
            tag = v.get("name", i) if isinstance(v, dict) else i
            _flatten_user(v, f"{path}[{tag}]", register)
    else:
        if path not in register or register[path].origin != "user":
            register[path] = RegisterEntry(path, obj, _unit_for(path.rsplit(".", 1)[-1]) or "", "unspecified", "",
                                           "", "user")


def deep_merge(base: Any, over: Any) -> Any:
    """Merge user values over a preset template. Lists of named dicts merge by name; items with
    ``_remove: true`` delete the preset item."""
    if isinstance(base, dict) and isinstance(over, dict):
        out = dict(base)
        for k, v in over.items():
            out[k] = deep_merge(base[k], v) if k in base else v
        return out
    if isinstance(base, list) and isinstance(over, list) and all(isinstance(x, dict) and "name" in x for x in base) \
            and all(isinstance(x, dict) and "name" in x for x in over):
        by = {x["name"]: x for x in base}
        out = []
        seen = set()
        for b in base:
            o = next((x for x in over if x["name"] == b["name"]), None)
            if o is None:
                out.append(b)
            elif not o.get("_remove"):
                out.append(deep_merge(b, {k: v for k, v in o.items() if k != "_remove"}))
            seen.add(b["name"])
        for o in over:
            if o["name"] not in by and not o.get("_remove"):
                out.append(o)
        return out
    return copy.deepcopy(over)


# ---------------------------------------------------------------------------
def preset_dir():
    return resources.files("quickpue.presets")


def list_presets() -> list[dict]:
    out = []
    for f in sorted(preset_dir().iterdir(), key=lambda p: p.name):
        if f.name.endswith(".yaml") and not f.name.startswith("_"):
            d = yaml.safe_load(f.read_text())
            out.append({k: d.get(k) for k in ("id", "name", "water_system", "plant_type", "dcoptest", "description")})
    return out


def load_preset(preset_id: str, user_dir: Path | None = None) -> dict:
    candidates = []
    if user_dir:
        candidates += [user_dir / f"{preset_id}.yaml", user_dir / "presets" / f"{preset_id}.yaml"]
    for c in candidates:
        if c.exists():
            return yaml.safe_load(c.read_text())
    f = preset_dir().joinpath(f"{preset_id}.yaml")
    if not f.is_file():
        ids = ", ".join(p["id"] for p in list_presets())
        raise ValueError(f"unknown preset {preset_id!r}; available: {ids}")
    d = yaml.safe_load(f.read_text())
    base = d.get("extends")
    if base:
        parent = load_preset(base, user_dir)
        d["template"] = deep_merge(parent.get("template", {}), d.get("template", {}))
        for k in ("water_system", "plant_type"):
            d.setdefault(k, parent.get(k))
    return d


def _expand_minimum(raw: dict, preset: dict | None) -> dict:
    """Minimum-input mode: an ``it`` block creates / fills the preset's data hall (8.4)."""
    it = raw.get("it")
    if not it:
        return raw
    if isinstance(it, dict) and any(isinstance(v, dict) and "value" in v for v in it.values()):
        it = {k: (v["value"] if isinstance(v, dict) and "value" in v else v) for k, v in it.items()}
    halls = raw.get("halls")
    n_halls = int(it.get("halls", 1))
    hall_name = (preset or {}).get("hall_name", "Data hall")
    if not halls:
        h = {"name": hall_name, "count": n_halls, "it_kw": float(it["installed_kw"]) / n_halls,
             "liquid_fraction": float(it.get("liquid_fraction", 0.0))}
        if it.get("area_m2"):
            h["area_m2"] = float(it["area_m2"]) / n_halls
        if it.get("height_m"):
            h["height_m"] = float(it["height_m"])
        raw = dict(raw)
        raw["halls"] = [h]
    return raw


def load_project(path_or_dict, base_dir: str | Path | None = None) -> LoadedProject:
    """Load a project from YAML, a Python file (defining PROJECT or project()), a dict or a Project."""
    if isinstance(path_or_dict, Project):
        return LoadedProject(path_or_dict, {}, Path(base_dir or "."), "<object>")
    if isinstance(path_or_dict, dict):
        raw = copy.deepcopy(path_or_dict)
        src = "<dict>"
        bdir = Path(base_dir or ".")
    else:
        p = Path(path_or_dict)
        bdir = Path(base_dir) if base_dir else p.resolve().parent
        src = str(p)
        if p.suffix in (".yaml", ".yml"):
            raw = yaml.safe_load(p.read_text()) or {}
        elif p.suffix == ".json":
            raw = json.loads(p.read_text())
        elif p.suffix == ".py":
            spec = importlib.util.spec_from_file_location("quickpue_user_project", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # user's own project script (D10)
            obj = getattr(mod, "PROJECT", None)
            if obj is None and hasattr(mod, "project"):
                obj = mod.project()
            if obj is None:
                raise ValueError(f"{p}: define PROJECT (dict) or project() in the Python input file")
            if isinstance(obj, Project):
                return LoadedProject(obj, {}, bdir, src)
            raw = copy.deepcopy(obj)
        else:
            raise ValueError(f"{p}: input files are YAML (.yaml) or Python (.py) (D10)")

    register: dict[str, RegisterEntry] = {}
    preset = None
    preset_id = raw.get("preset")
    if isinstance(preset_id, dict):
        preset_id = preset_id.get("value")
    if preset_id:
        preset = load_preset(preset_id, bdir)
        template = _strip(copy.deepcopy(preset.get("template", {})), "", register, "preset", f"preset {preset_id}")
        user = _strip(raw, "", register, "user")
        _flatten_user({k: v for k, v in user.items() if k != "preset"}, "", register)
        user = _expand_minimum(user, preset)
        merged = deep_merge(template, user)
        if preset.get("water_system") and "water_system" not in user:
            merged["water_system"] = preset["water_system"]
    else:
        merged = _strip(raw, "", register, "user")
        _flatten_user(merged, "", register)
        merged = _expand_minimum(merged, None)
    project = Project.model_validate(merged)
    lp = LoadedProject(project, register, bdir, src, preset, raw=raw)
    if preset:
        lp.assumptions.append(f"Topology preset {preset['id']}: {preset.get('name', '')}. "
                              f"Every preset value is listed in the input register as an assumption.")
    return lp
