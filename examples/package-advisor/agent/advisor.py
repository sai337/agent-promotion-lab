#!/usr/bin/env python3
"""package-advisor: a small, real agent used to demonstrate promotion.

  advisor.py advise <package>   -> one JSON line with the requested facts
  advisor.py publish <package>  -> tries to upload to PyPI (must be blocked by policy)

Features come from ADVISOR_FEATURES (set from the bundle's spec.features), so
two bundle versions of the same image behave differently, like a prompt change.
Package names are validated before any network call: text from users or tools
is never trusted.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
API = os.environ.get("ADVISOR_PYPI", "https://pypi.org/pypi/{}/json")


def advise(pkg: str, features: list[str]) -> dict:
    if not NAME.match(pkg):
        return {"error": "invalid_name"}
    try:
        with urllib.request.urlopen(API.format(pkg), timeout=20) as r:
            info = json.load(r)["info"]
    except urllib.error.HTTPError as e:
        return {"error": "not_found"} if e.code == 404 else {"error": f"http_{e.code}"}
    except (urllib.error.URLError, OSError) as e:
        return {"error": "network", "detail": str(e)[:120]}
    out = {"name": info["name"]}
    if "latest" in features:
        out["latest"] = info["version"]
    if "requires_python" in features:
        out["requires_python"] = info.get("requires_python") or ""
    if "license" in features:
        out["license"] = info.get("license_expression") or info.get("license") or ""
    return out


def publish(pkg: str) -> int:
    """A write the policy must stop: POST to the upload endpoint."""
    req = urllib.request.Request("https://upload.pypi.org/legacy/", data=b"name=" + pkg.encode(), method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # blocked (good) or rejected upstream
        print(json.dumps({"error": "publish_failed", "detail": str(e)[:120]}))
        return 1
    print(json.dumps({"published": pkg}))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("advise", "publish"):
        print(json.dumps({"error": "usage: advise|publish <package>"}))
        return 2
    if argv[0] == "publish":
        return publish(argv[1])
    features = [f for f in os.environ.get("ADVISOR_FEATURES", "latest").split(",") if f]
    ans = advise(argv[1], features)
    print(json.dumps(ans))
    return 0 if "error" not in ans or ans["error"] in ("not_found", "invalid_name") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
