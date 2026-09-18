# capacity-manifest Specification

## Purpose

Encode required serving capacity and true GPU placement in the repository so that losing replicas or drifting placement is caught by CI and monitoring rather than by a downstream consumer.

## ADDED Requirements

### Requirement: Model groups declare minimum replicas

Each chat and embedding model group in `models.yaml` SHALL declare `min_replicas`. `render-config.py --check` SHALL fail with a message naming the group when the number of routed deployments is below `min_replicas`. Lowering `min_replicas` SHALL require a manifest comment with a date and reason.

#### Scenario: Canary removes a replica
- **WHEN** a deployment line is removed and the routed count falls below `min_replicas`
- **THEN** `render-config.py --check` exits non-zero and CI fails until `min_replicas` is lowered with a dated reason

### Requirement: Placement drift is detectable

A `check-placement` script SHALL compare, on the GPU host, each slot's recorded tenants (`gpu-topology.json` plus recorded canary) with the live process→GPU-UUID mapping and container names, and SHALL report: a tenant on a different card, a recorded tenant not running, a running chat/embed container not routed in `models.yaml`, and a container name whose card suffix does not match its pin. The deploy workflow SHALL run it after a GPU-host deploy and fail on drift.

#### Scenario: Canary on the wrong card
- **WHEN** a container named `*-gpu5` is pinned to GPU 6's UUID
- **THEN** the check reports a name/pin mismatch for that container

#### Scenario: Healthy replica not routed
- **WHEN** an embed container is running and healthy on a port absent from the rendered LiteLLM config
- **THEN** the check reports an unrouted replica

### Requirement: Canary tenancy is recorded and respected

`gpu-topology.json` SHALL allow an optional `canary` entry per slot (container name, compose file, pinned UUID). The GPU failure controller SHALL NOT start a slot's main-compose services while a canary is recorded for that slot.

#### Scenario: Slot with a recorded canary faults
- **WHEN** the controller recovers a slot whose topology entry records a canary
- **THEN** it restores the GPU and alerts, but does not `compose up` the displaced main-compose services
