## MODIFIED Requirements

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
