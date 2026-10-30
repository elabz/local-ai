## Context

`litellm/docker-compose.yml` runs `postgres:16-alpine` with the data in a named volume and no backup service. Prod has no monitoring; Prometheus and Alertmanager run on PEA and already scrape LiteLLM's metrics and evaluate the capacity rules, so backup freshness can reach Slack through the existing path. The deploy runner (when registered, see `provision-cd-runner`) will live on Prod and can already SSH to PEA, so Prod → PEA is the natural off-host direction.

Database size is small (keys plus spend logs; streamed requests write no spend rows), so a nightly full logical dump is cheap.

## Goals / Non-Goals

**Goals:**
- A restorable copy of the key store that is at most one day old and is not on Prod's disk alone.
- A restore that has been exercised, not just written.
- Alerting when backups stop.

**Non-Goals:**
- Point-in-time recovery or WAL shipping; one day of spend-log loss is acceptable, key loss is not.
- Backing up Langfuse's databases (its fate is decided by `retire-unused-stacks-and-dirs`).
- Encrypting the dump at rest beyond filesystem permissions; the second host is on the same private LAN. Revisit if backups ever leave the LAN.

## Decisions

**D1. `pg_dump` via `docker exec` in the running Postgres container.** No new container, no extra Postgres client on the host, same major version as the server. Custom format (`-Fc`) so a restore can be selective and is faster. Alternative: a sidecar backup container (e.g. `prodrigestivill/postgres-backup-local`). Rejected: another floating image to pin and another 100 MB on a host that runs fine with a 20-line script.

**D2. systemd timer on Prod, daily at 03:30 local, 14 local copies.** systemd gives `journalctl` history and `OnFailure=` hooks for free; cron would need its own logging. Retention by count keeps the directory bounded regardless of dump size.

**D3. Off-host copy by `rsync` over SSH to PEA, into `/home/boss/backups/litellm/`.** PEA is up whenever inference is up, it is a different disk and host, and the SSH path already exists in the opposite direction for deploys. 30 copies retained there. The NAS used by load tests is an alternative if PEA's root disk is tight; decide in task 1.2 by checking free space.

**D4. Freshness through node-exporter's textfile collector.** The backup script writes `litellm_backup_last_success_timestamp_seconds` and `litellm_backup_bytes` to a `.prom` file. Prod has no node-exporter today; rather than add one, the rsync step writes the file on PEA, where node-exporter already runs with a textfile directory (verify; add the `--collector.textfile.directory` flag if missing). A rule `LiteLLMBackupStale` fires when `time() - timestamp > 48*3600` or bytes is 0. Alternative: push to Alertmanager directly. Rejected: a stale-backup condition is exactly what a metric absent-or-old check catches, and it also covers the case where the script never ran.

**D5. Restore is a script that targets a throwaway container.** `restore-postgres.sh <dump>` starts `postgres:16-alpine` (same pinned digest) on a random port, restores, prints key count and one key's grants and caps, and exits. Restoring into production is the same script with an explicit `--into-production` flag that first stops LiteLLM. The scratch path is what the rollout and every future Postgres bump runs.

## Risks / Trade-offs

- [Dump contains hashed keys and the master key's hash] → directory mode 0700, owned by the deploy user, on both hosts; dumps never enter the repo (gitignore `backups/`).
- [PEA disk fills with dumps] → count-based retention on both sides; `litellm_backup_bytes` makes growth visible.
- [Postgres image bump changes dump format compatibility] → the restore test is a required step for that bump (recorded on the pin line by `pin-floating-container-images`).
- [Timer silently disabled after a Prod rebuild] → the freshness alert catches it within 48 h.

## Migration Plan

1. Land scripts, unit test (script parses args and builds the expected `pg_dump` command), alert rule and promtool test; CI green.
2. User installs the timer on Prod and the SSH key from the ready-made steps; first run by hand.
3. Run the scratch restore against that first dump; record key count parity in `tasks.md`.
4. Confirm the metric on PEA and that the rule is loaded; fire it once by touching the timestamp back to prove delivery.

Rollback: disable the timer; nothing else changed.

## Open Questions

- Does PEA's node-exporter run with a textfile directory today? Task 1.3 checks.
- Prod → PEA or Prod → NAS: decided by free space and whether the NAS is reachable from Prod without a new credential.
