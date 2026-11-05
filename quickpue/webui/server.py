"""Local HTTP server for the web input editor (standard library only).

Binds to 127.0.0.1 by default. Static files come from ``static/``; JSON endpoints are in ``api.py``.
Write access is limited to saving project YAML files inside the root directory given at start-up.
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import api

STATIC = Path(__file__).parent / "static"
MAX_BODY = 32 * 1024 * 1024
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _finite(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    return obj


class _Handler(BaseHTTPRequestHandler):
    server_version = "QuickPUE-UI"
    root: Path = Path(".")
    initial: str | None = None
    quiet: bool = True
    check_host: bool = True

    # ------------------------------------------------------------------
    def log_message(self, fmt, *args):  # noqa: D401
        if not self.quiet:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        try:
            text = json.dumps(obj, allow_nan=False, default=str)
        except ValueError:  # NaN or infinity somewhere: send null, which the browser can parse
            text = json.dumps(_finite(obj), allow_nan=False, default=str)
        self._send(status, text.encode(), "application/json")

    def _error(self, msg: str, status: int = 400):
        self._json({"error": msg}, status)

    def _host_ok(self) -> bool:
        """Refuse requests whose Host header is not local (DNS rebinding guard on a loopback bind)."""
        if not self.check_host:
            return True
        host = self.headers.get("Host") or ""
        host = host[: host.find("]") + 1] if host.startswith("[") else host.rsplit(":", 1)[0]
        return host in _LOCAL_HOSTS

    # ------------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            return self._error("host not allowed", 403)
        u = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self._static("index.html")
            if u.path.startswith("/static/"):
                return self._static(u.path[len("/static/"):])
            if u.path == "/api/meta":
                return self._json(api.meta(self.root, self.initial))
            if u.path == "/api/preset":
                return self._json(api.preset(q.get("id", ""), self.root, q.get("project_path") or None))
            if u.path == "/api/files":
                return self._json(api.list_files(self.root, q.get("kind", "project"),
                                                 q.get("relative_to") or None))
            if u.path == "/api/file":
                return self._json(api.read_project_file(self.root, q.get("path", "")))
            if u.path == "/api/weather":
                return self._json(api.weather(self.root, q.get("epw", ""), q.get("project_path") or None))
            return self._error("not found", 404)
        except api.ApiError as e:
            return self._error(str(e), e.status)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._error(f"{type(e).__name__}: {e}", 500)

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            return self._error("host not allowed", 403)
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._error("expected application/json", 415)
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._error("request too large", 413)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError as e:
            return self._error(f"bad JSON: {e}")
        u = urlparse(self.path)
        try:
            if u.path == "/api/check":
                return self._json(api.check(body.get("project") or {}, self.root, body.get("project_path"),
                                            bool(body.get("full", True))))
            if u.path == "/api/yaml/dump":
                return self._json({"text": api.dump_yaml(body.get("project") or {})})
            if u.path == "/api/yaml/parse":
                return self._json({"value": api.parse_yaml(body.get("text", ""))})
            if u.path == "/api/curve":
                return self._json(api.curve(body.get("spec")))
            if u.path == "/api/save":
                return self._json(api.save_project_file(self.root, body.get("path", ""), body.get("project"),
                                                        bool(body.get("overwrite")), body.get("previous_path")))
            return self._error("not found", 404)
        except api.ApiError as e:
            return self._error(str(e), e.status)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._error(f"{type(e).__name__}: {e}", 500)

    def _static(self, name: str):
        p = (STATIC / name).resolve()
        if STATIC.resolve() not in p.parents or not p.is_file():
            return self._error("not found", 404)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if p.suffix == ".js":
            ctype = "text/javascript"
        if ctype.startswith("text/"):
            ctype += "; charset=utf-8"
        self._send(200, p.read_bytes(), ctype)


def make_server(root: str | Path = ".", host: str = "127.0.0.1", port: int = 8765, initial: str | None = None,
                quiet: bool = True) -> ThreadingHTTPServer:
    """Create (not start) the editor server. ``initial`` is a root-relative project path to open."""
    handler = type("Handler", (_Handler,), {"root": Path(root).resolve(), "initial": initial, "quiet": quiet,
                                            "check_host": host in _LOCAL_HOSTS})
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="quickpue-ui",
                                 description="QuickPUE web input editor (inputs and input visualisation only).")
    ap.add_argument("project", nargs="?", help="Project YAML to open")
    ap.add_argument("--root", default=None, help="Directory the editor may browse and save into "
                    "(default: the current directory, or the project's folder if it lies outside it)")
    ap.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1, local only)")
    ap.add_argument("--port", type=int, default=8765, help="Port (default 8765; 0 picks a free port)")
    ap.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    ap.add_argument("--verbose", action="store_true", help="Log every request")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve() if a.root else Path.cwd().resolve()
    initial = None
    if a.project:
        pf = Path(a.project).resolve()
        if not pf.is_file():
            ap.error(f"{a.project}: file not found")
        if not a.root and root not in pf.parents:
            root = pf.parent
        if root not in pf.parents:
            ap.error(f"{a.project} is outside --root {root}")
        initial = pf.relative_to(root).as_posix()
    try:
        srv = make_server(root, a.host, a.port, initial, quiet=not a.verbose)
    except OSError as e:
        ap.error(f"cannot listen on {a.host}:{a.port}: {e}")
    host = "127.0.0.1" if a.host in ("0.0.0.0", "") else a.host
    url = f"http://{host}:{srv.server_address[1]}/"
    print(f"QuickPUE input editor: {url}  (root {root}; Ctrl+C to stop)")
    if a.host not in _LOCAL_HOSTS:
        print("Warning: listening beyond this computer; anyone who can reach it can save YAML files under the root.")
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
