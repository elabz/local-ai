# chat-concurrency Specification

## Purpose

Increase chat throughput on fixed hardware by qualified multi-slot serving, preserve prompt-cache benefits through session affinity, and let interactive traffic take precedence over batch traffic.

## ADDED Requirements

### Requirement: Multi-slot serving is qualified by measurement

A chat replica SHALL run more than one llama.cpp slot only after a load test at the proposed slot count and per-slot context shows: aggregate throughput higher than single-slot, p95 time-to-first-token within the published bound, per-stream decode rate above the model's floor (SFW 12 tok/s, NSFW 12 tok/s), and no VRAM growth into a card's fault region. The qualified configuration and evidence SHALL be recorded before it becomes the fleet default.

#### Scenario: Two slots pass
- **WHEN** `--parallel 2` at 8K per slot yields higher aggregate throughput with p95 TTFT and decode floors met over the mixed-load test
- **THEN** it is recorded as qualified and rolled out via the compose env

#### Scenario: Four slots fail the TTFT bound
- **WHEN** `--parallel 4` breaches the TTFT bound under prompt-heavy load
- **THEN** it is recorded as rejected and not deployed

### Requirement: Session affinity preserves prompt cache

Requests carrying a session identifier SHALL be routed to the replica (and slot) that last served that session while it is healthy; requests without one SHALL be balanced. Cache-hit rate per replica SHALL be observable.

#### Scenario: Follow-up turn
- **WHEN** a second turn for the same session arrives within the cache lifetime
- **THEN** it is served by the same replica and llama.cpp reports reused prompt tokens

### Requirement: Interactive traffic has priority over batch

Keys SHALL carry a priority class. When all slots of a model group are busy, queued interactive requests SHALL be admitted before queued batch requests.

#### Scenario: Saturated pool
- **WHEN** the pool is saturated with batch requests and an interactive request arrives
- **THEN** the interactive request is admitted at the next free slot ahead of waiting batch requests

### Requirement: Capacity figures are published

For each chat model group the repository SHALL publish slot count, measured aggregate throughput, single-stream decode rate, and a queue-wait table by concurrency, updated whenever slots or models change.

#### Scenario: Consumer sizes concurrency
- **WHEN** a consumer reads the capacity table for `heartcode-chat-nsfw`
- **THEN** it finds the slot count and expected wait at 8, 16 and 32 concurrent requests
