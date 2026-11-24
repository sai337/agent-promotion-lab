import copy

import pytest
import yaml

from agentctl.bundle import Bundle, load, load_platform, validate
from agentctl.compile import compile_zone, to_openshell, to_substrate, zone_egress
from agentctl.diff import diff

from conftest import EXAMPLE, ROOT

PLATFORM = load_platform(ROOT / "config/platform.yaml")


def bundle(mutate=None):
    b = load(EXAMPLE / "agent.yaml")
    raw = copy.deepcopy(b.raw)
    if mutate:
        mutate(raw)
    return Bundle(b.path, raw, raw["metadata"]["name"], str(raw["metadata"]["version"]), raw["metadata"].get("owner", ""), raw["spec"])


def test_example_bundle_valid_for_sbx():
    assert validate(bundle(), PLATFORM, "sbx") == []


def test_staging_requires_pinned_digest():
    errs = validate(bundle(), PLATFORM, "staging")
    assert any("pinned by digest" in e for e in errs)
    pinned = bundle(lambda r: r["spec"].__setitem__("image", "reg/pa@sha256:" + "a" * 64))
    assert validate(pinned, PLATFORM, "staging") == []


@pytest.mark.parametrize("mutate,msg", [
    (lambda r: r["spec"]["policy"].__setitem__("program", "/bin/bash"), "shell"),
    (lambda r: r["spec"]["policy"]["egress"].append({"host": "*.github.com"}), "exact hostname"),
    (lambda r: r["spec"]["policy"]["egress"].append({"host": "169.254.169.254"}), "points into the platform"),
    (lambda r: r["spec"]["policy"]["egress"].append({"host": "kubernetes.default.svc"}), "points into the platform"),
    (lambda r: r["spec"]["policy"]["egress"].append({"host": "x.com", "access": "full"}), "access must be"),
    (lambda r: r["spec"].__setitem__("model", "random/model"), "allow-list"),
    (lambda r: r["spec"]["policy"]["zones"].pop("prod"), "policy.zones.prod"),
    (lambda r: r["spec"]["policy"]["writable"].append("/etc"), "system path"),
    (lambda r: r["metadata"].pop("owner"), "owner"),
    (lambda r: r["metadata"].__setitem__("version", "v1"), "semver"),
])
def test_g0_rejects(mutate, msg):
    assert any(msg in e for e in validate(bundle(mutate), PLATFORM, "sbx"))


def test_confidential_data_never_in_sbx():
    b = bundle(lambda r: r["spec"].__setitem__("dataClass", "confidential"))
    assert any("not allowed in zone sbx" in e for e in validate(b, PLATFORM, "sbx"))


def test_zone_policies_are_cumulative():
    def add(r):
        r["spec"]["policy"]["zones"]["staging"] = [{"host": "api.example.com"}]
        r["spec"]["policy"]["zones"]["prod"] = [{"host": "api.example.com", "access": "read-write"}]
    b = bundle(add)
    assert [e["host"] for e in zone_egress(b, "sbx")] == ["pypi.org"]
    assert {e["host"]: e["access"] for e in zone_egress(b, "canary")} == {"api.example.com": "read-only", "pypi.org": "read-only"}
    assert {e["host"]: e["access"] for e in zone_egress(b, "prod")}["api.example.com"] == "read-write"


def test_openshell_output_is_enforced_l7_and_pinned():
    doc = to_openshell(bundle(), "sbx")
    rule = next(iter(doc["network_policies"].values()))
    assert all(e["enforcement"] == "enforce" and e["protocol"] == "rest" and e["access"] == "read-only" for e in rule["endpoints"])
    assert rule["binaries"] == [{"path": "/usr/local/bin/python3.13"}]
    assert "/etc" not in doc["filesystem_policy"]["read_write"]


def test_substrate_output_and_fidelity_warnings():
    doc, warns = to_substrate(bundle(), "prod")
    assert doc == {"rules": [{"https": {"hostnames": ["pypi.org"]}}]}
    assert any("cannot be enforced per HTTP method" in w for w in warns)
    runtime, _, w2 = compile_zone(bundle(lambda r: r["spec"]["runtime"].__setitem__("prod", "substrate")), "prod")
    assert runtime == "substrate" and w2


def test_diff_detects_every_widening():
    old = load(EXAMPLE / "agent-v1.0.0.yaml")
    assert [c for c in diff(old, "prod", bundle(), "prod") if c.widening] == []

    def widen(r):
        r["spec"]["policy"]["zones"]["prod"] = [{"host": "upload.pypi.org", "access": "read-write"}]
        r["spec"]["model"] = "gateway/claude-sonnet"
        r["spec"]["tools"] = ["mcp://search"]
        r["spec"]["policy"]["writable"].append("/data")
    kinds = {c.kind for c in diff(old, "prod", bundle(widen), "prod") if c.widening}
    assert kinds == {"host", "model", "tools", "filesystem"}


def test_fingerprint_changes_with_behaviour():
    a, b2 = bundle(), bundle(lambda r: r["spec"].__setitem__("prompt", "prompts/advisor@v3"))
    assert a.fingerprint() != b2.fingerprint() and a.fingerprint() == bundle().fingerprint()


def test_example_files_parse():
    for f in ("evals/golden.yaml", "evals/safety.yaml", "evals/shadow-traffic.yaml"):
        assert yaml.safe_load((EXAMPLE / f).read_text())
