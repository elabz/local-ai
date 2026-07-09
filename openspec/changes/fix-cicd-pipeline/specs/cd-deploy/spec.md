## ADDED Requirements

### Requirement: Deploy workflow runs on a LAN-resident self-hosted runner
The deploy workflow SHALL run on a self-hosted runner labeled `homelab` that resides on the private LAN, so it can reach Prod (`192.168.0.152`) and PEA (`192.168.0.144`). Deploy jobs MUST NOT run on GitHub-hosted runners.

#### Scenario: Deploy targets the self-hosted runner
- **WHEN** the deploy workflow is invoked
- **THEN** its jobs run on `runs-on: [self-hosted, homelab]`
- **AND** they can reach `192.168.0.x` hosts that GitHub-hosted runners cannot

### Requirement: Deploys are explicitly triggered and gated
The deploy workflow SHALL be triggered by `workflow_dispatch` with a target input (`litellm`, `gpu-server`, or `both`). Self-hosted deploy jobs MUST NOT run for pull requests from forks, and production deploys SHALL require approval via a GitHub `production` Environment.

#### Scenario: Manual dispatch selects a target
- **WHEN** a maintainer runs the deploy workflow via `workflow_dispatch` and selects `litellm`
- **THEN** only the LiteLLM deploy job runs

#### Scenario: Fork PR cannot trigger a deploy
- **WHEN** a pull request from a fork is opened
- **THEN** no deploy job runs on the self-hosted runner

#### Scenario: Production deploy waits for approval
- **WHEN** a deploy job targets the `production` Environment
- **THEN** it pauses until a required reviewer approves

### Requirement: LiteLLM config deploy is validated then health-checked
Deploying LiteLLM SHALL first pass the `litellm-validate` check, then update the config on Prod and `docker compose up -d litellm`, then verify the service is healthy before reporting success.

#### Scenario: Valid config deploys and comes back healthy
- **WHEN** the LiteLLM deploy job runs with a valid `config.yaml`
- **THEN** Prod pulls the new config, restarts the `litellm` service, and the post-deploy health check passes
- **AND** the job reports success

#### Scenario: Invalid config is not deployed
- **WHEN** the LiteLLM deploy job runs but config validation fails
- **THEN** the running LiteLLM service is left untouched and the job fails

#### Scenario: Service unhealthy after restart fails the job
- **WHEN** LiteLLM does not return healthy after restart within the timeout
- **THEN** the deploy job fails so the maintainer is alerted

### Requirement: GPU server deploy rebuilds on-host and restarts with health gating
Deploying the GPU server SHALL rebuild the `local-ai-llama:latest` image natively on PEA and restart chat servers one at a time, verifying `/health` between each, matching the build-on-host model.

#### Scenario: One-at-a-time restart with health checks
- **WHEN** the GPU server deploy job runs
- **THEN** it rebuilds the image on PEA and restarts each chat server sequentially
- **AND** it verifies the server's `/health` endpoint before proceeding to the next
- **AND** a failed health check stops the rollout and fails the job

### Requirement: Manual deploy remains a documented fallback
The repo SHALL document the manual `docker compose` deploy commands for Prod and PEA so deploys remain possible when the self-hosted runner is unavailable.

#### Scenario: Runner down, manual fallback available
- **WHEN** the self-hosted runner is offline
- **THEN** a maintainer can follow documented commands to deploy LiteLLM on Prod and GPU servers on PEA manually
