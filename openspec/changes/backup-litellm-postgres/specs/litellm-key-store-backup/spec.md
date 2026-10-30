## ADDED Requirements

### Requirement: The key store is backed up daily and copied off-host

A logical backup of the LiteLLM PostgreSQL database SHALL be taken at least once per day, retained for a bounded number of copies on Prod, and copied to a second host on the private LAN with its own bounded retention. Backup files SHALL be readable only by the deploy user and SHALL never be committed to the repository.

#### Scenario: Scheduled run succeeds
- **WHEN** the daily backup job runs
- **THEN** a new dump exists on Prod and on the second host, the oldest copies beyond the retention count are removed, and the job exits zero

#### Scenario: Off-host copy fails
- **WHEN** the copy to the second host fails
- **THEN** the local dump is kept, the job exits non-zero, and the freshness metric is not updated

### Requirement: Restore is documented and exercised

A restore procedure SHALL exist that loads a backup into a scratch database, reports the number of virtual keys and a sample key's model grants and concurrency cap, and SHALL be run at rollout and before any change to the Postgres image.

#### Scenario: Scratch restore
- **WHEN** the restore script is run against the latest dump without the production flag
- **THEN** it restores into a throwaway container, prints the key count and sample key, and leaves the production database untouched

#### Scenario: Production restore
- **WHEN** the restore script is run with the production flag
- **THEN** it stops the proxy first, restores into the production database, restarts the proxy, and the health endpoint reports ready

### Requirement: Backup freshness is alerted

The backup job SHALL export its last success time and dump size to the existing Prometheus, and an alert SHALL fire to Slack when the newest successful backup is older than 48 hours or empty.

#### Scenario: Backups stop
- **WHEN** no successful backup has completed for 48 hours
- **THEN** a stale-backup alert fires through the existing Alertmanager Slack route

#### Scenario: Metric absent
- **WHEN** the freshness metric has never been written
- **THEN** the same alert fires
