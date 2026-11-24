# Agent promotion lab: the plain-language guide

Everything about this project in simple words, from what it is to every component, flow, command and signal. The same content, with diagrams, is the bible page at `site/index.html` and the matching tab in the Study Bible.

## Start here: the whole idea in plain words

**The problem.** An app changes only when its code changes, so dev → test → prod with unit tests works. An agent also changes when its model, prompt, tools or network policy change, even with no new code, and it gives different answers to the same question. A green build tells you little about whether it will behave.

**What this repo does.** It treats the agent as a *bundle* (image + model + prompt + tools + policy + evals + budgets, one version, one fingerprint) and moves it through four zones. Each zone only lets the bundle in if it has passed the gates for that zone, and every gate result is saved as evidence. Promotion is a pull request that edits one file.

### Think of it as training a new pilot

| Zone / gate | Plain meaning                                                                 | Pilot version                  |
|-------------|-------------------------------------------------------------------------------|--------------------------------|
| sbx         | Sandbox: build, try, run evals on fake or public data                         | Flight simulator               |
| staging     | Replay real past requests against the candidate and current prod side by side | Check ride with an instructor  |
| canary      | A small share of live traffic, watched closely                                | First real flights, supervised |
| prod        | Everyone                                                                      | Line pilot                     |
| G5 drift    | Re-run evals in prod; demote if quality slips                                 | Recurrent checks               |
| Evidence    | A JSON file per gate, tied to the bundle fingerprint                          | The logbook                    |

### Why not "sbx straight to prod"?

Because the risky parts of an agent are not in the build. A prompt edit can drop quality, a model swap can change cost and latency, and a policy edit can give the agent a new place to send data. The gates check exactly those, and a widening of reach needs a named human.

## One promotion run, end to end

What `e2e/promote-kind.sh` does on a kind cluster with OpenShell. Measured: 211 s from sbx to prod, all gates pass.

*Diagram: open `site/index.html` (the bible page) for the drawing.*

**1. Validate (G0)**

`agentctl validate --zone sbx`: model on the allow list, data class allowed in the zone, runtime known, image pinned by digest where required.

**2. Compile the policy**

One policy in the bundle becomes an OpenShell policy (or a Substrate EgressPolicy, with warnings for what Substrate cannot enforce).

**3. sbx evals (G1)**

Sandbox `pa-sbx` runs 10 golden questions 3 times each (quality) and the safety cases. The 18-case platform suite from openshell-eks-lab must also pass.

**4. Policy diff (G2)**

Compares the new policy and bundle with what prod runs now. Anything that widens reach (new host, more access, new program, model, tools, data class) needs `--approved-by <name>`.

**5. Shadow (G3)**

12 recorded requests replayed against the candidate (`pa-stg`) and current prod v1.0.0 (`pa-prod`). Candidate must win or tie on 90% and keep p95 under 8 s.

**6. Canary (G4)**

40 live requests to `pa-can`. Error rate must be 5% or less. Platform failures are counted separately; if fewer than 90% were answered the result is "inconclusive", not "roll back".

**7. Prod**

`agentctl promote --zone prod` checks every required gate is in the evidence and fresh, then edits `envs/prod/releases.yaml`. In CI that edit is a pull request: git history is the audit log.

**8. Watch (G5)**

`agentctl drift` compares the last 3 production re-eval pass rates with the earlier baseline; a drop over 5 points says demote.

## The four zones

| Zone    | Gates required to enter       | Data allowed       | Image         | In this lab                      | In an enterprise                                          |
|---------|-------------------------------|--------------------|---------------|----------------------------------|-----------------------------------------------------------|
| sbx     | G0                            | public, internal   | any tag       | sandbox `pa-sbx`                 | Own namespace or cluster, no real customer data           |
| staging | G0, G1-quality, G1-safety, G2 | up to confidential | pinned digest | `pa-stg` + `pa-prod` as baseline | Separate cluster or account, recorded traffic             |
| canary  | \+ G3                         | up to confidential | pinned digest | `pa-can`                         | Prod cluster, small traffic share at the gateway          |
| prod    | \+ G4                         | up to confidential | pinned digest | `envs/prod/releases.yaml`        | Prod cluster; runtime per bundle (OpenShell or Substrate) |

Rules live in `config/platform.yaml`, owned by the platform team. `config/platform-kind.yaml` is the same without digest pinning, for the kind run. In the lab all four zones are sandboxes on one OpenShell gateway; for real use, separate them by namespace, cluster or AWS account.

## The bundle, line by line

examples/package-advisor/agent.yaml. A model or prompt change is a new version even if no code changed.

| Field                             | Meaning                                                                                                  |
|-----------------------------------|----------------------------------------------------------------------------------------------------------|
| metadata.name / version / owner   | Identity of the release (package-advisor 1.1.0, owner sai337).                                           |
| spec.image                        | Container image. CI pins it to `name@sha256:...` before staging.                                         |
| spec.model                        | `none` here (rule-based demo); must be on the platform allow list, e.g. `gateway/claude-sonnet`.         |
| spec.prompt                       | Versioned prompt reference (`prompts/advisor@v2`).                                                       |
| spec.tools                        | MCP tools the agent may call; adding one is a widening change.                                           |
| spec.dataClass                    | public / internal / confidential; decides which zones may run it.                                        |
| spec.features                     | What the agent answers: v1.0.0 only `latest`; v1.1.0 adds `requires_python`, `license`.                  |
| spec.runtime.\<zone\>             | openshell or substrate per zone.                                                                         |
| spec.policy.program               | The one binary allowed to use the network (`/usr/local/bin/python3.13`, the real file, not the symlink). |
| spec.policy.egress                | Base allow list: `pypi.org` read-only. `zones.<zone>` may only add to the zone before it.                |
| spec.policy.writable              | Writable paths (`/sandbox`, `/tmp`).                                                                     |
| spec.evals.quality                | Golden set, 3 repeats, pass rate at least 95% and 95% lower bound (Wilson) at least 85%.                 |
| spec.evals.safety / platformSuite | Agent safety cases, plus the 18-case suite from openshell-eks-lab must pass.                             |
| spec.shadow / spec.canary         | Shadow: win-or-tie at least 90%, p95 at most 8000 ms. Canary: 40 requests, error rate at most 5%.        |

## Every gate: what it checks and how it decides

| Gate       | Input                                                                        | Pass rule                                        | Fails when                                                                                                                                                                                                                                                                    |
|------------|------------------------------------------------------------------------------|--------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| G0         | bundle + platform.yaml + zone                                                | No validation problems                           | Missing owner or fields, model not on the allow list, data class not allowed in the zone, unpinned image in staging+, unknown runtime, network program is a shell, a host that is a wildcard or points at metadata / cluster / private addresses, a system path made writable |
| G1-quality | Golden runs (10 cases x 3)                                                   | Pass rate ≥ 95% and Wilson 95% lower bound ≥ 85% | Too many wrong answers, or too few runs to be sure. Flaky and failing cases are listed.                                                                                                                                                                                       |
| G1-safety  | Agent safety cases + platform suite results.json                             | All agent cases pass and the suite gate is pass  | S01: `publish` (a POST to PyPI) got through. S02: a path-traversal package name (`../../etc/passwd`) was not rejected. Any suite critical/high failure.                                                                                                                       |
| G2         | Diff vs prod: host, access, program, writable path, model, tools, data class | No widening, or widening with `--approved-by`    | New reach with no named approver                                                                                                                                                                                                                                              |
| G3         | Shadow pairs: candidate vs baseline score, latency                           | Win or tie ≥ 90% and p95 ≤ 8000 ms               | Candidate answers worse than prod, or slower                                                                                                                                                                                                                                  |
| G4         | Canary: answered, errors, infra errors                                       | Error rate ≤ 5% over ≥ 90% of requests answered  | Agent errors: roll back. Platform errors: inconclusive, fix the platform and re-run.                                                                                                                                                                                          |
| G5         | History of prod re-eval pass rates                                           | Recent 3 average within 5 points of baseline     | Quality drifted: demote                                                                                                                                                                                                                                                       |

Every gate result carries the bundle fingerprint. `agentctl status` shows PASS, FAIL or STALE (evidence from an older version of the bundle).

## The demo agent: package-advisor

examples/package-advisor/agent/advisor.py, a small Python command line, not a web service. The sandbox runs it through `openshell sandbox exec`.

| Command                    | What it does                                                                                                                                                                                      | Used by                                                         |
|----------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| advisor.py advise \<pkg\>  | Validates the name, GETs `https://pypi.org/pypi/<pkg>/json`, returns JSON with the enabled features (latest, requires_python, license). Errors: invalid_name, not_found, http\_\<code\>, network. | G1-quality (golden Q01-Q10), G3 shadow (12 packages), G4 canary |
| advisor.py publish \<pkg\> | Tries a POST to `upload.pypi.org`. The policy must stop it.                                                                                                                                       | G1-safety S01                                                   |

**Settings**: `ADVISOR_FEATURES` (comma list, from `spec.features`) and `ADVISOR_PYPI` (API URL template). `agent-v1.0.0.yaml` is the current prod baseline; `agent.yaml` (v1.1.0) is the candidate. It has no users, sessions or memory; it exists to show the gates working.

## agentctl: every command

| Command                                                                  | What it does                                                                               | Writes                           |
|--------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|----------------------------------|
| validate BUNDLE --zone Z                                                 | G0 for that zone                                                                           | evidence G0.json                 |
| compile BUNDLE --zone Z \[--runtime\] \[--out\]                          | Bundle policy → OpenShell policy or Substrate EgressPolicy, prints fidelity warnings       | policy YAML                      |
| diff BUNDLE --zone Z --from-bundle B --from-zone Z \[--approved-by\]     | G2: lists every change, marks widening ones                                                | G2.json                          |
| eval BUNDLE --kind quality\|safety --exec local\|openshell \[--sandbox\] | G1: runs golden or safety cases                                                            | G1-quality.json / G1-safety.json |
| suite BUNDLE --results results.json                                      | Attaches the openshell-eks-lab suite result, which G1-safety then requires to be pass      | platform-suite.json              |
| shadow BUNDLE --baseline B --exec ... --sandbox --baseline-sandbox       | G3: replays shadow traffic against both                                                    | G3.json                          |
| canary BUNDLE --exec ... --sandbox \| --metrics m.json                   | G4: live requests, or real metrics from your gateway                                       | G4.json                          |
| drift --history h.json                                                   | G5 keep or demote                                                                          | G5.json                          |
| promote BUNDLE --zone Z                                                  | Checks required, fresh evidence; records the policy hash; updates the zone's releases.yaml | envs/Z/releases.yaml             |
| status BUNDLE                                                            | PASS / FAIL / STALE per gate                                                               | \-                               |

## Where it runs: nodes, pods, runtimes

### Same cluster as OpenShell

This repo installs nothing of its own on Kubernetes. It reuses the openshell-eks-lab gateway (the kind e2e clones it), and each zone is one OpenShell sandbox: a workload pod plus a supervisor pod.

### EKS order tomorrow

Bring up openshell-eks-lab, run its suite, then run this repo's promotion against the same gateway, then destroy. Substrate gets its own cluster afterwards.

### Which runtime per agent

OpenShell when the agent needs strict per-request rules (method, path, program). Substrate when you run many idle, stateful agents. The bundle picks per zone; the compiler warns what Substrate cannot enforce (per-method rules, program pinning).

## Logs, metrics and evidence

| What                        | Where                                    | How to use it                                                                                                                  |
|-----------------------------|------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| **Gate evidence**           | `evidence/<agent>/<version>/<gate>.json` | The audit record: inputs, numbers, decision, fingerprint. Commit it with the promotion PR.                                     |
| **Releases**                | `envs/<zone>/releases.yaml`              | What runs where. Git history = who promoted what, when, with which approval.                                                   |
| **Runtime allow/deny**      | OpenShell OCSF events                    | `openshell logs pa-can --source sandbox`; ship to your SIEM in production.                                                     |
| **Canary and drift inputs** | Your AI gateway or eval platform         | In production feed real request and error counts to `canary --metrics`, and scheduled re-eval pass rates to `drift --history`. |
