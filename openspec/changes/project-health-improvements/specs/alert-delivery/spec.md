## ADDED Requirements

### Requirement: Firing alerts are delivered to a human
The Prometheus instance that evaluates the PEA and LiteLLM alert rules SHALL send firing alerts to an Alertmanager, and that Alertmanager SHALL route them to a Slack receiver read by the operator.

#### Scenario: A rule fires
- **WHEN** any alert rule loaded by PEA's Prometheus enters the firing state
- **THEN** a Slack notification naming the alert appears in the configured channel

#### Scenario: Alertmanager is registered
- **WHEN** `/api/v1/alertmanagers` is queried on PEA's Prometheus
- **THEN** the response lists at least one active Alertmanager

### Requirement: Delivery is verified end to end
Alert delivery SHALL be proven with a synthetic firing alert before any task that depends on alerting is marked complete, and the evidence (timestamp and alert name) SHALL be recorded in the task.

#### Scenario: Synthetic alert
- **WHEN** an operator fires a synthetic test alert
- **THEN** the Slack notification arrives and its timestamp is recorded next to the checked task

### Requirement: Single source of alert rules
Alert rules SHALL live in one file loaded by the Prometheus that delivers alerts. Rule files that no running Prometheus loads SHALL be removed, or marked as not deployed.

#### Scenario: No inert rule copies
- **WHEN** the repo is searched for Prometheus rule files
- **THEN** each one is either loaded by the delivering Prometheus or explicitly labelled as not deployed
