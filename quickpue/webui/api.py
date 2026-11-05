"""JSON API behind the web input editor.

Everything here is read-only use of the QuickPUE package: the pydantic schema, topology presets, the
part-load curve and schedule libraries, the EPW reader, ``load_project`` and ``prepare`` (the same
checks as ``quickpue validate``). Nothing here runs the hourly simulation or changes an engine, sizing,
schema or preset value. File writes are limited to project YAML files inside the editor root directory.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
from dataclasses import asdict
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from .. import __version__
from ..chiller import library as chiller_library
from ..curves import FFLP_LIBRARY, make_fflp
from ..engine import END_USES
from ..inputs import _CONV, SOURCE_KINDS, list_presets, load_preset, load_project
from ..schedules import LIBRARY as PROFILE_LIBRARY
from ..schema import SCHEMA_VERSION, Project
from ..weather import design_point, monthly_summary, read_epw

# Loss allocation aliases accepted by the engine (Engine._loss_alloc_static is authoritative; this list
# only feeds the key suggestions in the editor, and the full check reports any key the engine rejects).
LOSS_ALIASES = ["pdu", "ups", "ups_it", "ups_mech", "transformer", "transformer_hv", "transformer_mvlv",
                "distribution"]

PROJECT_SUFFIXES = (".yaml", ".yml", ".json")
_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache", "build", "dist"}
_MAX_FILES = 500
_PROJECT_HINT = re.compile(r"^(weather|preset|halls|plants)\s*:", re.M)


class ApiError(Exception):
    """Error reported to the browser with an HTTP status."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def inside(root: Path, rel: str) -> Path:
    """Resolve ``rel`` against ``root`` and refuse anything outside it."""
    if rel is None or str(rel).strip() == "":
        raise ApiError("no path given")
    p = (root / rel).resolve()
    r = root.resolve()
    if p != r and r not in p.parents:
        raise ApiError(f"{rel}: outside the editor root directory {r}", 403)
    return p


def base_dir_for(root: Path, project_path: str | None) -> Path:
    """Directory that relative paths in a project resolve against (the project file's folder)."""
    if project_path:
        return inside(root, project_path).parent
    return root.resolve()


def _rel(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start)).as_posix()


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def _models(model: type[BaseModel], seen: dict[str, type[BaseModel]]):
    if model.__name__ in seen:
        return
    seen[model.__name__] = model
    for info in model.model_fields.values():
        for t in _types_in(info.annotation):
            if isinstance(t, type) and issubclass(t, BaseModel):
                _models(t, seen)


def _types_in(annotation):
    args = getattr(annotation, "__args__", None)
    if not args:
        return [annotation]
    out = []
    for a in args:
        out += _types_in(a)
    return out


def _jsonable(v):
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


def ui_schema() -> dict:
    """Pydantic JSON schema plus the values of ``default_factory`` defaults (which JSON schema omits),
    so the editor can show every default as a placeholder without writing it into the project."""
    schema = Project.model_json_schema()
    seen: dict[str, type[BaseModel]] = {}
    _models(Project, seen)
    for name, model in seen.items():
        target = schema if name == "Project" else schema.get("$defs", {}).get(name)
        if not target:
            continue
        props = target.get("properties", {})
        for fname, info in model.model_fields.items():
            if fname in props and info.default_factory is not None and "default" not in props[fname]:
                v = info.default_factory()
                if isinstance(v, BaseModel):
                    v = v.model_dump(mode="json")
                elif isinstance(v, tuple):
                    v = list(v)
                if _jsonable(v):
                    props[fname]["default"] = v
    return schema


def meta(root: Path, initial: str | None = None) -> dict:
    presets = list_presets()
    chillers = []
    for k, v in chiller_library().items():
        chillers.append({"id": k, "label": v.get("entry", k), "kind": v.get("kind", ""),
                         "ref_cop": v.get("ref_cop"), "ref_capacity_kw": (v.get("ref_capacity_w") or 0) / 1000.0})
    out_sets = sorted(x.name[:-5] for x in resources.files("quickpue.output_sets").iterdir()
                      if x.name.endswith(".yaml"))
    return {
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "schema": ui_schema(),
        "presets": presets,
        "source_kinds": list(SOURCE_KINDS),
        "units": {suffix: list(table) for suffix, table in _CONV.items()},
        "fflp": [{"id": k, "label": v["label"], "source": v["source"]} for k, v in FFLP_LIBRARY.items()],
        "profiles": {k: {"weekday": v["weekday"], "weekend": v["weekend"], "source": v["source"]}
                     for k, v in PROFILE_LIBRARY.items()},
        "chiller_library": chillers,
        "end_uses": {k: v[0] for k, v in END_USES.items()},
        "loss_aliases": LOSS_ALIASES,
        "output_sets": out_sets,
        "root": str(root.resolve()),
        "initial": initial,
    }


def preset(preset_id: str, root: Path, project_path: str | None = None) -> dict:
    try:
        d = load_preset(preset_id, base_dir_for(root, project_path))
    except ValueError as e:
        raise ApiError(str(e), 404) from e
    return {k: d.get(k) for k in ("id", "name", "description", "water_system", "plant_type", "dcoptest",
                                  "hall_name")} | {"template": d.get("template", {})}


# ---------------------------------------------------------------------------
# Validation (schema, links and sizing; no hourly simulation)
# ---------------------------------------------------------------------------
_TAG = re.compile(r"^[\w-]+\[.*\]$|^(str|int|float|bool|dict|list|none|literal\[.*\])$", re.I)


def _clean_loc(loc, model_names: set[str]) -> list:
    """Drop pydantic union and validator tags from an error location."""
    out = []
    for seg in loc:
        if isinstance(seg, str) and (seg in model_names or _TAG.match(seg)):
            continue
        out.append(seg)
    return out


def _errors(e: ValidationError) -> list[dict]:
    """Pydantic errors with union tags removed. Union branches failing at one location are joined into
    one message, and a literal mismatch is dropped when another branch reports a deeper error."""
    names = set(Project.model_json_schema().get("$defs", {})) | {"Project"}
    by_loc: dict[tuple, dict] = {}
    for err in e.errors():
        loc = tuple(_clean_loc(err.get("loc", ()), names))
        msg = err.get("msg", "")
        msg = msg[len("Value error, "):] if msg.startswith("Value error, ") else msg
        d = by_loc.setdefault(loc, {"loc": list(loc), "msgs": [], "type": err.get("type", "")})
        if msg not in d["msgs"]:
            d["msgs"].append(msg)
    out = []
    for loc, d in by_loc.items():
        deeper = any(len(o) > len(loc) and o[:len(loc)] == loc for o in by_loc)
        if deeper and d["type"] == "literal_error":
            continue
        out.append({"loc": d["loc"], "msg": " or ".join(d["msgs"]), "type": d["type"]})
    return out


def check(project: dict, root: Path, project_path: str | None = None, full: bool = True) -> dict:
    """Validate a project dict. ``full`` adds the preparation step of ``quickpue validate`` (EPW read,
    auto-sizing design passes, engine construction), which also yields the input register, the static
    warnings and the electrical loss heat allocation as the engine resolves it."""
    if not isinstance(project, dict):
        raise ApiError("project must be a mapping")
    base = base_dir_for(root, project_path)
    res: dict[str, Any] = {"ok": False, "stage": "schema", "errors": [], "warnings": [], "assumptions": [],
                           "register": [], "loss_alloc": None, "design_label": None, "full": full}
    try:
        lp = load_project(copy.deepcopy(project), base_dir=base)
    except ValidationError as e:
        res["errors"] = _errors(e)
        return res
    except Exception as e:  # noqa: BLE001  (any loader error is reported to the user)
        res["stage"] = "load"
        res["errors"] = [{"loc": [], "msg": f"{e}", "type": type(e).__name__}]
        return res
    res["assumptions"] = list(lp.assumptions)
    if not full:
        res["ok"] = True
        res["stage"] = "schema"
        res["register"] = [_entry(e) for e in sorted(lp.register.values(), key=lambda e: e.path)]
        return res
    from ..runner import _build_register, prepare

    res["stage"] = "sizing"
    try:
        w, sized, design, label, log, eng, _ = prepare(lp)
    except FileNotFoundError as e:
        res["errors"] = [{"loc": ["weather", "epw"], "msg": f"weather file not found: {e.filename or e}",
                          "type": "FileNotFoundError"}]
        return res
    except ValidationError as e:
        res["errors"] = _errors(e)
        return res
    except KeyError as e:
        res["errors"] = [{"loc": [], "msg": f"unknown name {e.args[0]!r}: check the loop, hall and zone references",
                          "type": "KeyError"}]
        return res
    except Exception as e:  # noqa: BLE001
        res["errors"] = [{"loc": [], "msg": f"{e}", "type": type(e).__name__}]
        return res
    res["ok"] = True
    res["stage"] = "complete"
    res["design_label"] = label
    res["warnings"] = list(dict.fromkeys(list(w.warnings) + list(eng.warn_static)))
    res["assumptions"] += list(log.notes)
    res["register"] = [_entry(e) for e in _build_register(lp, sized, log)]
    res["loss_alloc"] = {"elements": [{"name": n, "kind": k} for n, k in eng.elements],
                         "alloc": eng.alloc, "pdu_default_to_halls": bool(eng.pdu_default_to_halls)}
    return res


def _entry(e) -> dict:
    d = asdict(e)
    v = d.get("value")
    if isinstance(v, float) and not math.isfinite(v):
        d["value"] = str(v)
    elif not _jsonable(v):
        d["value"] = str(v)
    return d


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------
class _Dumper(yaml.SafeDumper):
    pass


def _scalar(x) -> bool:
    return x is None or isinstance(x, (str, int, float, bool))


def _repr_list(dumper, data):
    flow = all(_scalar(x) for x in data) or all(isinstance(x, (list, tuple)) and all(_scalar(y) for y in x)
                                                 for x in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=bool(data) and flow)


def _repr_dict(dumper, data):
    attr = "value" in data and set(data) <= {"value", "unit", "source", "note"}
    small = len(data) <= 4 and all(_scalar(v) or (isinstance(v, dict) and all(_scalar(x) for x in v.values()))
                                   for v in data.values()) and len(json.dumps(data, default=str)) < 100
    return dumper.represent_mapping("tag:yaml.org,2002:map", data, flow_style=bool(data) and (attr or small))


_Dumper.add_representer(list, _repr_list)
_Dumper.add_representer(tuple, _repr_list)
_Dumper.add_representer(dict, _repr_dict)

HEADER = "# QuickPUE project input (schema {v}). Written by the QuickPUE web input editor.\n"


def dump_yaml(project: dict) -> str:
    body = yaml.dump(project, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=4096,
                     default_flow_style=False)
    return HEADER.format(v=SCHEMA_VERSION) + body


def parse_yaml(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        raise ApiError(f"YAML error{where}: {e.problem or e}") from e
    except yaml.YAMLError as e:
        raise ApiError(f"YAML error: {e}") from e


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def list_files(root: Path, kind: str, relative_to: str | None = None) -> list[dict]:
    """Files under the root: ``project`` (YAML / JSON projects), ``epw`` or ``csv``. Each entry gives the
    root-relative path and the path relative to the current project's folder (what the YAML stores)."""
    suffixes = {"project": PROJECT_SUFFIXES, "epw": (".epw",), "csv": (".csv",)}.get(kind)
    if suffixes is None:
        raise ApiError(f"unknown file kind {kind!r}")
    r = root.resolve()
    start = base_dir_for(root, relative_to)
    out = []
    for dirpath, dirnames, filenames in os.walk(r):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
                             and not d.endswith("_results") and not d.endswith(".egg-info"))
        d = Path(dirpath)
        if kind == "project" and (d.name in ("presets", "output_sets") and d.parent.name == "quickpue"):
            continue
        for f in sorted(filenames):
            if not f.lower().endswith(suffixes):
                continue
            p = d / f
            if kind == "project" and not _looks_like_project(p):
                continue
            out.append({"path": _rel(p, r), "rel": _rel(p, start), "size": p.stat().st_size})
            if len(out) >= _MAX_FILES:
                return out
    return out


def _looks_like_project(p: Path) -> bool:
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            head = fh.read(8192)
    except OSError:
        return False
    if p.suffix == ".json":
        return '"weather"' in head or '"preset"' in head
    return bool(_PROJECT_HINT.search(head))


def read_project_file(root: Path, rel: str) -> dict:
    p = inside(root, rel)
    if p.suffix.lower() not in PROJECT_SUFFIXES:
        raise ApiError("the editor opens YAML or JSON project files (Python project scripts are not executed)")
    if not p.is_file():
        raise ApiError(f"{rel}: file not found", 404)
    text = p.read_text(encoding="utf-8")
    data = json.loads(text) if p.suffix.lower() == ".json" else parse_yaml(text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError(f"{rel}: the file does not hold a project mapping")
    has_comments = p.suffix.lower() != ".json" and any(line.lstrip().startswith("#") or " #" in line
                                                       for line in text.splitlines())
    return {"path": _rel(p, root.resolve()), "project": data, "has_comments": has_comments}


# fields that hold file paths relative to the project file (rebased on "save as" to another folder)
def _path_fields(project: dict):
    w = project.get("weather")
    if isinstance(w, dict) and "epw" in w:
        yield w, "epw"
    sc = project.get("scenarios")
    if isinstance(sc, list):
        for s in sc:
            if isinstance(s, dict) and "profile" in s:
                yield s, "profile"
    pv = (project.get("other") or {}).get("pv") if isinstance(project.get("other"), dict) else None
    if isinstance(pv, dict) and "hourly_csv" in pv:
        yield pv, "hourly_csv"


def _rebase(project: dict, old_base: Path, new_base: Path) -> list[str]:
    notes = []
    if old_base.resolve() == new_base.resolve():
        return notes
    for holder, key in _path_fields(project):
        v = holder[key]
        wrapped = isinstance(v, dict) and "value" in v
        s = v.get("value") if wrapped else v
        if not isinstance(s, str) or not s or Path(s).is_absolute():
            continue
        old = (old_base / s).resolve()
        if not old.exists() or (new_base / s).resolve() == old:
            continue
        new = Path(os.path.relpath(old, new_base)).as_posix()
        if wrapped:
            v["value"] = new
        else:
            holder[key] = new
        notes.append(f"{key}: {s} -> {new} (relative to the new file location)")
    return notes


def save_project_file(root: Path, rel: str, project: dict, overwrite: bool = False,
                      previous_path: str | None = None) -> dict:
    p = inside(root, rel)
    if p.suffix.lower() not in (".yaml", ".yml"):
        raise ApiError("save as .yaml or .yml")
    if not isinstance(project, dict):
        raise ApiError("project must be a mapping")
    if p.exists() and not overwrite:
        raise ApiError(f"{rel} exists", 409)
    project = copy.deepcopy(project)
    notes = _rebase(project, base_dir_for(root, previous_path), p.parent)
    text = dump_yaml(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return {"path": _rel(p, root.resolve()), "notes": notes, "project": project}


# ---------------------------------------------------------------------------
# Weather and curves (input visualisation)
# ---------------------------------------------------------------------------
_WEATHER_CACHE: dict[tuple[str, float], dict] = {}


def weather(root: Path, epw: str, project_path: str | None = None) -> dict:
    if not epw:
        raise ApiError("no weather file given")
    p = Path(epw)
    if not p.is_absolute():
        p = base_dir_for(root, project_path) / p
    p = p.resolve()
    if p.suffix.lower() != ".epw":
        raise ApiError("weather files are EPW (.epw)")
    if not p.is_file():
        raise ApiError(f"weather file not found: {epw} (resolved to {p})", 404)
    key = (str(p), p.stat().st_mtime)
    if key in _WEATHER_CACHE:
        return _WEATHER_CACHE[key]
    try:
        w = read_epw(p)
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"cannot read {epw}: {e}") from e
    ms = monthly_summary(w)
    points = {}
    for spec in ("epw_0.4", "max"):
        db, wb, label = design_point(w, spec)
        points[spec] = {"db": round(float(db), 2), "wb": round(float(wb), 2), "label": label}

    def r1(a):
        return [round(float(x), 1) for x in a]

    out = {
        "path": str(p), "station": w.station_label(), "city": w.city, "state": w.state, "country": w.country,
        "source": w.source, "wmo": w.wmo, "latitude": w.latitude, "longitude": w.longitude,
        "timezone": w.timezone, "elevation_m": w.elevation_m, "design": w.design, "design_points": points,
        "warnings": list(w.warnings),
        "monthly": [{"label": idx, **{k: round(float(v), 2) for k, v in row.items()}} for idx, row in ms.iterrows()],
        "hourly": {"t_db": r1(w.t_db), "t_wb": r1(w.t_wb), "t_dp": r1(w.t_dp), "rh": r1(w.rh)},
        "month": [int(x) for x in w.month], "day": [int(x) for x in w.day],
    }
    _WEATHER_CACHE.clear()
    _WEATHER_CACHE[key] = out
    return out


def curve(spec: Any, n: int = 51) -> dict:
    """Evaluate a part-load FFLP curve spec on 0..1 for the editor preview."""
    try:
        c = make_fflp(spec)
        x = [i / (n - 1) for i in range(n)]
        y = [round(float(v), 5) for v in c(x)]
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"curve: {e}") from e
    return {"id": c.curve_id, "label": c.label, "describe": c.describe(), "shaft": c.shaft, "x": x, "y": y}
