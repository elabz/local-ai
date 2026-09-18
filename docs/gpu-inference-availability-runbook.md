# GPU inference availability runbook

This runbook covers the P104-100 chat wrappers only. Never capture prompts,
responses, credentials, authorization headers, or user identifiers while using
these procedures.

## Diagnosis

1. Check container health and restart counts before logs.
2. Inspect bounded metrics: `backend_state`, `backend_in_flight_requests`,
   `watchdog_probe_failures_total`, `llama_child_exits_total`, and
   `watchdog_restart_decisions_total`.
3. Filter recent logs for `watchdog_probe_failed` and `watchdog_decision`.
   `busy_probe_timeout` means the child is alive with inference active and is
   not a restart reason. `idle_probe_failure`, `stuck_request`, and
   `child_exit` are bounded failure reasons.
4. Correlate aggregate LiteLLM failed-request counts and cooldown state. Do not
   dump request bodies or authorization headers.
5. Check placement truth on PEA from the repo checkout:
   `sudo python3 gpu-server/scripts/check-placement.py`. `sudo` lets it compare
   the GPU failure controller inventory too. Without it, that comparison is
   skipped with a warning. Each `DRIFT` line names the card and one of:
   `not-running`, `wrong-card`, `name-pin-mismatch`, `unrouted` (a running
   replica LiteLLM does not route), `unrecorded` (a live GPU container that is
   not in `gpu-server/configs/gpu-topology.json`), `displaced-running`, or
   `inventory-mismatch` (the controller will act on a stale layout: copy the
   topology over `/var/lib/pea-gpu-controller/current-inventory.json` and
   restart `pea-gpu-controller`). Fix the record or the host before routing
   changes. Add `--dump-snapshot FILE` to keep the evidence.

## Canary rollout

1. Validate Python syntax, focused unit tests, generated LiteLLM config, and
   compose interpolation with non-secret placeholders.
2. **If the canary displaces a slot's main-compose services** (it needs the
   card's VRAM, so `gpu-server-N` and/or the co-located embed service are
   stopped), record it in `gpu-server/configs/gpu-topology.json` *before*
   stopping them: set `schema_version` to `2` and add a `canary` entry to that
   slot with the container name, the canary compose file, and the pinned GPU
   UUID, e.g.

   ```json
   "canary": {
     "container": "pea-sfw-model-canary-gpu6",
     "compose_file": "docker-compose.model-canaries.yml",
     "uuid": "GPU-fe0fc635-7c25-49b8-866e-3e4f9ce7efc9"
   }
   ```

   The failure controller then restores that card without `compose up`-ing the
   displaced services (which would OOM it) and alerts instead, and
   `check-placement.py` expects the canary rather than the main tenants there.
   A canary has no restart policy, so it will not come back by itself after a
   host reboot — `docker compose ps` is the source of truth, not LiteLLM routes.
   Copy the updated topology over
   `/var/lib/pea-gpu-controller/current-inventory.json` and restart
   `pea-gpu-controller`, then confirm with `scripts/check-placement.py`.
   If the canary drops a routed replica below `min_replicas`, lower it in
   `models.yaml` in the same edit with a dated reason.
3. Record the canary container restart count and start timestamp.
4. Copy only changed wrapper/runtime files, then recreate one SFW service.
5. Wait for `/live`, then model-aware `/health` and a fixed synthetic chat probe.
6. Run `scripts/sustained-chat-concurrency.py` for at least five watchdog
   intervals. Require successful completions and no restart-count increase.
7. Terminate only the canary's `llama-server` child. Require withdrawal,
   bounded container recreation, readiness recovery, and a successful fixed
   synthetic request afterward.
8. **On retirement**, remove the slot's `canary` entry, bring the displaced
   main-compose services back, re-list their ports in `models.yaml` (raising
   `min_replicas` back in the same edit), sync the controller inventory, and
   confirm with `scripts/check-placement.py`. Leaving a retired canary recorded
   blocks fault recovery for that card.

## Fleet rollout

Recreate one SFW backend at a time. Do not recreate the co-located embedding,
speech, or image services. Wait for readiness and a successful fixed synthetic
probe before proceeding to the next backend. Compare restart counts and
aggregate proxy failure rates with the recorded baseline.

## Rollback

Restore the previous versions of `server.py`, `routes.py`, `metrics.py`,
`config.py`, `llama_client.py`, compose configuration, and LiteLLM base/generated
config. Recreate one backend at a time, then reload LiteLLM. A rollback restores
the former watchdog behavior, so stop sustained load first to avoid the known
false-restart loop.

## Operator recovery

When reason `restart_suppressed` is active, first stop new traffic to that
deployment and investigate child/GPU evidence. After the configured restart
window expires, recreate only the affected chat backend and verify `/live`,
`/health`, and a fixed synthetic completion before restoring routing.
