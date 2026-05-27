## 1. Model selection & evaluation (gating decision)

- [ ] 1.1 Assemble a representative natural-photo eval set with labeled text→image query pairs (and a few image→image probes) from the real corpus
- [ ] 1.2 Stand up candidate embedding models behind a temporary endpoint: `nomic-embed-vision-v1.5` + `nomic-embed-text-v1.5` (768-d, default), and at least one of `jina-clip-v2` (1024-d) or SigLIP2
- [ ] 1.3 Include the in-flight BiQwen2.5 (`nomic-embed-multimodal-3b`, 3584-d) as the baseline to confirm/deny the document-vs-photo mismatch
- [ ] 1.4 Score candidates on recall@k / nDCG for text→image and image→image on the eval set; record VRAM + latency in fp32 on a P104-100
- [ ] 1.5 Pick the model + dimension; record the decision and numbers in design.md Open Questions and in `CLAUDE.md`

## 2. Embedding endpoint

- [ ] 2.1 Deploy the chosen model on the GPU box (fp32 on Pascal; eager attention; no bf16) and expose it via LiteLLM, returning one vector per text/image item in a shared space
- [ ] 2.2 Decide coexistence with BiQwen2.5 on GPU 7 (replace vs run alongside) given VRAM/card budget; update `gpu-server/docker-compose.yml` and `litellm/config.yaml` accordingly
- [ ] 2.3 Verify text and image embeddings come back with identical dimension and are L2-normalizable (or already normalized)

## 3. Elasticsearch readiness

- [ ] 3.1 Record the running Elasticsearch version and confirm it supports the chosen dimension as an indexed `dense_vector` (≤2048 older; 4096 needs ES ≥ 8.11)
- [ ] 3.2 Inspect the existing text-embedding index mapping; decide reuse vs new versioned index (dimension/normalization compatibility)
- [x] 3.3 Create the image index mapping: `dense_vector` with `index: true`, `similarity: cosine`, HNSW params, plus metadata fields and a stable image-id key — `image-search/es_mapping.json` (768-d, cosine, hnsw m=16/ef=100; `image_id` keyword, `metadata`/`source_ref`/`model`/`ingested_at`). Service auto-creates the index from it on startup (`AUTO_CREATE_INDEX`). **Not yet applied to a live ES** (no endpoint available here).
- [ ] 3.4 If the corpus is large, evaluate quantized kNN (`int8_hnsw`) for memory footprint

## 4. Search service (ingestion + query)

- [x] 4.1 Scaffold a small search service/module that calls `heartcode-embed` for embeddings and Elasticsearch for storage/kNN (config-driven model name + index name) — new `image-search/` (Python/FastAPI, mirrors `gpu-server/` pattern): `config.py`, `embed_client.py` (httpx → `/v1/embeddings`), `es_client.py` (httpx → ES REST), `vectors.py`, `metrics.py`, `routes.py`, `server.py`, `Dockerfile`, `requirements.txt`, `README.md`. All compile-checked.
- [x] 4.2 Implement ingestion: image → embed → L2-normalize → upsert by id with metadata; idempotent re-ingest overwrites; partial-failure safe (spec: Image ingestion) — `POST /ingest` (`routes.py`): per-item embed+upsert (`PUT _doc/{id}` overwrites); one bad image is reported in `failed[]`, never writes a partial doc.
- [x] 4.3 Implement text→image search: text query → embed → kNN → ranked hits with score, honoring `top_k` and min-score threshold (spec: Text-to-image search, Result shape) — `POST /search/text`; prepends `TEXT_QUERY_PREFIX` (`search_query: `); `top_k` clamped to `MAX_TOP_K`, `min_score` passed to ES.
- [x] 4.4 Implement image→image search: query image → embed → kNN; reject malformed/oversized images with 4xx without crashing (spec: Image-to-image search) — `POST /search/image`; cheap size cap + upstream-4xx→400 translation (`EmbedBadRequest`).
- [x] 4.5 Enforce shared-space consistency: reject queries whose embedding dimension differs from the index mapping with a "re-index required" error (spec: Shared-space consistency) — `vectors.check_dim` vs live `index_dims` (read at startup) → 400 `DimensionMismatch` ("re-index required"); verified by unit test.

## 5. Backfill & migration

- [ ] 5.1 Build a backfill job that embeds and indexes the existing image corpus (store source-asset reference so re-embedding never needs re-upload)
- [ ] 5.2 If unifying spaces, re-embed existing text vectors with the chosen model into the new index
- [ ] 5.3 Keep the old index until validation passes; make the active index name a config flip for rollback

## 6. Validation & docs

- [ ] 6.1 Validate text→image and image→image against the eval set through the search service end-to-end; confirm ranking quality matches the task 1.4 numbers
- [ ] 6.2 Verify the spec scenarios: re-ingest overwrite, no-results-above-threshold, malformed query image → 4xx, dimension mismatch → re-index error, `top_k`/threshold behavior
- [ ] 6.3 Update `CLAUDE.md` and `docs/` (chosen model, GPU/port layout, ES index/mapping, search API)
- [ ] 6.4 Run `openspec validate add-image-semantic-search --strict` and confirm the deployed system matches the spec scenarios
