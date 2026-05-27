## ADDED Requirements

### Requirement: Image ingestion into the vector index

The system SHALL embed each ingested image with the configured joint-embedding model and upsert the resulting vector, together with caller-supplied metadata and a stable image identifier, into the Elasticsearch vector index. Vectors SHALL be L2-normalized before storage. Re-ingesting an existing identifier SHALL replace the prior vector and metadata.

#### Scenario: Successful image ingestion
- **WHEN** a client submits an image with a unique identifier and metadata
- **THEN** the system embeds the image, L2-normalizes the vector, and stores a document keyed by that identifier in the index, returning a success status

#### Scenario: Re-ingesting an existing identifier
- **WHEN** a client ingests an image using an identifier that already exists in the index
- **THEN** the system overwrites the stored vector and metadata for that identifier rather than creating a duplicate

#### Scenario: Embedding failure during ingestion
- **WHEN** the embedding endpoint returns an error or times out for an ingested image
- **THEN** the system does not write a partial document and returns an error identifying the failed image, leaving previously stored documents unchanged

### Requirement: Text-to-image search

The system SHALL accept a free-text query, embed it with the same model and space used for ingestion, and return stored images ranked by cosine similarity (descending). The query SHALL support a `top_k` limit and an optional minimum-score threshold.

#### Scenario: Search images by description
- **WHEN** a client submits a text query such as "a red bicycle" with `top_k = 10`
- **THEN** the system returns at most 10 image identifiers with their metadata and similarity scores, ordered from most to least similar

#### Scenario: No results above threshold
- **WHEN** a text query produces no stored image whose score meets the minimum-score threshold
- **THEN** the system returns an empty result set with a success status (not an error)

### Requirement: Image-to-image search

The system SHALL accept an image query, embed it in the same space as the stored image vectors, and return the most similar stored images ranked by cosine similarity. Malformed or undecodable query images SHALL be rejected with a 4xx error and SHALL NOT crash the service.

#### Scenario: Search by example image
- **WHEN** a client submits a query image
- **THEN** the system returns stored images ranked by visual/semantic similarity to the query image

#### Scenario: Malformed query image
- **WHEN** a client submits an undecodable or oversized image as a query
- **THEN** the system returns a 4xx error describing the problem and continues serving subsequent requests

### Requirement: Shared-space consistency

Stored image vectors and query vectors (text or image) SHALL be produced by the same model and embedding dimension so that cross-modal cosine comparison is meaningful. The system SHALL reject a query whose embedding dimension does not match the index mapping rather than returning meaningless scores.

#### Scenario: Text and image queries share one space
- **WHEN** the same content is embedded once as text and once as an image by the configured model
- **THEN** both vectors have identical dimension and are comparable by cosine similarity within the same index

#### Scenario: Dimension mismatch with the index
- **WHEN** a query vector's dimension differs from the index's `dense_vector` mapping (e.g. after a model change without re-indexing)
- **THEN** the system rejects the query with an error indicating a re-index is required rather than silently returning results

### Requirement: Result shape and ranking controls

Search responses SHALL include, per hit, the image identifier, the stored metadata, and the similarity score. The system SHALL expose `top_k` and an optional minimum-score threshold as request parameters, applying the threshold as a filter and `top_k` as the maximum number of returned hits.

#### Scenario: top_k bounds the result count
- **WHEN** a query matches more stored images than the requested `top_k`
- **THEN** the system returns exactly `top_k` highest-scoring hits

#### Scenario: Threshold filters low-similarity hits
- **WHEN** a minimum-score threshold is supplied with a query
- **THEN** the system omits all hits scoring below the threshold from the response
