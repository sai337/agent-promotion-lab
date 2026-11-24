"""Agent bundles (agent.yaml): load, validate (G0 manifest checks), fingerprint."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
ACCESS = ("read-only", "read-write")  # "full" is never allowed for agents
INTERNAL_SUFFIXES = (".svc", ".cluster.local", ".internal", "localhost")


@dataclass
class Bundle:
    path: Path
    raw: dict
    name: str = ""
    version: str = ""
    owner: str = ""
    spec: dict = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return self.path.parent

    def fingerprint(self) -> str:
        """Stable hash of the whole bundle: any behaviour-relevant change gives a new one."""
        canon = json.dumps(self.raw, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()


def load_platform(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text())


def load(path: str | Path) -> Bundle:
    p = Path(path)
    raw = yaml.safe_load(p.read_text()) or {}
    md = raw.get("metadata") or {}
    return Bundle(p, raw, md.get("name", ""), str(md.get("version", "")), md.get("owner", ""), raw.get("spec") or {})


def is_internal_host(host: str) -> bool:
    h = host.lower().rstrip(".")
    if h == "localhost" or h.endswith(INTERNAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def validate(b: Bundle, platform: dict, zone: str | None = None) -> list[str]:
    """G0 manifest checks. Returns a list of problems (empty = pass)."""
    errs: list[str] = []
    if b.raw.get("kind") != "AgentBundle":
        errs.append("kind must be AgentBundle")
    if not b.name or not re.match(r"^[a-z][a-z0-9-]{1,40}$", b.name):
        errs.append("metadata.name must be a lowercase DNS label")
    if not SEMVER.match(b.version):
        errs.append("metadata.version must be semver (x.y.z)")
    if not b.owner:
        errs.append("metadata.owner is required: every agent has an accountable owner")
    s = b.spec
    for key in ("image", "model", "prompt", "dataClass", "runtime", "policy", "evals"):
        if key not in s:
            errs.append(f"spec.{key} is required")
    if s.get("model") not in platform["modelAllowList"]:
        errs.append(f"model {s.get('model')!r} is not on the platform allow-list")
    if s.get("dataClass") not in platform["dataClasses"]:
        errs.append(f"dataClass {s.get('dataClass')!r} unknown")
    if zone and s.get("dataClass") not in platform["zoneDataClasses"][zone]:
        errs.append(f"dataClass {s.get('dataClass')} is not allowed in zone {zone}")
    if zone in platform.get("pinnedImageZones", []) and "@sha256:" not in str(s.get("image", "")):
        errs.append(f"image must be pinned by digest (name@sha256:...) to enter {zone}")
    rt = s.get("runtime") or {}
    for z in platform["zones"]:
        if rt.get(z) not in platform["runtimes"]:
            errs.append(f"spec.runtime.{z} must be one of {platform['runtimes']}")
    pol = s.get("policy") or {}
    if not str(pol.get("program", "")).startswith("/"):
        errs.append("policy.program must be an absolute path to the one binary allowed on the network")
    if str(pol.get("program", "")) in ("/bin/sh", "/bin/bash", "/usr/bin/env"):
        errs.append("policy.program cannot be a shell: that would allow every program")
    zones = pol.get("zones") or {}
    for z in platform["zones"]:
        if z not in zones:
            errs.append(f"policy.zones.{z} is required (use [] for no additions)")
    for where, eps in [("egress", pol.get("egress") or [])] + [(f"zones.{z}", zones.get(z) or []) for z in zones]:
        for ep in eps:
            host = str(ep.get("host", ""))
            if not host or "*" in host:
                errs.append(f"policy.{where}: host {host!r} must be an exact hostname")
            elif is_internal_host(host):
                errs.append(f"policy.{where}: {host} points into the platform (metadata/cluster/private)")
            if ep.get("access", "read-only") not in ACCESS:
                errs.append(f"policy.{where}: {host} access must be one of {ACCESS}")
    for w in pol.get("writable") or []:
        if "/" + str(w).strip("/") in ("/", "/etc", "/usr", "/bin", "/lib", "/root") or str(w).startswith(("/etc", "/usr")):
            errs.append(f"policy.writable: {w} is a system path")
    q = (s.get("evals") or {}).get("quality") or {}
    if not (0 < float(q.get("minPassRate", 0)) <= 1) or int(q.get("repeats", 0)) < 1:
        errs.append("evals.quality needs repeats >= 1 and 0 < minPassRate <= 1")
    return errs
