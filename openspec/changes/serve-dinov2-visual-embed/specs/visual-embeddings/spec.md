## ADDED Requirements

### Requirement: Serve DINOv2 image embeddings

The system SHALL accept an image — as a `data:` URI, raw base64, or http(s) URL — on the OpenAI `/v1/embeddings` endpoint and return a single fixed-dimension DINOv2 visual-similarity vector for it. Vectors SHALL be L2-normalized so cosine similarity is meaningful for image→image retrieval.

#### Scenario: Embed an image
- **WHEN** a client POSTs `/v1/embeddings` with an image input to `heartcode-embed-visual`
- **THEN** the system returns one fixed-dimension vector for that image in the OpenAI `data[]` shape

#### Scenario: Batch of images preserves order
- **WHEN** a client submits a list of images
- **THEN** the system returns one vector per image, in input order, each at its index

### Requirement: Image-only — reject text

DINOv2 has no text encoder. The system SHALL reject text inputs with a 4xx error rather than returning a meaningless vector, so callers cannot accidentally mix modalities.

#### Scenario: Text input is rejected
- **WHEN** a client submits a plain text string (not an image) to `heartcode-embed-visual`
- **THEN** the system returns a 4xx error explaining the endpoint is image-only

#### Scenario: Malformed image
- **WHEN** a client submits an undecodable or oversized image
- **THEN** the system returns a 4xx error identifying the problem and keeps serving subsequent requests

### Requirement: Separate vector space from CLIP/text embeddings

DINOv2 vectors SHALL NOT be presented as comparable to `heartcode-embed-vision` / `heartcode-embed` vectors. The served dimension SHALL be fixed and reported (e.g. via `/health`), and documentation SHALL state that DINOv2 vectors require their own downstream index.

#### Scenario: Dimension is reported and consistent
- **WHEN** a client queries `/health` or embeds any image
- **THEN** the reported/served dimension matches the configured DINOv2 variant and is consistent across requests

### Requirement: Serving only — no storage

The service SHALL NOT store, index, or search vectors; it returns them to the caller and retains nothing. Persistence, indexing, and retrieval are downstream responsibilities.

#### Scenario: Vectors are returned, not stored
- **WHEN** a client requests an embedding
- **THEN** the system returns the vector in the response and writes it to no datastore
