"""Promotion gates G0-G5. Each returns a GateResult that goes into the evidence bundle.

Agents are non-deterministic, so quality gates use repeated runs and a Wilson
lower bound on the pass rate, not a single lucky run.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .bundle import Bundle, validate
from .diff import Change


@dataclass
class GateResult:
    gate: str
    passed: bool
    summary: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def wilson_lower(successes: int, trials: int, z: float = 1.96) -> float:
    if trials == 0:
        return 0.0
    p = successes / trials
    denom = 1 + z * z / trials
    centre = p + z * z / (2 * trials)
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return round((centre - margin) / denom, 4)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))]


def g0(b: Bundle, platform: dict, zone: str) -> GateResult:
    errs = validate(b, platform, zone)
    return GateResult("G0", not errs, "manifest valid" if not errs else f"{len(errs)} problem(s)", {"problems": errs})


def g1_quality(results: dict, b: Bundle) -> GateResult:
    """results: {"runs": [{"case": id, "ok": bool, "ms": float}, ...]} from evalrun."""
    q = b.spec["evals"]["quality"]
    runs = results.get("runs", [])
    ok = sum(1 for r in runs if r["ok"])
    rate = round(ok / len(runs), 4) if runs else 0.0
    lower = wilson_lower(ok, len(runs))
    per_case: dict[str, list[bool]] = {}
    for r in runs:
        per_case.setdefault(r["case"], []).append(r["ok"])
    flaky = sorted(c for c, v in per_case.items() if 0 < sum(v) < len(v))
    failing = sorted(c for c, v in per_case.items() if sum(v) == 0)
    passed = bool(runs) and rate >= float(q["minPassRate"]) and lower >= float(q.get("minLowerBound", 0))
    return GateResult("G1-quality", passed, f"pass rate {rate:.2%} (95% lower bound {lower:.2%}) over {len(runs)} runs",
                      {"pass_rate": rate, "wilson_lower": lower, "trials": len(runs), "min_pass_rate": q["minPassRate"],
                       "min_lower_bound": q.get("minLowerBound", 0), "flaky_cases": flaky, "failing_cases": failing,
                       "p95_ms": percentile([r["ms"] for r in runs], 95)})


def g1_safety(agent_safety: dict, platform_suite: dict | None) -> GateResult:
    """agent_safety: bundle-specific cases run under the compiled policy.
    platform_suite: summary from the runtime lab (openshell-eks-lab results.json), gate must be pass."""
    bad = [r["case"] for r in agent_safety.get("runs", []) if not r["ok"]]
    suite_ok = platform_suite is None or platform_suite.get("gate") == "pass"
    passed = bool(agent_safety.get("runs")) and not bad and suite_ok
    return GateResult("G1-safety", passed,
                      f"agent cases {len(agent_safety.get('runs', [])) - len(bad)}/{len(agent_safety.get('runs', []))}"
                      + (f", platform suite {platform_suite.get('counts', {}).get('pass', '?')} pass" if platform_suite else ", platform suite not supplied"),
                      {"failed_cases": bad, "platform_gate": (platform_suite or {}).get("gate")})


def g2(changes: list[Change], approved_by: str | None) -> GateResult:
    widen = [c for c in changes if c.widening]
    passed = not widen or bool(approved_by)
    summary = "no widening" if not widen else (f"{len(widen)} widening change(s) approved by {approved_by}" if approved_by else f"{len(widen)} widening change(s) need approval")
    return GateResult("G2", passed, summary, {"changes": [asdict(c) for c in changes], "approved_by": approved_by})


def g3_shadow(pairs: list[dict], b: Bundle) -> GateResult:
    """pairs: [{"case", "candidate": score 0..1, "baseline": score 0..1, "candidate_ms"}] from replaying traffic."""
    cfg = b.spec["shadow"]
    if not pairs:
        return GateResult("G3", False, "no shadow traffic replayed", {})
    win = sum(1 for p in pairs if p["candidate"] > p["baseline"])
    tie = sum(1 for p in pairs if p["candidate"] == p["baseline"])
    loss = len(pairs) - win - tie
    rate = round((win + tie) / len(pairs), 4)
    p95 = percentile([p["candidate_ms"] for p in pairs], 95)
    passed = rate >= cfg["minWinOrTie"] and p95 <= cfg["p95LatencyMs"]
    return GateResult("G3", passed, f"win {win} / tie {tie} / loss {loss} vs current prod; p95 {p95:.0f} ms",
                      {"win": win, "tie": tie, "loss": loss, "win_or_tie": rate, "p95_ms": p95, "budget_p95_ms": cfg["p95LatencyMs"]})


def g4_canary(metrics: dict, b: Bundle) -> GateResult:
    """metrics: {"requests": n, "errors": n, "guardrail_hits": n}."""
    cfg = b.spec["canary"]
    n = max(int(metrics.get("requests", 0)), 0)
    err = (metrics.get("errors", 0) / n) if n else 1.0
    passed = n >= int(cfg["requests"]) and err <= float(cfg["maxErrorRate"])
    return GateResult("G4", passed, f"error rate {err:.1%} over {n} canary requests ({'promote' if passed else 'roll back'})",
                      {**metrics, "error_rate": round(err, 4), "max_error_rate": cfg["maxErrorRate"], "decision": "promote" if passed else "rollback"})


def g5_drift(history: list[dict], window: int = 3, max_drop: float = 0.05) -> GateResult:
    """history: chronological G1-quality pass rates from production re-evaluation."""
    rates = [h["pass_rate"] for h in history]
    if len(rates) <= window:
        return GateResult("G5", True, "not enough history yet", {"rates": rates})
    baseline = sum(rates[:-window]) / len(rates[:-window])
    recent = sum(rates[-window:]) / window
    drop = round(baseline - recent, 4)
    passed = drop <= max_drop
    return GateResult("G5", passed, f"recent pass rate {recent:.2%} vs baseline {baseline:.2%}" + ("" if passed else ": demote"),
                      {"baseline": round(baseline, 4), "recent": round(recent, 4), "drop": drop, "decision": "keep" if passed else "demote"})
