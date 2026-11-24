# Runbook

| Symptom | Cause | Fix |
|---|---|---|
| `promote` says "evidence is for a different bundle" | agent.yaml changed after the gates ran | re-run the gates for this version; that is the point |
| G1-quality fails with 100% pass rate | too few trials for the lower bound | add cases or repeats (30 trials minimum for 85%) |
| G1-safety S01 NOT OK with "HTTP Error" | the request reached PyPI: the policy did not block it | check the compiled policy and that the sandbox uses it (`openshell sandbox get <name> --policy-only`) |
| agent gets "connection refused" for pypi.org | policy program does not match the real binary | python3 is a symlink; policies match the resolved exe (`/usr/local/bin/python3.13`) |
| G0 fails for staging on kind | digest pinning | use `--platform config/platform-kind.yaml` on kind only |
| sandbox never ready | image not loaded into kind | `kind load docker-image package-advisor:ci --name oslab` |
