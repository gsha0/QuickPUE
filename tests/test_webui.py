"""Web input editor (quickpue.webui): the JSON API behind the browser form. The editor is inputs only: these
tests check that it serves the schema and presets, validates through the same loader as the CLI, writes YAML
that loads to the identical project, and keeps file access inside its root directory."""

import json
import shutil
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from quickpue.inputs import load_project
from quickpue.webui.server import make_server

HERE = Path(__file__).parent
ROOT = HERE.parent
EPW_NAME = "AUS_NSW_Horsley.Equestrian.Centre.947600_TMYx.2011-2025.epw"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("ui_root")
    (root / "weather").mkdir()
    shutil.copy(HERE / "data" / EPW_NAME, root / "weather" / EPW_NAME)
    (root / "cases").mkdir()
    for name in ("dc_o1.yaml", "dc_s1.yaml"):
        text = (HERE / "cases" / name).read_text().replace("../data/", "../weather/")
        (root / "cases" / name).write_text(text)
    srv = make_server(root, "127.0.0.1", 0, initial="cases/dc_o1.yaml")
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", root
    srv.shutdown()
    srv.server_close()


def call(base, path, body=None, headers=None):
    data = None if body is None else json.dumps(body).encode()
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(base + path, data=data, headers=h, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw.decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def raw_case(name="dc_o1.yaml"):
    return yaml.safe_load((HERE / "cases" / name).read_text().replace("../data/", "../weather/"))


def test_page_and_static_files(server):
    base, _ = server
    st, html = call(base, "/")
    assert st == 200 and "QuickPUE" in html and "/static/js/app.js" in html
    for f in ("app.js", "model.js", "form.js", "views.js", "charts.js", "util.js"):
        with urllib.request.urlopen(f"{base}/static/js/{f}") as r:
            assert r.status == 200 and r.headers.get_content_type() == "text/javascript"
    st, _ = call(base, "/static/../api.py")
    assert st == 404


def test_meta_has_schema_defaults_and_libraries(server):
    base, _ = server
    st, m = call(base, "/api/meta")
    assert st == 200
    defs = m["schema"]["$defs"]
    # default_factory defaults are added so the editor can show them without writing them
    assert defs["UPS"]["properties"]["efficiency"]["default"] == [[0.0, 0.94], [1.0, 0.94]]
    assert defs["CondenserWater"]["properties"]["reset"]["default"]["type"] == "wetbulb_offset"
    assert {p["id"] for p in m["presets"]} >= {"LC-ACC-IFC-AD", "AIR-WCC-WSE"}
    assert "K-DP(0.3)" not in [c["id"] for c in m["fflp"]] and "K-VSM" in [c["id"] for c in m["fflp"]]
    assert m["units"]["kw"] == ["w", "kw", "mw"]
    assert m["initial"] == "cases/dc_o1.yaml"


def test_preset_template_is_resolved(server):
    base, _ = server
    st, p = call(base, "/api/preset?id=LC-ACC-IFC-AD")
    assert st == 200 and p["hall_name"] == "Data hall"
    assert p["template"]["plants"][0]["chillers"][0]["adiabatic"]["activation_c"] == 30.0
    assert p["template"]["zones"]  # inherited from _base_common through extends
    st, e = call(base, "/api/preset?id=NOPE")
    assert st == 404 and "unknown preset" in e["error"]


def test_check_complete_matches_cli_register(server):
    base, _ = server
    st, r = call(base, "/api/check", {"project": raw_case(), "project_path": "cases/dc_o1.yaml"})
    assert st == 200 and r["ok"] and r["stage"] == "complete" and not r["errors"]
    reg = {e["path"]: e for e in r["register"]}
    assert reg["plants[Chiller plant].chillers[ACC].capacity_kw"]["kind"] == "document"
    assert any(e["origin"] == "default" for e in r["register"])
    names = [e["name"] for e in r["loss_alloc"]["elements"]]
    assert names[:3] == ["PDU", "UPS-IT", "UPS-MECH"]
    assert r["loss_alloc"]["alloc"]["TX-HV"] == {"__outdoors__": 1.0}


def test_check_reports_schema_errors_with_locations(server):
    base, _ = server
    p = raw_case()
    p["halls"][0]["it_kw"] = -1
    p["loops"][0]["return_c"] = 10
    p["scenarios"] = [{"name": "x"}]
    st, r = call(base, "/api/check", {"project": p, "project_path": "cases/dc_o1.yaml"})
    assert st == 200 and not r["ok"] and r["stage"] == "schema"
    locs = {tuple(e["loc"]): e["msg"] for e in r["errors"]}
    assert ("halls", 0, "it_kw") in locs
    assert "return must exceed supply" in locs[("loops", 0)]
    assert "exactly one of it_fraction or profile" in locs[("scenarios", 0)]
    assert ("scenarios",) not in locs  # the union literal branch is dropped when a deeper error exists


def test_check_reports_missing_weather_and_bad_links(server):
    base, _ = server
    p = raw_case()
    p["weather"]["epw"] = "missing.epw"
    st, r = call(base, "/api/check", {"project": p, "project_path": "cases/dc_o1.yaml"})
    assert r["stage"] == "sizing" and r["errors"][0]["loc"] == ["weather", "epw"]
    p = raw_case()
    p["plants"][0]["loop"] = "NOPE"
    st, r = call(base, "/api/check", {"project": p, "project_path": "cases/dc_o1.yaml"})
    assert not r["ok"] and "NOPE" in r["errors"][0]["msg"]


@pytest.mark.parametrize("case", ["dc_o1.yaml", "dc_s1.yaml"])
def test_yaml_written_by_the_editor_loads_to_the_same_project(server, case, tmp_path):
    """Round trip through the editor's YAML writer changes nothing the engine sees."""
    base, root = server
    raw = raw_case(case)
    st, d = call(base, "/api/yaml/dump", {"project": raw})
    assert st == 200 and d["text"].startswith("# QuickPUE project input")
    st, back = call(base, "/api/yaml/parse", {"text": d["text"]})
    assert back["value"] == raw
    a = load_project(raw, base_dir=root / "cases")
    b = load_project(back["value"], base_dir=root / "cases")
    assert a.project.model_dump() == b.project.model_dump()
    assert {k: (v.value, v.kind, v.ref) for k, v in a.register.items()} == \
        {k: (v.value, v.kind, v.ref) for k, v in b.register.items()}


def test_yaml_parse_error_has_position(server):
    base, _ = server
    st, e = call(base, "/api/yaml/parse", {"text": "a: [1, 2\nb: 3"})
    assert st == 400 and "line" in e["error"]


def test_files_listing_and_relative_paths(server):
    base, _ = server
    st, files = call(base, "/api/files?kind=project")
    assert st == 200 and {f["path"] for f in files} == {"cases/dc_o1.yaml", "cases/dc_s1.yaml"}
    st, epws = call(base, "/api/files?kind=epw&relative_to=cases/dc_o1.yaml")
    assert epws[0]["path"] == f"weather/{EPW_NAME}" and epws[0]["rel"] == f"../weather/{EPW_NAME}"
    st, f = call(base, "/api/file?path=cases/dc_o1.yaml")
    assert st == 200 and f["project"]["project"]["name"] == "DC_O1" and f["has_comments"]


def test_file_access_stays_inside_root(server):
    base, _ = server
    st, e = call(base, "/api/file?path=../../etc/passwd")
    assert st == 403
    st, e = call(base, "/api/save", {"path": "../escape.yaml", "project": {"weather": {"epw": "x.epw"}}})
    assert st == 403
    st, e = call(base, "/api/save", {"path": "notes.txt", "project": {}})
    assert st == 400
    st, e = call(base, "/api/file?path=cases/x.py")
    assert st == 400 and "not executed" in e["error"]


def test_save_refuses_overwrite_and_rebases_paths(server):
    base, root = server
    p = raw_case()
    st, r = call(base, "/api/save", {"path": "cases/dc_o1.yaml", "project": p})
    assert st == 409
    st, r = call(base, "/api/save", {"path": "studies/a/copy.yaml", "project": p, "previous_path": "cases/dc_o1.yaml"})
    assert st == 200 and r["path"] == "studies/a/copy.yaml"
    saved = yaml.safe_load((root / "studies" / "a" / "copy.yaml").read_text())
    assert saved["weather"]["epw"] == f"../../weather/{EPW_NAME}"
    assert r["notes"] and "epw" in r["notes"][0]
    a = load_project(root / "studies" / "a" / "copy.yaml").project.model_dump()
    b = load_project(p, base_dir=root / "cases").project.model_dump()
    a["weather"].pop("epw")
    b["weather"].pop("epw")
    assert a == b
    st, r = call(base, "/api/save", {"path": "studies/a/copy.yaml", "project": saved, "overwrite": True,
                                     "previous_path": "studies/a/copy.yaml"})
    assert st == 200 and not r["notes"]


def test_weather_and_curve_previews(server):
    base, _ = server
    st, w = call(base, f"/api/weather?epw=../weather/{EPW_NAME}&project_path=cases/dc_o1.yaml")
    assert st == 200 and len(w["hourly"]["t_db"]) == 8760 and len(w["monthly"]) == 13
    assert w["design_points"]["epw_0.4"]["db"] == pytest.approx(35.4, abs=0.05)
    st, c = call(base, "/api/curve", {"spec": "K-DP(0.3)"})
    assert st == 200 and c["y"][-1] == pytest.approx(1.0) and c["y"][0] == pytest.approx(0.0)
    st, e = call(base, "/api/curve", {"spec": "K-NOPE"})
    assert st == 400


def test_requests_from_other_hosts_and_non_json_posts_are_refused(server):
    base, _ = server
    st, e = call(base, "/api/meta", headers={"Host": "evil.example"})
    assert st == 403
    req = urllib.request.Request(base + "/api/save", data=b"path=x.yaml", method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req)
    assert ei.value.code == 415
