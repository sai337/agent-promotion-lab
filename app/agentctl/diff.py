"""G2: what would this promotion let the agent do that it could not do before?

Compares the resolved egress of two (bundle, zone) pairs in the runtime-neutral
form, so the same rule protects OpenShell and Substrate deployments.
"""
from __future__ import annotations

from dataclasses import dataclass

from .bundle import Bundle
from .compile import zone_egress

RANK = {"read-only": 1, "read-write": 2}


@dataclass(frozen=True)
class Change:
    kind: str
    detail: str
    widening: bool


def diff(old: Bundle | None, old_zone: str | None, new: Bundle, new_zone: str) -> list[Change]:
    before = {e["host"]: e for e in (zone_egress(old, old_zone) if old else [])}
    after = {e["host"]: e for e in zone_egress(new, new_zone)}
    out: list[Change] = []
    for h in sorted(after.keys() - before.keys()):
        out.append(Change("host", f"+ {h} ({after[h]['access']})", True))
    for h in sorted(before.keys() - after.keys()):
        out.append(Change("host", f"- {h}", False))
    for h in sorted(before.keys() & after.keys()):
        a, c = RANK[before[h]["access"]], RANK[after[h]["access"]]
        if c != a:
            out.append(Change("access", f"{h}: {before[h]['access']} -> {after[h]['access']}", c > a))
    if old is not None:
        op, np_ = old.spec["policy"]["program"], new.spec["policy"]["program"]
        if op != np_:
            out.append(Change("program", f"{op} -> {np_}", True))
        new_w = set(new.spec["policy"].get("writable") or []) - set(old.spec["policy"].get("writable") or [])
        for w in sorted(new_w):
            out.append(Change("filesystem", f"+ writable {w}", True))
        if old.spec.get("model") != new.spec.get("model"):
            out.append(Change("model", f"{old.spec.get('model')} -> {new.spec.get('model')}", True))
        if set(new.spec.get("tools") or []) - set(old.spec.get("tools") or []):
            out.append(Change("tools", "+ " + ", ".join(sorted(set(new.spec.get("tools") or []) - set(old.spec.get("tools") or []))), True))
        if old.spec.get("dataClass") != new.spec.get("dataClass"):
            out.append(Change("dataClass", f"{old.spec.get('dataClass')} -> {new.spec.get('dataClass')}", True))
    return out
