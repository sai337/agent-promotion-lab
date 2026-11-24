"""agentctl: promote AI agents from sandbox to production through evidence gates.

  agentctl validate BUNDLE [--zone Z]                 G0
  agentctl compile  BUNDLE --zone Z [--runtime R]     one policy -> OpenShell or Substrate
  agentctl diff     BUNDLE --zone Z [--from-bundle B --from-zone Z0] [--approved-by WHO]   G2
  agentctl eval     BUNDLE --kind quality|safety --exec local|openshell [--sandbox S]       G1
  agentctl shadow   BUNDLE --baseline B --exec local|openshell [--sandbox S --baseline-sandbox S0]  G3
  agentctl canary   BUNDLE --metrics FILE                                                    G4
  agentctl drift    --history FILE                                                           G5
  agentctl suite    BUNDLE --results FILE      attach the runtime lab's hostile-agent suite to G1-safety
  agentctl promote  BUNDLE --zone Z             write envs/Z/releases.yaml if the evidence allows
  agentctl status   BUNDLE                      gates recorded for this version
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

from . import evidence, gates
from .bundle import load, load_platform
from .compile import compile_zone
from .diff import diff
from .runner import LocalExecutor, OpenShellExecutor, run_quality, run_safety, run_shadow

ROOT = Path.cwd()


def _platform(a) -> dict:
    return load_platform(a.platform)


def _executor(a, b, sandbox: str | None):
    feats = ",".join(b.spec.get("features") or ["latest"])
    if a.exec == "local":
        agent = b.root / "agent" / "advisor.py"
        return LocalExecutor(["env", f"ADVISOR_FEATURES={feats}", sys.executable, str(agent)])
    return OpenShellExecutor(sandbox, ["env", f"ADVISOR_FEATURES={feats}", b.spec["policy"]["program"], "/app/advisor.py"])


def _record(a, b, result, zone: str) -> int:
    p = evidence.record(ROOT, b, result, zone)
    print(f"{result.gate}: {'PASS' if result.passed else 'FAIL'} - {result.summary}\n  evidence: {p.relative_to(ROOT)}")
    return 0 if result.passed else 1


def cmd_validate(a) -> int:
    b = load(a.bundle)
    return _record(a, b, gates.g0(b, _platform(a), a.zone), a.zone)


def cmd_compile(a) -> int:
    b = load(a.bundle)
    runtime, doc, warns = compile_zone(b, a.zone, a.runtime)
    text = yaml.safe_dump(doc, sort_keys=False)
    if a.out:
        Path(a.out).write_text(text)
        print(f"{runtime} policy for {b.name}@{b.version} zone={a.zone} -> {a.out} (sha256 {hashlib.sha256(text.encode()).hexdigest()[:12]})")
    else:
        print(text, end="")
    for w in warns:
        print(f"WARNING fidelity: {w}", file=sys.stderr)
    return 0


def cmd_diff(a) -> int:
    b = load(a.bundle)
    old = load(a.from_bundle) if a.from_bundle else None
    changes = diff(old, a.from_zone or a.zone, b, a.zone)
    for c in changes:
        print(f"{'WIDEN ' if c.widening else 'narrow'} {c.kind:10} {c.detail}")
    return _record(a, b, gates.g2(changes, a.approved_by), a.zone)


def cmd_eval(a) -> int:
    b = load(a.bundle)
    ex = _executor(a, b, a.sandbox)
    if a.kind == "quality":
        q = b.spec["evals"]["quality"]
        res = run_quality(ex, b.root / q["dataset"], int(q["repeats"]), b.spec.get("features") or ["latest"])
        result = gates.g1_quality(res, b)
    else:
        res = run_safety(ex, b.root / b.spec["evals"]["safety"]["dataset"])
        suite_file = evidence.evidence_dir(ROOT, b) / "platform-suite.json"
        suite = json.loads(suite_file.read_text()) if suite_file.exists() else None
        result = gates.g1_safety(res, suite)
    result.details["runs"] = res["runs"]
    return _record(a, b, result, a.zone)


def cmd_suite(a) -> int:
    b = load(a.bundle)
    d = evidence.evidence_dir(ROOT, b)
    d.mkdir(parents=True, exist_ok=True)
    summary = json.loads(Path(a.results).read_text())
    (d / "platform-suite.json").write_text(json.dumps({k: summary.get(k) for k in ("gate", "counts", "blocking_failures", "meta")}, indent=2))
    print(f"attached platform suite: gate={summary.get('gate')} counts={summary.get('counts')}")
    return 0


def cmd_shadow(a) -> int:
    b, base = load(a.bundle), load(a.baseline)
    pairs = run_shadow(_executor(a, b, a.sandbox), _executor(a, base, a.baseline_sandbox or a.sandbox),
                       b.root / b.spec["shadow"]["traffic"], b.spec.get("features") or [], base.spec.get("features") or [])
    result = gates.g3_shadow(pairs, b)
    result.details["pairs"] = pairs
    return _record(a, b, result, "staging")


def cmd_canary(a) -> int:
    b = load(a.bundle)
    return _record(a, b, gates.g4_canary(json.loads(Path(a.metrics).read_text()), b), "canary")


def cmd_drift(a) -> int:
    r = gates.g5_drift(json.loads(Path(a.history).read_text()))
    print(f"G5: {'KEEP' if r.passed else 'DEMOTE'} - {r.summary}")
    return 0 if r.passed else 1


def cmd_promote(a) -> int:
    b = load(a.bundle)
    platform = _platform(a)
    runtime, doc, _ = compile_zone(b, a.zone)
    policy_hash = hashlib.sha256(yaml.safe_dump(doc, sort_keys=True).encode()).hexdigest()
    ok, problems, rel = evidence.promote(ROOT, b, a.zone, platform, runtime, policy_hash)
    if not ok:
        print(f"BLOCKED: {b.name}@{b.version} cannot enter {a.zone}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"PROMOTED {b.name}@{b.version} -> {a.zone} ({runtime}); updated {rel.relative_to(ROOT)}")
    return 0


def cmd_status(a) -> int:
    b = load(a.bundle)
    ev = evidence.collect(ROOT, b)
    print(f"{b.name}@{b.version} fingerprint {b.fingerprint()[:19]}")
    for g in ["G0", "G1-quality", "G1-safety", "G2", "G3", "G4"]:
        r = ev.get(g)
        stale = r and r["fingerprint"] != b.fingerprint()
        print(f"  {g:11} {'-' if not r else ('STALE' if stale else ('PASS' if r['passed'] else 'FAIL'))}  {r['summary'] if r else ''}")
    for z in _platform(a)["zones"]:
        ok, _ = evidence.check(ROOT, b, z, _platform(a))
        print(f"  may enter {z:8} {'yes' if ok else 'no'}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agentctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--platform", default="config/platform.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, bundle=True):
        sp = sub.add_parser(name)
        if bundle:
            sp.add_argument("bundle")
        sp.set_defaults(fn=fn)
        return sp

    s = add("validate", cmd_validate); s.add_argument("--zone", default="sbx")
    s = add("compile", cmd_compile); s.add_argument("--zone", required=True); s.add_argument("--runtime"); s.add_argument("--out")
    s = add("diff", cmd_diff); s.add_argument("--zone", required=True); s.add_argument("--from-bundle"); s.add_argument("--from-zone"); s.add_argument("--approved-by")
    s = add("eval", cmd_eval); s.add_argument("--kind", choices=["quality", "safety"], required=True); s.add_argument("--exec", choices=["local", "openshell"], default="local"); s.add_argument("--sandbox"); s.add_argument("--zone", default="sbx")
    s = add("suite", cmd_suite); s.add_argument("--results", required=True)
    s = add("shadow", cmd_shadow); s.add_argument("--baseline", required=True); s.add_argument("--exec", choices=["local", "openshell"], default="local"); s.add_argument("--sandbox"); s.add_argument("--baseline-sandbox")
    s = add("canary", cmd_canary); s.add_argument("--metrics", required=True)
    s = add("drift", cmd_drift, bundle=False); s.add_argument("--history", required=True)
    s = add("promote", cmd_promote); s.add_argument("--zone", required=True)
    add("status", cmd_status)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
