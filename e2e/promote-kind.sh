#!/usr/bin/env bash
# End to end on kind: take package-advisor 1.1.0 from sbx to prod through every gate,
# with the agent running inside real NVIDIA OpenShell sandboxes.
#   1. platform: kind + Calico + Agent Sandbox + OpenShell (from openshell-eks-lab)
#   2. G1 platform suite: the 18 hostile-agent cases
#   3. sbx: G0, compiled sbx policy, G1 quality + safety inside the sandbox, G2 vs prod
#   4. staging: shadow replay vs the current prod version (1.0.0), G3
#   5. canary: 40 live requests, G4
#   6. prod: promote; envs/*/releases.yaml + evidence/ are the record
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WORK="$ROOT/.work"; mkdir -p "$WORK"
LAB="${OPENSHELL_LAB:-$WORK/openshell-eks-lab}"
export OPENSHELL_TELEMETRY_ENABLED=false PYTHONPATH="$ROOT/app"
B=examples/package-advisor/agent.yaml
BASE=examples/package-advisor/agent-v1.0.0.yaml
P=(--platform config/platform-kind.yaml)
ctl() { python3 -m agentctl.cli "${P[@]}" "$@"; }
log() { printf '\n==> %s\n' "$*"; }
# kubectl port-forward degrades on long runs; refresh it before each phase.
pf() {
  [ -f "$LAB/.work/port-forward.pid" ] && kill "$(cat "$LAB/.work/port-forward.pid")" 2>/dev/null || true
  nohup kubectl -n openshell port-forward svc/openshell "${OSLAB_PORT:-18080}:8080" >"$LAB/.work/port-forward.log" 2>&1 &
  echo $! > "$LAB/.work/port-forward.pid"
  for _ in $(seq 1 20); do (echo >"/dev/tcp/127.0.0.1/${OSLAB_PORT:-18080}") 2>/dev/null && return 0; sleep 1; done
}

log "1. platform from openshell-eks-lab"
[ -d "$LAB/.git" ] || git clone -q --depth 1 https://github.com/sai337/openshell-eks-lab "$LAB"
bash "$LAB/e2e/up.sh"
export OPENSHELL_GATEWAY=oslab-kind

log "2. G1 platform suite (18 hostile-agent cases)"
OSLAB_OUT="$WORK/suite" bash "$LAB/e2e/run.sh"
ctl suite "$B" --results "$WORK/suite/results.json"

log "agent image"
docker build -q -t package-advisor:ci examples/package-advisor/agent
kind load docker-image package-advisor:ci --name "${KIND_CLUSTER_NAME:-oslab}"

sandbox() { # name bundle zone
  ctl compile "$2" --zone "$3" --out "$WORK/$1.yaml"
  openshell sandbox delete "$1" >/dev/null 2>&1 || true
  openshell sandbox create --name "$1" --from package-advisor:ci --policy "$WORK/$1.yaml" \
    --no-auto-providers --no-tty --detach -- sleep infinity
  for _ in $(seq 1 60); do
    openshell sandbox exec -n "$1" --no-login-shell -- true >/dev/null 2>&1 && return 0; sleep 3
  done
  echo "sandbox $1 never became ready" >&2; return 1
}

log "3. sbx zone"
pf
ctl validate "$B" --zone sbx
ctl promote "$B" --zone sbx
sandbox pa-sbx "$B" sbx
ctl eval "$B" --kind quality --exec openshell --sandbox pa-sbx --zone sbx
ctl eval "$B" --kind safety --exec openshell --sandbox pa-sbx --zone sbx
ctl diff "$B" --zone staging --from-bundle "$BASE" --from-zone prod

log "4. staging: shadow replay vs current prod (1.0.0)"
pf
ctl validate "$B" --zone staging
ctl promote "$B" --zone staging
sandbox pa-stg "$B" staging
sandbox pa-prod "$BASE" prod
ctl shadow "$B" --baseline "$BASE" --exec openshell --sandbox pa-stg --baseline-sandbox pa-prod

log "5. canary: live requests"
pf
ctl validate "$B" --zone canary
ctl promote "$B" --zone canary
sandbox pa-can "$B" canary
ctl canary "$B" --exec openshell --sandbox pa-can

log "6. prod"
pf
ctl validate "$B" --zone prod
ctl promote "$B" --zone prod
ctl status "$B"

for s in pa-sbx pa-stg pa-prod pa-can; do openshell sandbox delete "$s" >/dev/null 2>&1 || true; done
log "done: evidence/ and envs/*/releases.yaml hold the record"
