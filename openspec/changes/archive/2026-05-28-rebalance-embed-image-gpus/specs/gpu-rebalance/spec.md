## ADDED Requirements

### Requirement: Embeddings co-located on chat GPUs

The system SHALL serve 3 `heartcode-embed-vision` backends co-located on the SFW chat GPUs and 3 `heartcode-embed` (text) backends co-located on the NSFW chat GPUs, with no dedicated embedding-only GPU. Each co-located embed server SHALL share its GPU with a chat server without OOM under normal load.

#### Scenario: Vision and text embeds run co-located
- **WHEN** the rebalanced layout is deployed
- **THEN** 3 vision-embed and 3 text-embed servers are healthy, each on a chat GPU, and chat continues to serve

#### Scenario: All routed embed backends are live
- **WHEN** LiteLLM routes `heartcode-embed` or `heartcode-embed-vision`
- **THEN** every backend `api_base` corresponds to a running server (no dead routes)

### Requirement: Image generation load-balanced across two GPUs

The system SHALL run two image-generation servers (on GPU 7 and GPU 8) behind `heartcode-image`, and LiteLLM SHALL distribute image requests across both.

#### Scenario: Image request is load-balanced
- **WHEN** image-generation requests arrive at `heartcode-image`
- **THEN** they are served by either of the two image servers, and a single server being busy does not block the other

#### Scenario: Second image server reuses installed backend
- **WHEN** the second image server starts
- **THEN** it uses the already-installed cuda12-diffusers backend + SSD-1B model from the shared volumes rather than re-downloading them

### Requirement: Model names and behavior unchanged

The rebalance SHALL preserve the public LiteLLM model names (`heartcode-embed`, `heartcode-embed-vision`, `heartcode-image`) and their embedding dimension (768-d shared space).

#### Scenario: Clients see no API change
- **WHEN** a client calls any of the embed/image model names after the rebalance
- **THEN** the request succeeds with the same contract (768-d vectors / generated image) as before
