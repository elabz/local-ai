# Back up the LiteLLM key store

## Why

The LiteLLM PostgreSQL database on Prod holds every issued virtual key, its model grants, its `max_parallel_requests` cap and the spend logs. It lives in one Docker volume (`local-ai-litellm-postgres-data`) on one host with no dump, no copy off-host and no tested restore. Losing that volume (disk failure, a mistaken `docker compose down -v`, a bad Postgres major bump) would revoke every consumer's access at once and lose the per-key caps that `docs/proxy-client-contract.md` makes mandatory; recovery would mean reissuing every key by hand and redistributing it to each consumer.

## What Changes

- **Nightly logical backup.** A `pg_dump` of the `litellm` database runs on Prod on a schedule, written locally with a retention window, then copied to a second host (PEA or the NAS the load tests already use) so a Prod disk loss does not take the backups with it.
- **Restore procedure, tested.** A documented restore into a scratch Postgres container that verifies key count and a sample key's caps against the live database, run once at rollout and again before any Postgres image bump.
- **Backup freshness is monitored.** The backup job exports its last-success timestamp and size (textfile collector into the existing Prometheus on PEA, via the same path the LiteLLM capacity rules use), with an alert when the newest backup is older than 48 h or empty.
- **Secrets stay out of the repo.** The dump is taken with the existing `LITELLM_DB_PASSWORD` from the gitignored `litellm/.env`; the off-host copy uses an SSH key that already exists for the deploy runner or a dedicated read-only one.

## Capabilities

### New Capabilities

- `litellm-key-store-backup`: scheduled backup, off-host copy, tested restore and freshness alerting for the LiteLLM PostgreSQL database.

### Modified Capabilities

_None._

## Impact

- `litellm/scripts/backup-postgres.sh` (new), `litellm/scripts/restore-postgres.sh` (new), a systemd timer or cron entry on Prod, `gpu-server/configs/alert_rules.yml` (freshness rule) and its promtool test, `docs/pea-server-setup.md` or a new `docs/litellm-backup-runbook.md`, `CLAUDE.md` Common Commands.
- Live hosts: Prod gains a scheduled job and a backup directory; the second host gains a receive directory. No change to the running LiteLLM or Postgres containers.
- Secret operations (reading `.env`, installing the cron entry, SSH key placement) need the user at the keyboard (see the `Secret ops on PEA need the user` memory); the change hands over ready-made steps.
