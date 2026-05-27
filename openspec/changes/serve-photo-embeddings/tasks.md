## 1. Model selection (offline eval — gating)

- [ ] 1.1 Assemble a representative natural-photo sample with a few text→image and image→image probes (offline; no storage infra needed)
- [ ] 1.2 Generate embeddings from the candidates: `nomic-embed-vision-v1.5` + `nomic-embed-text-v1.5` (768-d, default), at least one of `jina-clip-v2` / SigLIP2, and BiQwen2.5 as the document-domain baseline
- [ ] 1.3 Score offline with cosine recall@k / nDCG for text→image and image→image; record VRAM + latency in fp32 on a P104-100
- [ ] 1.4 Pick the model + dimension; record the decision and numbers in `design.md` Open Questions and `CLAUDE.md`

## 2. Serving implementation

- [ ] 2.1 Build the model server for the chosen model (mirror `gpu-server/multimodal-embed/`): in-process load, **fp32**, eager attention (no bf16/flash-attn), single shared text+image space
- [ ] 2.2 Implement `/v1/embeddings` accepting text strings and images (data URI / base64 / http(s) URL); apply the `search_query:` prefix to text queries; return OpenAI `data[]` in input order
- [ ] 2.3 Reject malformed/oversized images with 4xx without crashing; cap image size/batch for Pascal activation memory
- [ ] 2.4 `/health` (model-loaded readiness, reports dimension) + Prometheus metrics + Dockerfile

## 3. Integration

- [ ] 3.1 Add the service to `gpu-server/docker-compose.yml` on a GPU (decide coexist vs replace BiQwen2.5 on GPU 7); set healthcheck + mem/GPU limits
- [ ] 3.2 Activate the `heartcode-embed-vision` entry in `litellm/config.yaml` (uncomment, set `api_base`/port)
- [ ] 3.3 Verify text + image requests return identical-dimension shared-space vectors through the proxy

## 4. Docs & validation

- [ ] 4.1 Update `CLAUDE.md` and `docs/` (chosen model, GPU/port layout, `heartcode-embed-vision` endpoint)
- [ ] 4.2 Run `openspec validate serve-photo-embeddings --strict` and confirm the served endpoint matches the spec scenarios
