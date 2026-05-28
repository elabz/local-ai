## ADDED Requirements

### Requirement: Multimodal embedding endpoint
The system SHALL expose an OpenAI-compatible `POST /v1/embeddings` endpoint, backed by `nomic-embed-multimodal-3b`, that accepts text and image inputs and returns one dense vector per input item. Vectors for text and images SHALL lie in the same shared latent space so that text-to-image and image-to-text similarity are meaningful.

#### Scenario: Text input returns a dense vector
- **WHEN** a client POSTs `{"model": "heartcode-embed", "input": "a red bicycle"}`
- **THEN** the response contains one embedding vector of the model's fixed dimension in OpenAI `data[].embedding` format

#### Scenario: Image input returns a dense vector in the same space
- **WHEN** a client POSTs an image as a base64 `data:` URI (or `{"image": "<base64|url>"}`) in `input`
- **THEN** the response contains one embedding vector of the same dimension as text embeddings, comparable via cosine/dot similarity to text vectors

#### Scenario: Mixed batch preserves order
- **WHEN** `input` is an array mixing text strings and image items
- **THEN** the response returns one vector per item in the same order as the input array

#### Scenario: Malformed image input is rejected clearly
- **WHEN** an input item is declared as an image but is not decodable
- **THEN** the endpoint returns a 4xx error identifying the offending item, and does not crash the service

### Requirement: Pascal-compatible precision handling
The service SHALL run the model in a precision supported by the P104-100 (Pascal `sm_61`) GPUs — `float32` or `float16` — and SHALL NOT require `bfloat16`. The active precision SHALL be configurable (environment variable) and the chosen default SHALL be recorded after on-hardware benchmarking of VRAM and latency.

#### Scenario: Service starts without bf16
- **WHEN** the service loads the model on a P104-100 GPU
- **THEN** it loads weights as float32 or float16 (never bfloat16) and reaches a healthy state

#### Scenario: Precision is configurable
- **WHEN** the precision environment variable is set to `float16` or `float32`
- **THEN** the service loads the model in that precision and reports it on startup/health

### Requirement: Dedicated GPU allocation within VRAM budget
The embedding service SHALL run on one or more GPUs dedicated to it (not shared with a chat model), and its weights plus activations SHALL fit within the dedicated GPUs' 8GB-per-card VRAM budget. When the chosen precision requires more than one card, the service SHALL shard across the assigned GPU UUIDs.

#### Scenario: Single-GPU deployment fits in VRAM
- **WHEN** the service runs in a precision that fits one 8GB card
- **THEN** model load and a representative text+image request complete without CUDA out-of-memory

#### Scenario: Multi-GPU deployment shards across assigned cards
- **WHEN** the chosen precision exceeds one card's VRAM
- **THEN** the service loads across exactly the assigned GPU UUIDs and serves requests without OOM

#### Scenario: No co-location with chat models
- **WHEN** the GPU layout is applied
- **THEN** each GPU assigned to the embedding service hosts no chat (8B) container

### Requirement: Health and observability
The service SHALL expose a `/health` endpoint reflecting model-loaded readiness and SHALL expose Prometheus metrics consistent with the existing GPU servers, so monitoring and the watchdog can supervise it.

#### Scenario: Health reflects model readiness
- **WHEN** the model is still loading
- **THEN** `/health` reports not-ready, and reports healthy only once the model can serve an embedding

#### Scenario: Metrics are scrapable
- **WHEN** Prometheus scrapes the service
- **THEN** request count, latency, and error metrics are exposed in the same format as the other GPU servers

### Requirement: LiteLLM routing preserves the public model name
The system SHALL route the public `heartcode-embed` model through LiteLLM to the new service with `mode: embedding`, so existing text-embedding clients continue to function after cutover without changing the model name.

#### Scenario: Existing text clients keep working via heartcode-embed
- **WHEN** a client calls LiteLLM with `model: "heartcode-embed"` and text input after cutover
- **THEN** it receives a valid embedding from the new multimodal service

#### Scenario: Rate limits and timeouts are tuned for heavier requests
- **WHEN** the LiteLLM config is applied
- **THEN** the `heartcode-embed` deployment(s), rate limits, and request timeout reflect the new lower-throughput, higher-latency profile (not the old 7-server values)

## REMOVED Requirements

### Requirement: Text-only embedding tier (nomic-embed-text-v1.5)
**Reason**: Replaced by the multimodal `nomic-embed-multimodal-3b` service; the 7 per-GPU `llama-server` text-embed containers (ports 8090–8096) and their GGUF model are retired so their GPU capacity can be reallocated.

**Migration**: Clients keep using the `heartcode-embed` model name (now multimodal). Because the vector dimension and semantics change, all previously stored `heartcode-embed` vectors MUST be re-computed/re-indexed against the new model before similarity results are trusted; the old tier remains available for rollback until re-indexing completes.
