## 1. Facts (read-only)

- [ ] 1.1 Record the database size and key count on Prod (`docker exec ... psql -c`) in design.md
- [ ] 1.2 Check free space on PEA `/home` and whether the load-test NAS is reachable from Prod; pick the second host
- [ ] 1.3 Check whether `pea-node-exporter` runs with a textfile directory; note the compose change needed if not

## 2. Scripts

- [ ] 2.1 `litellm/scripts/backup-postgres.sh`: `docker exec` `pg_dump -Fc`, dated filename, 0700 dir, count-based retention, rsync to the second host, write the `.prom` freshness file, non-zero on any failure
- [ ] 2.2 `litellm/scripts/restore-postgres.sh`: scratch mode into a throwaway pinned Postgres container printing key count and sample key; `--into-production` mode that stops and restarts LiteLLM
- [ ] 2.3 Unit test (shell-free, e.g. `--dry-run` printing the commands) for both scripts; add `backups/` to `.gitignore`
- [ ] 2.4 systemd `litellm-backup.service` + `.timer` files under `litellm/scripts/`, daily 03:30, `OnFailure` logging

## 3. Monitoring

- [ ] 3.1 If needed, add `--collector.textfile.directory` to `pea-node-exporter` in `gpu-server/docker-compose.yml` (memory budget unchanged)
- [ ] 3.2 Add `LiteLLMBackupStale` to `gpu-server/configs/alert_rules.yml` (age > 48h, bytes == 0, or absent) with a promtool test file

## 4. Rollout (user at the keyboard for secret and cron steps)

- [ ] 4.1 Hand over the install steps: copy scripts, create the SSH key on Prod, authorize it on the second host, `systemctl enable --now litellm-backup.timer`
- [ ] 4.2 First run by hand; confirm the dump on both hosts and the metric in Prometheus
- [ ] 4.3 Scratch restore of that dump; record key count parity with 1.1 here with the date
- [ ] 4.4 Prove alert delivery once (age the timestamp) and record the Slack arrival time

## 5. Docs

- [ ] 5.1 `docs/litellm-backup-runbook.md`: schedule, locations, restore both modes, what to do when the alert fires
- [ ] 5.2 `CLAUDE.md`: backup and restore commands under LiteLLM Proxy; note the restore test as a precondition for Postgres bumps
