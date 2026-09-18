## ADDED Requirements

### Requirement: Every llama-server exposes llama.cpp metrics
Every `llama-server` process on PEA, whether chat or embedding, fleet or canary, SHALL run with `--metrics`, so llama.cpp's own `llamacpp:*` series are available.

#### Scenario: Launch flags
- **WHEN** any `llama-server` process on PEA is inspected
- **THEN** its command line contains `--metrics`

### Requirement: Chat workers relay llama.cpp metrics without bypassing admission
Chat workers SHALL keep `llama-server` bound to loopback and SHALL expose its metrics read-only at `/llama/metrics` on the wrapper port. The relay SHALL NOT take an admission slot or require GPU readiness, and SHALL answer 503 when llama-server is unreachable.

#### Scenario: Scraping a busy worker
- **WHEN** Prometheus requests `/llama/metrics` while the worker's only slot is generating
- **THEN** it receives llama.cpp's current exposition without waiting in the admission queue

#### Scenario: llama-server down
- **WHEN** the wrapper cannot reach llama-server
- **THEN** `/llama/metrics` returns 503 and the scrape records the target as down

### Requirement: Prometheus scrapes exactly the running inference servers
PEA's Prometheus SHALL scrape every inference server (chat, text-embed, vision-embed, DINOv2 and image), and SHALL NOT keep targets for containers that are no longer deployed. With the stack healthy, every active target SHALL be up.

#### Scenario: Healthy stack
- **WHEN** all PEA services are running
- **THEN** `/api/v1/targets` reports every active target as `up`

#### Scenario: A server is removed
- **WHEN** a container is removed from the deployment
- **THEN** its scrape target is removed in the same change
