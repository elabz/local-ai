# vision-embed-availability Specification

## Purpose
TBD - created by archiving change finalize-vision-embed-rollout. Update Purpose after archive.
## Requirements
### Requirement: heartcode-embed-vision served through the prod proxy

The prod LiteLLM proxy (192.168.70.152) SHALL serve `heartcode-embed-vision`: an authenticated `/v1/embeddings` request with text or an image SHALL be routed to a PEA vision-embed replica and return a 768-d vector.

#### Scenario: Text embedding through the proxy
- **WHEN** a client calls the prod proxy `/v1/embeddings` with `model: heartcode-embed-vision` and a text input
- **THEN** the proxy returns a 768-d embedding vector

#### Scenario: Image embedding through the proxy
- **WHEN** a client calls the prod proxy `/v1/embeddings` with `model: heartcode-embed-vision` and an image input
- **THEN** the proxy returns a 768-d embedding vector in the same space as the text vector

### Requirement: heartcode-embed resolves to a live backend

`heartcode-embed` SHALL route only to running text-embed backends. A config change that stops or moves a text-embed backend SHALL update or remove the matching deployment in the same change, never leaving a route to a stopped service.

#### Scenario: No dead text-embed route
- **WHEN** the deployed LiteLLM config is compared with the running PEA containers
- **THEN** every `heartcode-embed` deployment points at a text-embed server that answers `/health` with 200

