## ADDED Requirements

### Requirement: heartcode-embed-vision served through the prod proxy

After the cutover, the prod LiteLLM proxy (192.168.0.152) SHALL serve `heartcode-embed-vision`: an authenticated `/v1/embeddings` request with text or an image SHALL be routed to the PEA vision-embed service and return a 768-d vector.

#### Scenario: Text embedding through the proxy
- **WHEN** a client calls the prod proxy `/v1/embeddings` with `model: heartcode-embed-vision` and a text input
- **THEN** the proxy returns a 768-d embedding vector

#### Scenario: Image embedding through the proxy
- **WHEN** a client calls the prod proxy `/v1/embeddings` with `model: heartcode-embed-vision` and an image input
- **THEN** the proxy returns a 768-d embedding vector in the same space as the text vector

### Requirement: Deploy preserves a working heartcode-embed

The cutover SHALL NOT leave `heartcode-embed` pointing at a non-running backend. After deploy, `heartcode-embed` SHALL either resolve to a live backend or be intentionally removed/aliased per the chosen disposition — never a dead route.

#### Scenario: heartcode-embed remains usable (or is intentionally retired)
- **WHEN** the new config is deployed to prod
- **THEN** `heartcode-embed` resolves to a running backend (or is deliberately aliased/removed), and no client receives errors from a deployment that points at a stopped service

### Requirement: Rollback restores the prior proxy state

Reverting the LiteLLM config and restarting SHALL restore the previous routing without residual effect on other models.

#### Scenario: Config revert
- **WHEN** the previous `litellm/config.yaml` is restored and LiteLLM is restarted
- **THEN** the proxy serves the prior model set and `heartcode-embed-vision` is removed cleanly
