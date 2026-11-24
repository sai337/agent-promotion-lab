import json
import sys

import pytest
import yaml

from agentctl import evidence, gates
from agentctl.bundle import load, load_platform
from agentctl.cli import main
from agentctl.runner import LocalExecutor, run_quality, run_safety, run_shadow

from conftest import EXAMPLE, ROOT, truth

PLATFORM = load_platform(ROOT / "config/platform-kind.yaml")


def test_wilson_lower_bound():
    assert gates.wilson_lower(30, 30) == pytest.approx(0.8865, abs=1e-3)
    assert gates.wilson_lower(0, 0) == 0.0
    assert gates.wilson_lower(29, 30) < gates.wilson_lower(30, 30)


def runs(ok_pattern):
    return {"runs": [{"case": f"Q{i % 10}", "ok": ok, "ms": 10.0} for i, ok in enumerate(ok_pattern)]}


def test_small_samples_cannot_pass_g1():
    b = load(EXAMPLE / "agent.yaml")
    r = gates.g1_quality(runs([True] * 6), b)
    assert not r.passed and r.details["wilson_lower"] < 0.85   # 6/6 is not evidence of 95%


def test_g1_quality_needs_rate_and_bound():
    b = load(EXAMPLE / "agent.yaml")
    assert gates.g1_quality(runs([True] * 30), b).passed
    r = gates.g1_quality(runs([True] * 27 + [False] * 3), b)
    assert not r.passed and r.details["pass_rate"] == 0.9
    r = gates.g1_quality(runs([True] * 10 + [False] + [True] * 19), b)  # one flaky case
    assert r.details["flaky_cases"] == ["Q0"]
    assert not gates.g1_quality({"runs": []}, b).passed


def test_g1_safety_requires_platform_suite_pass():
    ok = {"runs": [{"case": "S01", "ok": True}]}
    assert gates.g1_safety(ok, {"gate": "pass", "counts": {"pass": 18}}).passed
    assert not gates.g1_safety(ok, {"gate": "fail"}).passed
    assert not gates.g1_safety({"runs": [{"case": "S01", "ok": False}]}, None).passed


def test_g3_g4_g5():
    b = load(EXAMPLE / "agent.yaml")
    pairs = [{"case": str(i), "candidate": 1.0, "baseline": 0.33, "candidate_ms": 100} for i in range(9)] + [{"case": "x", "candidate": 0.3, "baseline": 0.6, "candidate_ms": 100}]
    assert gates.g3_shadow(pairs, b).passed
    assert not gates.g3_shadow(pairs[-1:] * 5, b).passed
    assert gates.g4_canary({"requests": 40, "errors": 1}, b).details["decision"] == "promote"
    assert gates.g4_canary({"requests": 40, "errors": 5}, b).details["decision"] == "rollback"
    assert not gates.g4_canary({"requests": 10, "errors": 0}, b).passed
    hist = [{"pass_rate": r} for r in (1.0, 0.98, 1.0, 0.97, 0.85, 0.84, 0.86)]
    assert gates.g5_drift(hist).details["decision"] == "demote"
    assert gates.g5_drift(hist[:4]).passed


def agent(features):
    return LocalExecutor(["env", f"ADVISOR_FEATURES={features}", sys.executable, str(EXAMPLE / "agent/advisor.py")])


def test_real_agent_quality_against_fake_pypi(fake_pypi, tmp_path):
    ds = tmp_path / "g.yaml"
    ds.write_text(yaml.safe_dump({"cases": [{"id": "Q1", "package": "requests"}, {"id": "Q2", "package": "flask"},
                                            {"id": "Q3", "package": "nope-xyz", "expect": "not_found"},
                                            {"id": "Q4", "package": "a;rm -rf /", "expect": "invalid_name"}]}))
    full = run_quality(agent("latest,requires_python,license"), ds, 2, ["latest", "requires_python", "license"], truth)
    assert all(r["ok"] for r in full["runs"]) and len(full["runs"]) == 8
    # a version that does not return license fails the license-graded cases
    partial = run_quality(agent("latest"), ds, 1, ["latest", "license"], truth)
    assert [r["ok"] for r in partial["runs"]] == [False, False, True, True]


def test_shadow_prefers_the_richer_candidate(fake_pypi, tmp_path):
    t = tmp_path / "t.yaml"
    t.write_text("requests: [requests, flask, missing-pkg-1]\n")
    pairs = run_shadow(agent("latest,requires_python,license"), agent("latest"), t, [], [], truth)
    assert [p["candidate"] > p["baseline"] for p in pairs] == [True, True, False]
    assert pairs[2]["candidate"] == pairs[2]["baseline"] == 1.0


def test_safety_runner_scores_exit_codes(tmp_path):
    class Fake:
        def run(self, argv):
            return (1, "blocked", 1.0) if argv[0] == "publish" else (0, "{}", 1.0)
    ds = tmp_path / "s.yaml"
    ds.write_text((EXAMPLE / "evals/safety.yaml").read_text())
    assert all(r["ok"] for r in run_safety(Fake(), ds)["runs"])


def test_promotion_flow_and_blocks(workspace, fake_pypi, monkeypatch):
    import agentctl.runner as runner
    monkeypatch.setattr(runner, "pypi_truth", lambda pkg, fetch=None: truth(pkg))
    import agentctl.cli as cli
    monkeypatch.setattr(cli, "run_quality", lambda ex, ds, rep, feats: runner.run_quality(ex, ds, rep, feats, truth))
    B = "examples/package-advisor/agent.yaml"
    P = ["--platform", "config/platform-kind.yaml"]
    gold = workspace / "examples/package-advisor/evals/golden.yaml"
    pk = ["requests", "flask", "nope-xyz", "a;b"]
    ex = [None, None, "not_found", "invalid_name"]
    cases = [{"id": f"Q{i:02d}", "package": pk[i % 4], **({"expect": ex[i % 4]} if ex[i % 4] else {})} for i in range(10)]
    gold.write_text(yaml.safe_dump({"cases": cases}))   # 10 cases x 3 repeats: enough trials for the lower bound
    assert main(P + ["promote", B, "--zone", "staging"]) == 1          # no evidence yet
    assert main(P + ["validate", B, "--zone", "staging"]) == 0
    assert main(P + ["eval", B, "--kind", "quality"]) == 0
    b = load(workspace / B)
    evidence.record(workspace, b, gates.g1_safety({"runs": [{"case": "S01", "ok": True}]}, {"gate": "pass"}), "sbx")
    assert main(P + ["diff", B, "--zone", "staging", "--from-bundle", "examples/package-advisor/agent-v1.0.0.yaml", "--from-zone", "prod"]) == 0
    assert main(P + ["promote", B, "--zone", "staging"]) == 0
    rel = yaml.safe_load((workspace / "envs/staging/releases.yaml").read_text())
    assert rel["agents"]["package-advisor"]["version"] == "1.1.0"
    assert main(P + ["promote", B, "--zone", "prod"]) == 1             # G3, G4 missing
    # any change to the bundle makes old evidence stale
    p = workspace / B
    p.write_text(p.read_text().replace("prompts/advisor@v2", "prompts/advisor@v3"))
    assert main(P + ["promote", B, "--zone", "staging"]) == 1
