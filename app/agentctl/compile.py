"""One policy, two runtimes.

The bundle declares egress once (hosts + access) plus per-zone additions. This
module resolves the policy for a zone and compiles it to:
  - an NVIDIA OpenShell sandbox policy (host + port + binary + HTTP method), and
  - a CNCF Agent Substrate EgressPolicy (hostnames).
Substrate rules are host-level in our tests, so method limits (read-only) cannot
be expressed there. The compiler reports that as a fidelity warning instead of
silently widening.
"""
from __future__ import annotations

from .bundle import Bundle

ZONE_ORDER = ["sbx", "staging", "canary", "prod"]
READ_ONLY_FS = ["/bin", "/usr", "/lib", "/proc", "/dev/urandom", "/app", "/etc", "/var/log"]


def zone_egress(b: Bundle, zone: str) -> list[dict]:
    """Base egress plus every zone's additions up to and including `zone` (cumulative)."""
    pol = b.spec["policy"]
    merged: dict[str, dict] = {}
    for ep in pol.get("egress") or []:
        merged[ep["host"]] = {"host": ep["host"], "access": ep.get("access", "read-only")}
    for z in ZONE_ORDER[: ZONE_ORDER.index(zone) + 1]:
        for ep in (pol.get("zones") or {}).get(z) or []:
            cur = merged.get(ep["host"])
            acc = ep.get("access", "read-only")
            if cur is None or (cur["access"] == "read-only" and acc == "read-write"):
                merged[ep["host"]] = {"host": ep["host"], "access": acc}
    return sorted(merged.values(), key=lambda e: e["host"])


def to_openshell(b: Bundle, zone: str) -> dict:
    pol = b.spec["policy"]
    eg = zone_egress(b, zone)
    doc: dict = {
        "version": 1,
        "filesystem_policy": {"include_workdir": True, "read_only": READ_ONLY_FS,
                              "read_write": list(pol.get("writable") or ["/sandbox", "/tmp"]) + ["/dev/null"]},
        "landlock": {"compatibility": "best_effort"},
    }
    groups: dict[str, list] = {}
    for ep in eg:
        groups.setdefault(ep["access"], []).append(ep)
    if groups:
        doc["network_policies"] = {}
        for access, eps in sorted(groups.items()):
            key = f"{b.name}_{access.replace('-', '_')}"
            doc["network_policies"][key] = {
                "name": f"{b.name}-{access}",
                "endpoints": [{"host": e["host"], "port": 443, "protocol": "rest", "enforcement": "enforce", "access": access} for e in eps],
                "binaries": [{"path": pol["program"]}],
            }
    return doc


def to_substrate(b: Bundle, zone: str) -> tuple[dict, list[str]]:
    eg = zone_egress(b, zone)
    warnings = [f"{e['host']}: '{e['access']}' cannot be enforced per HTTP method in a Substrate EgressPolicy; "
                f"the host is allowed for all methods. Keep this agent on OpenShell if method limits matter."
                for e in eg if e["access"] == "read-only"]
    warnings.append(f"program pinning ({b.spec['policy']['program']}) has no Substrate equivalent; isolation is per actor (gVisor).")
    doc = {"rules": [{"https": {"hostnames": [e["host"] for e in eg]}}]} if eg else {"rules": []}
    return doc, warnings


def compile_zone(b: Bundle, zone: str, runtime: str | None = None) -> tuple[str, dict, list[str]]:
    runtime = runtime or b.spec["runtime"][zone]
    if runtime == "openshell":
        return runtime, to_openshell(b, zone), []
    if runtime == "substrate":
        doc, warns = to_substrate(b, zone)
        return runtime, doc, warns
    raise ValueError(f"unknown runtime {runtime}")
