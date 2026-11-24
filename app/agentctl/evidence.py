"""Evidence bundles and promotion.

Every gate result for a bundle version is written to
evidence/<agent>/<version>/<gate>.json. Promotion to a zone is allowed only when
the evidence holds a passing result for every gate the platform requires for
that zone, all recorded against the same bundle fingerprint. Promotion itself is
a change to envs/<zone>/releases.yaml: a reviewed PR in a GitOps flow, and a
revert is the rollback.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import yaml

from .bundle import Bundle
from .gates import GateResult


def evidence_dir(root: Path, b: Bundle) -> Path:
    return root / "evidence" / b.name / b.version


def record(root: Path, b: Bundle, result: GateResult, zone: str) -> Path:
    d = evidence_dir(root, b)
    d.mkdir(parents=True, exist_ok=True)
    doc = {"agent": b.name, "version": b.version, "fingerprint": b.fingerprint(), "zone": zone,
           "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **result.to_dict()}
    p = d / f"{result.gate}.json"
    p.write_text(json.dumps(doc, indent=2))
    return p


def collect(root: Path, b: Bundle) -> dict[str, dict]:
    d = evidence_dir(root, b)
    if not d.exists():
        return {}
    return {p.stem: json.loads(p.read_text()) for p in sorted(d.glob("*.json"))}


def check(root: Path, b: Bundle, zone: str, platform: dict) -> tuple[bool, list[str]]:
    ev = collect(root, b)
    problems = []
    for gate in platform["requiredGates"][zone]:
        r = ev.get(gate)
        if r is None:
            problems.append(f"{gate}: no evidence")
        elif not r["passed"]:
            problems.append(f"{gate}: failed ({r['summary']})")
        elif r["fingerprint"] != b.fingerprint():
            problems.append(f"{gate}: evidence is for a different bundle (fingerprint changed since)")
    return not problems, problems


def promote(root: Path, b: Bundle, zone: str, platform: dict, runtime: str, policy_hash: str) -> tuple[bool, list[str], Path]:
    ok, problems = check(root, b, zone, platform)
    rel = root / "envs" / zone / "releases.yaml"
    if not ok:
        return False, problems, rel
    data = yaml.safe_load(rel.read_text()) if rel.exists() else None
    data = data or {"zone": zone, "agents": {}}
    prev = (data["agents"].get(b.name) or {}).get("version")
    data["agents"][b.name] = {
        "version": b.version, "previous": prev, "image": b.spec["image"], "runtime": runtime,
        "fingerprint": b.fingerprint(), "policy_sha256": policy_hash,
        "evidence": f"evidence/{b.name}/{b.version}/", "owner": b.owner,
    }
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text(yaml.safe_dump(data, sort_keys=False))
    return True, [], rel
