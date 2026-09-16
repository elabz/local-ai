## ADDED Requirements

### Requirement: NSFW chat has at least two routed replicas

The `heartcode-chat-nsfw` model group SHALL have at least two deployments that are both running and listed in the rendered LiteLLM config. GPU 5 SHALL host an NSFW chat replica (`gpu-server-5`, port 8084) alongside `embedding-server-5`, at a configuration whose llama-server process allocation stays at least 1 GiB below the card's documented ~7.6 GiB corruption region.

#### Scenario: Two NSFW requests arrive together
- **WHEN** two `heartcode-chat-nsfw` requests arrive within one generation time of each other
- **THEN** LiteLLM routes them to different deployments and both complete without a 503 or a cooldown

#### Scenario: Restored replica proves coherent generation
- **WHEN** `gpu-server-5` is brought up on GPU 5
- **THEN** it is added to routing only after a repeated-generation check (at least 20 sequential completions) returns non-empty, coherent output with no empty or garbled generations
- **AND** its steady-state process allocation is recorded and is below 6.6 GiB

### Requirement: Recorded GPU placement matches running placement

`configs/gpu-topology.json`, compose service comments, and `models.yaml` deployment lists SHALL describe the containers actually pinned to each GPU UUID. A canary container's name SHALL identify the card it is pinned to.

#### Scenario: Canary pinned to a different card than its default
- **WHEN** a canary is pinned via `SFW_CANARY_GPU_UUID` to GPU 6
- **THEN** its container name ends in `gpu6` and the topology and comments no longer describe GPU 5 as the canary card

#### Scenario: Running but unrouted replica
- **WHEN** a healthy embed or chat container is running on a card
- **THEN** it is listed in `models.yaml` deployments, or its exclusion is documented with a reason in the manifest
