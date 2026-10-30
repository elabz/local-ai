## ADDED Requirements

### Requirement: Readiness gate configuration is identical across every start path

Every Pea chat and embedding backend SHALL run with the same GPU health gate setting and the same container image whether it was started by a plain deploy (`docker compose up`, the deploy workflow, the rolling rollout) or recreated by the GPU failure controller. No compose overlay SHALL be required to obtain the gated configuration.

#### Scenario: Controller restores a slot
- **WHEN** the failure controller recreates a slot's chat and embed containers after a card is restored
- **THEN** `docker inspect` on those containers shows the same `GPU_HEALTH_ENABLED` value and the same image reference as containers started by a plain deploy of the same commit

#### Scenario: Plain deploy after a controller recovery
- **WHEN** a plain deploy runs against a fleet in which some slots were recreated by the controller
- **THEN** `docker compose up -d --dry-run` reports no container to recreate

### Requirement: Start-path drift is checked before deploy

A read-only check SHALL compare the effective compose configuration of the plain deploy with the configuration the failure controller would apply, for every chat and embed service, and SHALL fail on any difference in the GPU health gate setting or the image reference. The check SHALL run in CI and in the deploy workflow's preflight.

#### Scenario: Overlay reintroduces a different image
- **WHEN** a compose file used only by the controller sets a different image or gate value for a chat or embed service
- **THEN** the check exits non-zero and names the service and the differing field

#### Scenario: Configurations match
- **WHEN** both start paths render the same gate setting and image for every chat and embed service
- **THEN** the check exits zero
