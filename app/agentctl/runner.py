"""Runs an agent's eval cases: locally (subprocess) or inside an OpenShell sandbox.

Quality cases compare the agent's answer with ground truth the runner fetches
itself, outside the sandbox, so the agent cannot grade its own homework.
Safety cases state the secure outcome (exit code) like the hostile-agent suite.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

import yaml


class Executor(Protocol):
    def run(self, argv: list[str]) -> tuple[int, str, float]: ...


class LocalExecutor:
    """Runs the agent on this machine (no sandbox). For development and unit tests."""

    def __init__(self, agent_cmd: list[str]):
        self.agent_cmd = agent_cmd

    def run(self, argv: list[str]) -> tuple[int, str, float]:
        t0 = time.monotonic()
        p = subprocess.run(self.agent_cmd + argv, capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout + p.stderr, (time.monotonic() - t0) * 1000


class OpenShellExecutor:
    """Runs the agent inside an existing OpenShell sandbox via `openshell sandbox exec`."""

    def __init__(self, sandbox: str, agent_cmd: list[str], cli: str | None = None):
        self.sandbox, self.agent_cmd = sandbox, agent_cmd
        self.cli = cli or os.environ.get("OPENSHELL_BIN", "openshell")

    def run(self, argv: list[str]) -> tuple[int, str, float]:
        t0 = time.monotonic()
        cmd = " ".join(shlex.quote(a) for a in self.agent_cmd + argv)
        env = {**os.environ, "OPENSHELL_TELEMETRY_ENABLED": "false"}
        p = subprocess.run([self.cli, "sandbox", "exec", "-n", self.sandbox, "--no-login-shell", "--", "/bin/bash", "-c", cmd],
                           capture_output=True, text=True, timeout=120, env=env)
        out = p.stdout + p.stderr
        if p.returncode != 0 and "Error:" in out and "×" in out:
            raise RuntimeError(f"agent did not run in sandbox {self.sandbox}: {out[-400:]}")
        return p.returncode, out, (time.monotonic() - t0) * 1000


def pypi_truth(package: str, fetch: Callable[[str], dict | None] | None = None) -> dict | None:
    """Ground truth from PyPI, fetched by the runner (not the agent)."""
    def default(url: str):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
    doc = (fetch or default)(f"https://pypi.org/pypi/{package}/json")
    if doc is None:
        return None
    info = doc["info"]
    return {"name": info["name"], "latest": info["version"], "requires_python": info.get("requires_python") or "",
            "license": info.get("license_expression") or info.get("license") or ""}


def grade(case: dict, answer: dict, truth: dict | None, features: list[str]) -> bool:
    expect = case.get("expect", "facts")
    if expect == "not_found":
        return answer.get("error") == "not_found"
    if expect == "invalid_name":
        return answer.get("error") == "invalid_name"
    if truth is None:
        return False
    return all(str(answer.get(f, "")) == str(truth.get(f, "")) for f in features)


def run_quality(ex: Executor, dataset: Path, repeats: int, features: list[str],
                truth_fn: Callable[[str], dict | None] = pypi_truth) -> dict:
    cases = yaml.safe_load(dataset.read_text())["cases"]
    truths = {c["package"]: (truth_fn(c["package"]) if c.get("expect", "facts") == "facts" else None) for c in cases}
    runs = []
    for _ in range(repeats):
        for c in cases:
            rc, out, ms = ex.run(["advise", c["package"]])
            try:
                ans = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                ans = {"error": "unparseable", "raw": out[-200:]}
            runs.append({"case": c["id"], "ok": grade(c, ans, truths[c["package"]], features), "ms": round(ms, 1)})
    return {"runs": runs}


def run_safety(ex: Executor, dataset: Path) -> dict:
    cases = yaml.safe_load(dataset.read_text())["cases"]
    runs = []
    for c in cases:
        rc, out, ms = ex.run(c["argv"])
        ok = (rc == 0) if c["expect"] == "success" else (rc != 0)
        # "blocked" must mean the policy stopped it, not that the upstream said no
        if ok and any(marker in out for marker in c.get("must_not_contain", [])):
            ok = False
        runs.append({"case": c["id"], "ok": ok, "rc": rc, "ms": round(ms, 1), "output": out[-300:]})
    return {"runs": runs}


def run_shadow(candidate: Executor, baseline: Executor, traffic: Path, cand_features: list[str], base_features: list[str],
               truth_fn: Callable[[str], dict | None] = pypi_truth) -> list[dict]:
    """Replays recorded prod traffic through both versions and scores each answer 0..1
    by the share of all known fields it gets right (more correct fields = better)."""
    all_fields = ["latest", "requires_python", "license"]
    pairs = []
    for pkg in yaml.safe_load(traffic.read_text())["requests"]:
        truth = truth_fn(pkg)

        def score(ex: Executor):
            rc, out, ms = ex.run(["advise", pkg])
            try:
                ans = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                return 0.0, ms
            if truth is None:
                return (1.0 if ans.get("error") == "not_found" else 0.0), ms
            return sum(str(ans.get(f, "")) == str(truth.get(f, "")) for f in all_fields) / len(all_fields), ms

        c, cms = score(candidate)
        b_, _ = score(baseline)
        pairs.append({"case": pkg, "candidate": round(c, 3), "baseline": round(b_, 3), "candidate_ms": round(cms, 1)})
    return pairs
