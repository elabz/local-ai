# gpu-rebalance Specification

## Purpose
TBD - created by archiving change rebalance-embed-image-gpus. Update Purpose after archive.
## Requirements
### Requirement: Embeddings co-located on chat GPUs

The system SHALL normally serve the configured `heartcode-embed-vision` and `heartcode-embed` backends co-located on their assigned chat GPUs, with no dedicated embedding-only GPU unless explicitly documented. Each co-located embed server SHALL share its GPU with a chat server without OOM under normal load, and only backends passing GPU-aware readiness SHALL remain eligible for routing. During an explicitly documented pre-production chat-model canary, one replica MAY be stopped to dedicate its assigned GPU to the candidate, provided at least one backend for the affected public embedding model remains GPU-ready and eligible and the stopped replica has a verified rollback.

#### Scenario: Vision and text embeds run co-located
- **WHEN** the normal rebalanced layout is deployed
- **THEN** the configured vision-embed and text-embed servers are GPU-ready on their assigned chat GPUs and chat continues to serve

#### Scenario: One embed replica is displaced by a canary
- **WHEN** an approved pre-production chat-model canary requires the replica's GPU memory
- **THEN** only that replica is removed from eligibility, at least one deployment for the public embedding model remains GPU-ready, and the canary evidence identifies the temporary capacity reduction and rollback

#### Scenario: All routed embed backends are live
- **WHEN** LiteLLM routes `heartcode-embed` or `heartcode-embed-vision`
- **THEN** every eligible backend `api_base` corresponds to a running server whose configured GPU passes identity, memory, model, and execution readiness

#### Scenario: Co-located GPU fails
- **WHEN** a shared chat and embedding GPU becomes unavailable
- **THEN** both affected backends fail readiness and are excluded from routing without changing the public model names or falling back to CPU

### Requirement: Model names and behavior unchanged

The rebalance SHALL preserve the public LiteLLM model names (`heartcode-embed`, `heartcode-embed-vision`, `heartcode-image`) and their embedding dimension (768-d shared space).

#### Scenario: Clients see no API change
- **WHEN** a client calls any of the embed/image model names after the rebalance
- **THEN** the request succeeds with the same contract (768-d vectors / generated image) as before

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

### Requirement: Image generation served from GPU 8

The system SHALL run one image-generation server on GPU 8 behind `heartcode-image`; GPU 7 is dedicated to speech. The image server SHALL keep its installed cuda12-diffusers backend and SSD-1B model on persistent volumes so that a restart does not re-download them. Adding a second image server SHALL be a manifest change that raises `min_replicas` in the same edit.

#### Scenario: Image request is served
- **WHEN** an image-generation request arrives at `heartcode-image`
- **THEN** it is served by the GPU 8 image server

#### Scenario: Restart reuses installed backend
- **WHEN** the image server restarts
- **THEN** it uses the already-installed cuda12-diffusers backend and SSD-1B model from the persistent volumes rather than re-downloading them

