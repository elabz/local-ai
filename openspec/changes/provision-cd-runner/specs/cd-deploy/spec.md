## ADDED Requirements

### Requirement: Deploys run from a reviewed, manually dispatched workflow on a LAN-connected runner

Production deploys of LiteLLM and the GPU server SHALL run from the deploy workflow on a self-hosted runner that can reach both hosts, SHALL require approval through the `production` Environment, and SHALL record the deployed commit. GitHub-hosted runners SHALL never deploy.

#### Scenario: Dispatch with approval
- **WHEN** an operator dispatches the workflow for a target and the Environment reviewer approves
- **THEN** the runner checks out the requested commit on the target host, applies it, and the job succeeds only when the host's health endpoint reports ready

#### Scenario: Runner not registered
- **WHEN** no runner with the required labels is online
- **THEN** the job does not start, is marked failed after the queue timeout, and no host is changed

### Requirement: GPU server rollout follows the rolling-rollout rules

The GPU server deploy SHALL restart chat replicas one at a time in an order that never takes two replicas of one model group down together, SHALL skip any replica the manifest marks as quarantined or the controller inventory marks as recovering, SHALL wait for each replica's health endpoint before continuing, SHALL stop at the first failure leaving remaining replicas untouched, and SHALL finish by proving a further plain deploy would change nothing.

#### Scenario: Healthy rollout
- **WHEN** every restarted replica reports healthy within the bounded wait
- **THEN** all replicas are restarted in the derived order and the final dry-run reports no change

#### Scenario: Replica fails health after restart
- **WHEN** a restarted replica does not report healthy within the bounded wait
- **THEN** the job fails, no further replica is restarted, and the failing replica is named in the job output

#### Scenario: Quarantined card
- **WHEN** the manifest excludes a GPU from a model group
- **THEN** the rollout does not restart or health-check a replica on that GPU

### Requirement: Runner availability is verified on a schedule

A scheduled run SHALL exercise the runner at least weekly without changing any host, and SHALL fail visibly when the runner is offline.

#### Scenario: Weekly probe with runner online
- **WHEN** the scheduled probe runs and the runner is online
- **THEN** it performs only the health check and succeeds

#### Scenario: Weekly probe with runner offline
- **WHEN** the scheduled probe runs and no runner is online
- **THEN** the run fails and the repository owner is notified by GitHub's failed-run notification
