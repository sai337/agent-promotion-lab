# LinkedIn

**One line**
AI agents shouldn't go from sandbox straight to prod. I built an open-source pipeline where an agent earns each step (evals with a statistical bound, an 18-attack safety suite, a policy diff, shadow replay against prod, a canary), and one policy compiles to both NVIDIA OpenShell and CNCF Agent Substrate. <article link>

**Longer variant**
"How do we get our agents from the sandbox to production?" Adding evals to CI is not enough. An agent's release is its image plus model, prompt, tools, data and what it can reach, and any of those can change with no code change.

So I built it: the agent bundle is the unit of release, and it moves sandbox → staging → canary → prod only with evidence: 30/30 quality runs with a 95% lower bound, 18/18 hostile-agent attacks blocked, no permission widening, 12/12 wins against the prod version on replayed traffic, 0 errors in canary. Sandbox to prod in about 3.5 minutes on Kubernetes.

Open source: <repo link>
#AIAgents #PlatformEngineering #MLOps #Kubernetes #AISecurity
