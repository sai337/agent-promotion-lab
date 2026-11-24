# Threat model (of the promotion pipeline)

| # | Threat | Control |
|---|---|---|
| P1 | Privilege creep rides along with a feature ("just one more host") | G2 diff on the runtime-neutral policy; widening needs a named approver |
| P2 | A prompt or model change ships without re-testing | bundle fingerprint: any change makes all evidence stale |
| P3 | A lucky run promotes a worse agent | repeats + Wilson lower bound; flaky cases listed |
| P4 | The agent grades itself | ground truth fetched by the runner, outside the sandbox |
| P5 | Works on test data, fails on real traffic | G3 shadow replay vs current prod |
| P6 | Live regression reaches everyone | G4 canary with an automatic rollback decision |
| P7 | Silent decay after release | G5 drift check demotes |
| P8 | Unpinned or swapped image | G0 requires a digest for staging and later |
| P9 | Confidential data in a sandbox | G0 data-class rule per zone |
| P10 | Policy semantics lost when moving runtimes | compiler fidelity warnings (method limits, binary pinning) |
| P11 | Someone edits releases.yaml by hand | promotion is a PR with required reviewers (CODEOWNERS on envs/prod) |
| P12 | Evidence forged in the repo | evidence produced by CI runs and linked to the run; sign evidence (next) |

Not covered yet: signing evidence and images (cosign), memory and state promotion for stateful agents
(never copy snapshots between zones), multi-agent dependencies.
