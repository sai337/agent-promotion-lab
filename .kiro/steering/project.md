---
inclusion: always
---
# agent-promotion-lab: working rules

Goal: run the promotion pipeline end to end (sbx → staging → canary → prod) for the
package-advisor agent, first on kind (`bash e2e/promote-kind.sh`), then on the EKS cluster created
by openshell-eks-lab (docs/DEPLOYMENT.md, "EKS").

Rules
- AWS: only `$AWS_PROFILE` (personal lab account); tear the cluster down afterwards via openshell-eks-lab.
- Use `config/platform.yaml` (digest pinning on) for EKS; `config/platform-kind.yaml` only on kind.
- Never hand-edit `envs/*/releases.yaml` or `evidence/`: only `agentctl` writes them.
- Commits: author `sai337 <sai.devop@gmail.com>`, no co-author or tool attribution lines. No secrets or account IDs.

Definition of done
1. `pytest -q` passes.
2. `agentctl status examples/package-advisor/agent.yaml` shows PASS for G0, G1-quality, G1-safety, G2, G3, G4 and "may enter prod: yes".
3. `evidence/package-advisor/1.1.0/` and `envs/prod/releases.yaml` committed on a branch with a PR.
4. On EKS: the same, with `--platform config/platform.yaml` and the image pinned by ECR digest.

## Read first
- docs/GUIDE.md explains every component, flow, command and signal in plain words. Use it to explain results to the owner.
- docs/DEPLOYMENT.md is the exact EKS procedure. Personal lab AWS account only; destroy when done.
