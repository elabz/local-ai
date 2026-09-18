# chat-model-canary-evaluation Specification

## Purpose
TBD - created by archiving change evaluate-modern-chat-model-canaries. Update Purpose after archive.
## Requirements
### Requirement: Canary isolation and control preservation
The system SHALL run candidate chat models on direct non-public canary ports without changing production model aliases, SHALL retain GPU 4's current NSFW model as the simultaneous NSFW control, and SHALL keep at least one healthy deployment of each temporarily reduced embedding model.

#### Scenario: SFW canary is launched
- **WHEN** the Gemma canary is evaluated on GPU 5
- **THEN** the Qwen canary and GPU 5 text-embedding replica are stopped, one text-embedding replica remains healthy, and no public SFW alias routes to Gemma

#### Scenario: NSFW canary is launched
- **WHEN** the NSFW challenger is evaluated on GPU 6
- **THEN** the GPU 6 Lumimaid and DINO replica are stopped, GPU 4 remains the Lumimaid control, one DINO replica remains healthy, and no public NSFW alias routes to the challenger

### Requirement: Reproducible candidate identity
Every evaluation SHALL record the model repository, revision, filename, quantization, exact artifact digest, license and provenance assessment, llama.cpp commit/build, launch parameters, physical GPU identity, and benchmark version.

#### Scenario: Results are recorded
- **WHEN** a candidate benchmark produces evidence
- **THEN** another operator can identify and relaunch the exact model and runtime configuration without relying on mutable tags

### Requirement: Progressive context-window qualification
The SFW evaluation SHALL test 4K, 8K, and 16K contexts and SHALL test 24K and 32K when the preceding size remains safe. It SHALL distinguish advertised context from the largest Pea-qualified usable context.

#### Scenario: Candidate reaches the hard gate
- **WHEN** an SFW candidate completes the 16K test
- **THEN** evidence includes load status, VRAM, host RAM and swap, restart count, prompt throughput, time to first token, decode distribution, output validity, and positional retrieval at that context

#### Scenario: Context size becomes unsafe
- **WHEN** a candidate fails to load, OOMs, restarts, falls back from GPU, or causes sustained swap thrashing at a context size
- **THEN** larger sizes are not attempted and the preceding safe size is recorded without claiming the failed size as usable

### Requirement: Throughput gates use tail performance
An SFW candidate SHALL achieve p10 decode throughput of at least 10 tokens per second at 16K context. An NSFW candidate SHALL achieve p10 decode throughput of at least 12 tokens per second at its proposed production context. Mean throughput alone SHALL NOT qualify a candidate.

#### Scenario: Candidate falls below the floor
- **WHEN** measured p10 decode throughput is below the applicable floor
- **THEN** that model and configuration are rejected regardless of mean throughput or qualitative preference

### Requirement: Workload-relevant SFW quality gate
SFW candidates SHALL be evaluated against the frozen `site-2017` tool-demand benchmark for valid JSON, actionable precision, high-risk recall, identifier leakage, invented evidence, and latency, using the benchmark's existing approval gates.

#### Scenario: Candidate is eligible for selection
- **WHEN** an SFW candidate passes the context and throughput gates
- **THEN** it is eligible only if the frozen benchmark also passes all schema, quality, privacy, and safety gates

#### Scenario: Failed-call mop-up begins
- **WHEN** a winning SFW candidate has passed every selection gate
- **THEN** outstanding failed extraction calls may be retried separately and their results are not retroactively included in the blind selection score

#### Scenario: Native schema grammar is incompatible
- **WHEN** provider-side `json_schema` fails because llama.cpp rejects a candidate control token rather than because the candidate violates the semantic output contract
- **THEN** the benchmark may omit provider grammar, include the unchanged schema contract in the prompt, perform syntax-only object extraction, validate the unchanged schema, and apply the same 98% valid-output and safety gates

#### Scenario: Compatibility cleanup encounters invalid semantics
- **WHEN** prompt-constrained output is missing fields, uses invalid enum values, invents evidence, leaks identifiers, or otherwise violates the semantic schema
- **THEN** the output remains failed and cleanup SHALL NOT fabricate, coerce, or infer replacement values

### Requirement: NSFW quality and safety evaluation
Each admitted NSFW challenger SHALL be compared with the retained Lumimaid control using a fixed private prompt suite covering instruction adherence, character consistency, repetition, prose quality, refusal behavior for allowed consenting-adult content, and rejection of prohibited content. Thinking-capable candidates SHALL be evaluated with native reasoning disabled so latency and output behavior represent the intended direct-response production mode.

#### Scenario: NSFW candidate is reviewed
- **WHEN** a challenger completes its fixed evaluation suite
- **THEN** the report contains aggregate scores and safe excerpts or hashes only, without publishing private prompts or explicit generated content

#### Scenario: Direct-response mode is enforced
- **WHEN** a Gemma 4 NSFW/RP candidate is launched
- **THEN** native reasoning is disabled, no reasoning content is returned, and the measured time to first answer includes no hidden thinking pass

### Requirement: Runtime compatibility probes
Each candidate SHALL pass model-load, health, text generation, chat-template, structured-output, and relevant multi-turn API probes on the pinned Pascal-compatible llama.cpp build before quality evaluation. Structured output SHALL test native `json_schema` first and MAY use prompt-constrained JSON with strict post-generation validation when the native failure is an identified runtime grammar/control-token incompatibility.

#### Scenario: Ministral tool-call template is incompatible
- **WHEN** llama.cpp emits a tool-call identifier that Ministral's own Jinja template rejects on the following turn
- **THEN** the incompatibility is recorded and the configuration is not approved for workflows requiring native multi-turn tool calls

### Requirement: Safe rollback
The canary workflow SHALL provide and verify a rollback that removes only the candidate container and restores the exact displaced services without modifying public routing.

#### Scenario: Canary becomes unhealthy
- **WHEN** a canary OOMs, restarts, fails GPU-aware health, or threatens surviving services
- **THEN** the canary is stopped and the displaced embedding/chat services are restored and verified healthy

