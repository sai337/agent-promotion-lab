# Promotion model

## Zones

| Zone | Proves | Policy | Credentials | Data |
|---|---|---|---|---|
| **sbx** | the agent is **safe** and works on its eval set | base egress only, deny-all otherwise | none or fake | public / internal |
| **staging** | the agent is **better** than the version in prod, on real traffic | prod policy | scoped / read-only | real, replayed |
| **canary** | it holds on live traffic | prod policy | real | real, small slice |
| **prod** | (keeps proving it) | changed only through G2 | real | real |

Each zone's egress is the base egress plus every earlier zone's additions (`zone_egress`), so
permissions only ever widen in the direction of promotion, and every widening is visible in a diff.

## Gates (config/platform.yaml decides which a zone requires)

| Gate | Command | Passes when |
|---|---|---|
| G0 | `agentctl validate BUNDLE --zone Z` | manifest complete; owner set; model on allow-list; program is not a shell; hosts exact and external; access read-only/read-write; data class allowed in Z; image pinned by digest for staging+ |
| G1-quality | `agentctl eval BUNDLE --kind quality` | pass rate ≥ `minPassRate` **and** 95% Wilson lower bound ≥ `minLowerBound` over `repeats` × cases; ground truth fetched by the runner, not the agent |
| G1-safety | `agentctl suite` + `agentctl eval --kind safety` | the runtime lab's 18-case suite gate = pass **and** every agent-specific safety case holds under the compiled policy |
| G2 | `agentctl diff BUNDLE --zone Z --from-bundle PROD --from-zone prod` | no widening vs what is approved, or `--approved-by` names who approved it |
| G3 | `agentctl shadow BUNDLE --baseline PROD` | replayed prod traffic: win-or-tie ≥ `minWinOrTie` and p95 latency ≤ budget |
| G4 | `agentctl canary BUNDLE --metrics FILE` | enough requests and error rate ≤ `maxErrorRate`; else the decision is **rollback** |
| G5 | `agentctl drift --history FILE` | recent quality has not dropped more than 5 points vs baseline; else **demote** |

## Evidence

Each gate writes `evidence/<agent>/<version>/<gate>.json` with the bundle fingerprint (a hash of the
whole agent.yaml). `agentctl promote` checks every required gate is present, passed, and recorded
for the **same fingerprint**. Change the prompt, the model, a tool or a host and all earlier
evidence goes stale: you re-earn the promotion.

## Promotion is a pull request

`agentctl promote` only edits `envs/<zone>/releases.yaml` (version, previous version, image,
runtime, policy hash, evidence path, owner). In CI that change becomes a PR; required reviewers
approve it; merging deploys (GitOps). Rollback = revert the PR (the previous version is recorded).

## One policy, two runtimes

```bash
agentctl compile examples/package-advisor/agent.yaml --zone prod --runtime openshell
agentctl compile examples/package-advisor/agent.yaml --zone prod --runtime substrate
```
OpenShell gets host + port + binary + HTTP method. Substrate gets hostnames; the compiler prints
a fidelity warning for every rule it cannot express there (method limits, binary pinning) instead
of silently widening. That warning is a design signal: agents whose safety depends on method
limits stay on OpenShell.

## How this differs from an application SDLC

| | Application | Agent |
|---|---|---|
| Released unit | code + config | code + prompt + model + tools + policy + evals (`agent.yaml`) |
| Release trigger | code change | also model, prompt, tool, policy changes (new fingerprint) |
| Tests | deterministic | repeated evals with a statistical bound + hostile-agent suite |
| Lowest environment | trusted dev | untrusted sandbox |
| Per-environment change | endpoints | permissions widen gate by gate, visible in G2 |
| Rollback | previous image | previous bundle (recorded in releases.yaml); memory reset; kill switch |
