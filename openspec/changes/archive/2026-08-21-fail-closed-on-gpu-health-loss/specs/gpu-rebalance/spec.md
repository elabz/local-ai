## MODIFIED Requirements

### Requirement: Embeddings co-located on chat GPUs

The system SHALL serve the configured `heartcode-embed-vision` and `heartcode-embed` backends co-located on their assigned chat GPUs, with no dedicated embedding-only GPU unless explicitly documented. Each co-located embed server SHALL share its GPU with a chat server without OOM under normal load, and only backends passing GPU-aware readiness SHALL remain eligible for routing.

#### Scenario: Vision and text embeds run co-located
- **WHEN** the rebalanced layout is deployed
- **THEN** the configured vision-embed and text-embed servers are GPU-ready on their assigned chat GPUs and chat continues to serve

#### Scenario: All routed embed backends are live
- **WHEN** LiteLLM routes `heartcode-embed` or `heartcode-embed-vision`
- **THEN** every eligible backend `api_base` corresponds to a running server whose configured GPU passes identity, memory, model, and execution readiness

#### Scenario: Co-located GPU fails
- **WHEN** a shared chat and embedding GPU becomes unavailable
- **THEN** both affected backends fail readiness and are excluded from routing without changing the public model names or falling back to CPU
