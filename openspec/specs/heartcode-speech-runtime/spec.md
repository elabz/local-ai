# heartcode-speech-runtime Specification

## Purpose

Provide GPU-backed STT/TTS serving, authenticated streaming, safe observability, and verifiable speech routing for HeartCode.
## Requirements
### Requirement: Dedicated speech services

The system SHALL serve HeartCode STT and TTS from independently health-checked GPU containers pinned to the configured GPU UUID, with an authenticated direct streaming path for TTS.

#### Scenario: Speech services start
- **WHEN** the speech compose profile is deployed
- **THEN** STT and TTS load their configured models on the target GPU UUID and their model-aware health checks pass

#### Scenario: Direct streaming is unauthorized
- **WHEN** a client calls the direct TTS gateway without the configured credential
- **THEN** the gateway rejects the request without forwarding it or exposing credential values

### Requirement: GPU identity is unambiguous

The system SHALL identify speech placement by GPU UUID and SHALL report zero-based physical index and one-based display slot as separately named metadata.

#### Scenario: Inventory is displayed
- **WHEN** operators inspect speech placement
- **THEN** they see UUID `GPU-f417c539-26db-94e9-4c8f-c5a775291988`, zero-based physical index 6, and one-based display slot 7 without a bare ambiguous GPU-number label

#### Scenario: Inventory changes
- **WHEN** the UUID resolves to a different physical index after a hardware or driver change
- **THEN** placement remains pinned by UUID and monitoring raises an inventory mismatch warning

### Requirement: Speech routing is observable

The system SHALL expose secret-free request telemetry for STT and TTS including correlation fields in structured logs and low-cardinality counters for route, model, outcome, fallback, latency, and workload units.

#### Scenario: Correlated request succeeds
- **WHEN** HeartCode sends an allowlisted speech request ID with call and turn context
- **THEN** operators can correlate gateway and container handling without recording audio, transcript content, or authorization credentials

#### Scenario: LiteLLM audio correlation is forwarded
- **WHEN** HeartCode sends STT or TTS through the LiteLLM model groups with request, call, and turn correlation headers
- **THEN** a scoped LiteLLM audio adapter shim forwards only those three validated headers to the PEA data plane and does not forward authorization, cookies, or arbitrary client headers

#### Scenario: Metrics are collected
- **WHEN** speech requests are processed
- **THEN** Prometheus records request counts, failures, latency, STT seconds, TTS characters/bytes, and health without using request/call/turn IDs as labels

### Requirement: LiteLLM policy handling is preserved

The system SHALL retain LiteLLM as the normal authentication, virtual-key accounting, rate-limit, model-routing, retry, cooldown, and fallback plane, and SHALL keep the PEA metering proxy private to the speech data path.

#### Scenario: Normal speech request
- **WHEN** HeartCode performs normal STT or TTS through LiteLLM
- **THEN** LiteLLM applies its existing key, accounting, rate-limit, and routing policies before forwarding the request through the PEA edge and metering proxy

#### Scenario: Direct streaming TTS
- **WHEN** the HeartCode backend uses the low-latency direct TTS route
- **THEN** the PEA edge requires a dedicated service credential, permits only the configured speech endpoint, bounds resource use, strips authorization upstream, and does not expose Kokoro or the metering service directly

#### Scenario: Browser attempts direct access
- **WHEN** an untrusted browser or unauthenticated client calls the direct route
- **THEN** the edge rejects it without forwarding the request or revealing service credentials

### Requirement: GPU execution is verifiable

The system SHALL provide a controlled probe that associates a speech request with process placement, model memory residency, and observed GPU execution on the expected UUID.

#### Scenario: Controlled probe runs
- **WHEN** an operator runs the end-to-end speech probe
- **THEN** the result records request receipt, route/accounting evidence, expected process GPU UUID, non-zero model memory, and a utilization or execution-counter change

### Requirement: Speech failures alert safely

The system SHALL alert on sustained speech unavailability, route-correlation failure, UUID/index mismatch, CPU fallback, error rate, and latency without including user content or secrets.

#### Scenario: TTS becomes unavailable
- **WHEN** the TTS model-aware health probe fails for the configured duration
- **THEN** a service-specific alert identifies the failing route and model

#### Scenario: CPU fallback occurs
- **WHEN** a production speech process handles inference without expected GPU placement
- **THEN** monitoring raises an unexpected CPU fallback alert

### Requirement: Kokoro serves built-in and approved custom voices

The HeartCode speech runtime SHALL preserve all existing built-in Kokoro voices and SHALL additionally discover and synthesize only healthy active custom voice registry entries.

#### Scenario: Custom pack is only staged
- **WHEN** a public client lists voices or requests synthesis
- **THEN** the staged voice is absent from discovery and rejected by the ordinary speech endpoint

#### Scenario: Custom pack is active and healthy
- **WHEN** a public client lists voices and then requests synthesis with its stable ID
- **THEN** the ID is discoverable and synthesis uses the registry's exact active artifact digest

### Requirement: Custom voice lifecycle does not degrade live speech

Building, staging, activating, rolling back, retiring, reconciling, or deleting custom voices SHALL NOT change the existing speech authentication boundary, supported delivery formats, `opus-40k` live profile, or availability of unrelated voices.

#### Scenario: Voice build runs during live calls
- **WHEN** Quick Chat and character calls synthesize speech while an offline voice build is queued or executing
- **THEN** existing calls remain within the accepted latency/error budget and keep their requested output profile
