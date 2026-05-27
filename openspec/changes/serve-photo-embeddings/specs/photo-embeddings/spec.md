## ADDED Requirements

### Requirement: Serve text embeddings

The system SHALL accept a text string on the OpenAI `/v1/embeddings` endpoint and return a single embedding vector for it. Text intended as a search query SHALL be embedded with the model's query convention (the `search_query:` prefix for the nomic pair).

#### Scenario: Embed a text string
- **WHEN** a client POSTs `/v1/embeddings` with a text string as input
- **THEN** the system returns one embedding vector for that text in the `data[]` array

### Requirement: Serve image embeddings

The system SHALL accept an image — as a `data:` URI, raw base64, or http(s) URL — on `/v1/embeddings` and return a single embedding vector for it. Malformed, undecodable, or oversized images SHALL be rejected with a 4xx error and SHALL NOT crash the service.

#### Scenario: Embed an image
- **WHEN** a client POSTs `/v1/embeddings` with an image input
- **THEN** the system returns one embedding vector for that image

#### Scenario: Malformed image
- **WHEN** a client submits an undecodable or oversized image
- **THEN** the system returns a 4xx error identifying the problem and continues serving subsequent requests

### Requirement: Shared text and image space

Text and image inputs SHALL be embedded by the same model into the same vector space and SHALL produce vectors of identical dimension, so that a downstream consumer can compare a text vector and an image vector directly (cosine). The system SHALL report this dimension (e.g. via `/health`).

#### Scenario: Text and image vectors are comparable
- **WHEN** the same subject is embedded once as text and once as an image
- **THEN** both vectors have identical dimension and lie in one space usable for cross-modal comparison

### Requirement: OpenAI-compatible embeddings response

For a request with one or more inputs, the system SHALL return an OpenAI-shaped response: a `data[]` list with one `{object: "embedding", index, embedding}` per input, in input order, plus the served `model` name. Mixed text and image inputs in one request SHALL each yield one vector at the matching index.

#### Scenario: Batch of mixed inputs preserves order
- **WHEN** a client submits a list of inputs mixing text and images
- **THEN** the system returns one embedding per input, in the same order, each at its input index

### Requirement: Serving only — no storage

The service SHALL NOT store, index, or search embedding vectors; it returns vectors to the caller and retains nothing. Persistence, indexing, and retrieval are the responsibility of downstream consumers.

#### Scenario: Vectors are returned, not stored
- **WHEN** a client requests an embedding
- **THEN** the system returns the vector in the response and does not write it to any datastore
