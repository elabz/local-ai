# Image Search Service

Cross-modal image retrieval over Elasticsearch:

- **text→image** — search by description (`POST /search/text`)
- **image→image** — search by example (`POST /search/image`)

It is a thin orchestration layer (no GPU, no ML stack): embeddings come from the
`heartcode-embed` OpenAI-compatible `/v1/embeddings` endpoint (via LiteLLM),
storage and ANN from Elasticsearch `dense_vector` + kNN. The embedding model
(`heartcode-embed-vision`) is **config-driven** — it just needs to return one
vector per text/image item in a shared space.

> Implements openspec change `add-image-semantic-search` tasks 4.1–4.5 and the
> index mapping (3.3). Remaining tasks (model eval, deploy, backfill, live
> validation) need the photo corpus, GPU, and a live Elasticsearch.

## Model assumption

Defaults target the **768-d** `nomic-embed-vision-v1.5` (images) + `nomic-embed-text-v1.5`
(text) shared space (design Decision 2). Text **queries** are prefixed with
`search_query: ` (`TEXT_QUERY_PREFIX`); images get no prefix. If the model/dimension
changes, set `EMBED_DIM` and re-create the index (`es_mapping.json`).

## Endpoints

| Method | Path | Body |
|--------|------|------|
| POST | `/ingest` | `{"items": {"id","image","metadata?","source_ref?"}}` or a list |
| POST | `/search/text` | `{"query","top_k?","min_score?"}` |
| POST | `/search/image` | `{"image","top_k?","min_score?"}` |
| GET | `/health` | readiness (ES reachable + index dim == `EMBED_DIM`) |
| GET | `/metrics` | Prometheus |

`image` accepts a `data:` URI, raw base64, or an http(s) URL — the documented
`heartcode-embed` input convention. Malformed/oversized images return **400**.
A query whose embedding dimension differs from the index mapping returns **400**
("re-index required") — the shared-space consistency guard.

## Key env vars

| Var | Default | Notes |
|-----|---------|-------|
| `EMBED_BASE_URL` | `http://192.168.0.152:4000/v1` | LiteLLM `/v1` base |
| `EMBED_MODEL` | `heartcode-embed-vision` | model name passed through |
| `EMBED_API_KEY` | — | LiteLLM bearer key |
| `EMBED_DIM` | `768` | index/query dimension guard |
| `TEXT_QUERY_PREFIX` | `search_query: ` | nomic text-query prefix; `""` to disable |
| `ES_URL` | `http://localhost:9200` | Elasticsearch base |
| `ES_INDEX` | `image-embeddings` | target index |
| `ES_API_KEY` / `ES_USERNAME`+`ES_PASSWORD` | — | auth |
| `AUTO_CREATE_INDEX` | `true` | create index from `es_mapping.json` if missing |
| `DEFAULT_TOP_K` / `MAX_TOP_K` | `10` / `100` | result count bounds |

## Notes

- Vectors are L2-normalized before indexing and querying (`NORMALIZE=true`), so
  ES `cosine` scores are stable; `min_score` is passed through to ES (cosine
  `_score = (1 + cosine) / 2`).
- Ingestion is per-item: one bad image never blocks the rest and never writes a
  partial document.
- Elasticsearch ≥ 8.x assumed (top-level `knn` search; native dense_vector kNN).
