import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "package-advisor"

FAKE_PYPI = {
    "requests": {"name": "requests", "version": "2.33.0", "requires_python": ">=3.9", "license_expression": "Apache-2.0"},
    "flask": {"name": "Flask", "version": "3.2.0", "requires_python": ">=3.9", "license_expression": "BSD-3-Clause"},
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # /pypi/<name>/json
        name = self.path.split("/")[2] if self.path.startswith("/pypi/") else ""
        info = FAKE_PYPI.get(name.lower())
        if info is None:
            self.send_response(404); self.end_headers(); return
        body = json.dumps({"info": info}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def fake_pypi(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("ADVISOR_PYPI", f"http://127.0.0.1:{srv.server_port}/pypi/{{}}/json")
    yield FAKE_PYPI
    srv.shutdown()


def truth(pkg):
    i = FAKE_PYPI.get(pkg.lower())
    return None if i is None else {"name": i["name"], "latest": i["version"], "requires_python": i["requires_python"], "license": i["license_expression"]}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A copy of the repo layout so CLI runs write evidence/ and envs/ in tmp."""
    for d in ("config", "examples", "envs"):
        shutil.copytree(ROOT / d, tmp_path / d)
    monkeypatch.chdir(tmp_path)
    import agentctl.cli as cli
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    return tmp_path
