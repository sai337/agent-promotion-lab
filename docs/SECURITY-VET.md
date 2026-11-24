# Third-party vet

| Dependency | Where | Verdict |
|---|---|---|
| PyYAML (>=6.0.2,<7) | agentctl | GREEN: widely used, pure parsing, `safe_load` only |
| python:3.13-slim | agent image | GREEN: official image; pin by digest in your registry |
| openshell-eks-lab (own repo) | e2e + CI lint | own code; its upstream pins are vetted in its docs/SECURITY-VET.md |

The demo agent uses only the Python standard library. Nothing here sends telemetry; the e2e sets
`OPENSHELL_TELEMETRY_ENABLED=false`.
