# Architecture

```mermaid
flowchart LR
  subgraph Repo["Git repo (source of truth)"]
    A[agent.yaml bundle] --> CTL[agentctl]
    PL[config/platform.yaml] --> CTL
    CTL --> EV[(evidence/agent/version/*.json)]
    CTL --> REL[envs/zone/releases.yaml]
  end
  CTL -- compile --> OSP[OpenShell policy]
  CTL -- compile --> SUP[Substrate EgressPolicy]
  subgraph Cluster["Kubernetes (kind or EKS)"]
    SBX[sbx sandbox] --- STG[staging sandbox] --- CAN[canary sandbox] --- PRD[prod]
  end
  OSP --> SBX & STG & CAN & PRD
  SUP -.-> PRD
  SBX -- evals + safety --> CTL
  STG -- shadow vs prod --> CTL
  CAN -- live metrics --> CTL
  REL -- PR + review --> GIT[GitOps deploy]
```

| Component | Role |
|---|---|
| `agent.yaml` | the bundle: image, model, prompt, tools, data class, runtime per zone, one policy, evals, shadow and canary budgets |
| `config/platform.yaml` | platform rules: zones, runtimes, model allow-list, data classes per zone, gates required per zone, digest pinning |
| `agentctl` | validates, compiles policies, runs evals inside sandboxes, records evidence, promotes |
| `evidence/` | one JSON per gate per bundle version, tied to the bundle fingerprint |
| `envs/<zone>/releases.yaml` | desired state per zone; changed only by `agentctl promote` through a PR |
| openshell-eks-lab | runtime + 18-case suite used for G1-safety and to run the sandboxes |
| agent-substrate-lab | runtime for prod fleets of stateful agents; consumes the compiled EgressPolicy |

The runner fetches ground truth itself, outside the sandbox, so the agent cannot grade its own work.
