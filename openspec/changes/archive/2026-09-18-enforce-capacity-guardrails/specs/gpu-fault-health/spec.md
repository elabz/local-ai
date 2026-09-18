## ADDED Requirements

### Requirement: Recovery respects recorded canary tenancy

When recovering a GPU slot, the failure controller SHALL consult the slot's recorded canary tenancy and SHALL NOT start main-compose services that a recorded canary has displaced.

#### Scenario: Recovering GPU 6 while the SFW canary holds it
- **WHEN** GPU 6 faults and recovers and its topology entry records `pea-sfw-model-canary-gpu6`
- **THEN** the controller leaves `gpu-server-6` and `dino-embed-2` stopped and alerts the operator
