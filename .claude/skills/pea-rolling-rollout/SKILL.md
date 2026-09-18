---
name: pea-rolling-rollout
description: Roll a compose/config/code change out to PEA's GPU containers one at a time with health gating, then prove a plain deploy is a no-op. Use whenever gpu-server changes must reach running containers on PEA (192.168.70.144).
---

Proven on 2026-09-18 (`bound-llama-host-prompt-cache`, `expose-llama-server-metrics`). Remote writes on PEA need the owner's explicit go-ahead; read-only probes do not.

## 1. Before touching PEA

- Commit and push, and let CI pass (`gh run list --workflow gpu-build.yml -L1`). `gpu-server/scripts/check-memory-budget.py` must pass locally.
- Confirm no HeartCode evaluation is running on the routes you will restart (ask, or check the HeartCode repo's evaluation log).
- `ssh 192.168.70.144 'cd /home/boss/local-ai && git status --porcelain'`: clear untracked files that collide with incoming paths first (see memory `pea-git-pull-untracked-conflict`).

## 2. Pick the right action per container

- **Compose config changed** (env, command, limits, image) → `docker compose --env-file .env --env-file models.generated.env up -d --no-deps <service>` (recreates).
- **Only a bind-mounted file changed** (`server.py`, `routes.py`, `config.py`, `llama_client.py`, `configs/*.yml`) → `docker restart <container>` after `git pull` (restart re-binds the path; compose `up` would not recreate).
- Always pass both `--env-file` flags; without `models.generated.env` the chat workers fall back to default model env.
- **Recreate services that share a GPU together in one command** (e.g. `gpu-server-2 vision-embed-2`). The GPU failure controller polls every 60 s, and if *any* slot container is not running it runs `compose up` for the whole slot with its own overlay, recreating the healthy neighbour (memory `gpu-controller-slot-recreate`).

## 3. Roll one at a time, gated

Write the script to the scratchpad and run it with `ssh 192.168.70.144 'bash -s' < script.sh | tee rollout.log` in the background, plus a Monitor on `rollout.log` grepping `OK|FAIL|DONE`. Script essentials (stop at the first failure):

```bash
cd /home/boss/local-ai && git pull -q --ff-only || { echo "FAIL pull"; exit 1; }
cd gpu-server; DC="docker compose --env-file .env --env-file models.generated.env"
wait_health() { local c=$1 max=$2 i=0 s; while [ $i -lt $max ]; do
  s=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $c)
  [ "$s" = healthy ] && return 0; sleep 5; i=$((i+5)); done; return 1; }
for n in 3 6 2 1 5 4; do                     # chat: SFW 1-3 on 8080-8082, NSFW 4-6 on 8083-8085
  base=$([ $n -le 3 ] && echo 1 || echo 4)   # both route peers must be healthy first
  for p in $base $((base+1)) $((base+2)); do [ $p = $n ] && continue
    [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:$((8079+p))/health)" = 200 ] || { echo "FAIL peer $p"; exit 1; }; done
  $DC up -d --no-deps gpu-server-$n   # or: docker restart pea-gpu-$n
  wait_health pea-gpu-$n 360 || { echo "FAIL pea-gpu-$n"; exit 1; }
  # verify the change itself: cmdline flags, docker inspect HostConfig.Memory, an endpoint
  docker exec pea-gpu-$n sh -c 'tr "\0" " " < /proc/$(pgrep -f llama-server|head -1)/cmdline'
  echo "OK pea-gpu-$n"; sleep 60                # soak before the next
done
```

Then the non-chat services the same way, one at a time; services without a healthcheck count as up once `running`. LocalAI's health endpoint is `/readyz`, not `/health`. Restart Prometheus last if its config changed (`docker restart pea-prometheus`, then wait until no target is `unknown`).

## 4. Prove a deploy is now a no-op

```bash
ssh 192.168.70.144 'cd /home/boss/local-ai/gpu-server && docker compose --env-file .env --env-file models.generated.env up -d --dry-run 2>&1 | grep -E "Recreate|Create|Remove"'
```

Empty output = done. Any `Recreate` means a container differs from what a deploy would build (usually one the controller recreated with its overlay): recreate it (and its GPU neighbour) with the deploy invocation, then re-run the dry run. Also check `python3 scripts/check-placement.py` and Prometheus `/api/v1/targets` (all `up`).

## Notes

- Long monitoring loops on the workstation can be killed by local memory pressure; for "memory over the last N hours" query PEA Prometheus (`min_over_time(node_memory_MemAvailable_bytes[2h])` on `localhost:9099`) instead.
- Record what happened (times, checks, surprises) in the OpenSpec change's tasks.md or `evidence/`, and commit.
