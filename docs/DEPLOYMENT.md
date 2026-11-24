# Deployment

## Local (no cluster, 2 min)

```bash
git clone https://github.com/sai337/agent-promotion-lab && cd agent-promotion-lab
pip install -e '.[test]' && pytest -q
agentctl validate examples/package-advisor/agent.yaml --zone sbx
agentctl compile  examples/package-advisor/agent.yaml --zone prod --runtime openshell
agentctl compile  examples/package-advisor/agent.yaml --zone prod --runtime substrate
agentctl eval     examples/package-advisor/agent.yaml --kind quality --exec local   # agent on your machine, real PyPI
agentctl status   examples/package-advisor/agent.yaml
```

## POC on kind (about 10 min; this is what `promote-kind.yml` runs)

Needs Docker, kind, kubectl, helm, Python 3.11+.
```bash
bash e2e/promote-kind.sh
```
It clones openshell-eks-lab, brings up kind + Calico + Agent Sandbox + OpenShell, runs the 18-case
suite, then takes package-advisor 1.1.0 through sbx → staging (shadow vs 1.0.0) → canary → prod
with the agent inside real sandboxes. Results: `evidence/package-advisor/1.1.0/` and `envs/*/releases.yaml`.

## EKS (with openshell-eks-lab's cluster)

The promotion pipeline runs against any OpenShell gateway. On EKS:

1. Bring up the cluster and gateway with openshell-eks-lab (its docs/DEPLOYMENT.md, steps 0-2).
2. Push the agent image to the ECR repo and pin it in the bundle:
   ```bash
   REPO=$(terraform -chdir=../openshell-eks-lab/infra/eks/terraform output -raw ecr_repository_url)
   docker build --platform linux/amd64 -t "$REPO:pa-1.1.0" examples/package-advisor/agent && docker push "$REPO:pa-1.1.0"
   DIGEST=$(docker inspect --format '{{index .RepoDigests 0}}' "$REPO:pa-1.1.0")
   sed -i.bak "s#image: package-advisor:dev.*#image: $DIGEST#" examples/package-advisor/agent.yaml
   ```
3. Run the same flow with the strict platform file (digest pinning on) and sandboxes on the tainted nodes:
   ```bash
   export OPENSHELL_GATEWAY=oslab-eks
   # same steps as e2e/promote-kind.sh from "3. sbx zone", with --platform config/platform.yaml,
   # --from "$DIGEST", and --driver-config-json "$(cat ../openshell-eks-lab/e2e/eks-driver-config.json)" on sandbox create
   ```
4. Commit `evidence/` and `envs/` on a branch and open the promotion PR.
5. Tear down with openshell-eks-lab step 5.

For Substrate as the prod runtime, set `spec.runtime.prod: substrate`, compile with
`--runtime substrate`, and apply the result as the actor's EgressPolicy in agent-substrate-lab
(`kubectl ate create egress-policy <actor> -a <atespace> -f -`).

## Repo settings for the promotion PR

Settings → Actions → General → "Allow GitHub Actions to create and approve pull requests", then run
`promote-kind` with `open_pr: true`. Add yourself as a required reviewer on `envs/prod/` with CODEOWNERS.
