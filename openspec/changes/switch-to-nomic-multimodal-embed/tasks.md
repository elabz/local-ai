## 1. Research & validation (pre-build)

- [x] 1.1 Confirm `nomic-embed-multimodal-3b` license permits our deployment (O4) — **License = Qwen RESEARCH LICENSE (non-commercial / research & eval only)**; permits dev/eval, NOT commercial without a separate Alibaba license. Flagged for product decision.
- [x] 1.2 Pin a `colpali-engine` commit/tag (`illuin-tech/colpali`) and the `transformers`/`accelerate`/`qwen-vl-utils` versions it needs — pinned `colpali-engine==0.3.13` (BiQwen2_5 since 0.3.9; last line before 0.3.14's transformers-5 bump), `transformers>=4.49.1,<5.0`, `accelerate>=0.26.0`, `peft>=0.13.0` (model is a LoRA adapter), `qwen-vl-utils>=0.0.8`, `torch==2.4.1` cu121 (sm_61). See `multimodal-embed/requirements.txt`.
- [ ] 1.3 In a throwaway container on PEA, confirm `import torch` works on the no-AVX Celeron and `torch.cuda.is_available()` is true on a P104-100
- [ ] 1.4 Load the model once and record the single-vector embedding dimension (O2) — expected **3584-d** per Nomic docs; confirm empirically on load (`bench.py`).

## 2. Embedding service (build artifact)

- [x] 2.1 Create the service dir under `gpu-server/` (e.g. `multimodal-embed/`) with a FastAPI app mirroring `server.py`/`routes.py`/`metrics.py`
- [x] 2.2 Load via `BiQwen2_5` + `BiQwen2_5_Processor`; force precision from env (`float32`/`float16`, never `bfloat16`); set `attn_implementation` to eager (no flash-attn) — `embed_model.py` (`_resolve_dtype` rejects bf16; `attn_implementation=eager`)
- [x] 2.3 Implement `POST /v1/embeddings`: detect text vs image items, run text branch and image branch, return one vector per item in input order (OpenAI `data[]` shape) — `routes.py`
- [x] 2.4 Define & implement the image input convention (base64 `data:` URI and/or `{"image": ...}`) with clear 4xx errors on malformed/undecodable images (D5, O3) — `image_input.py` (plain string=text, `data:` URI / `{"image": ...}`=image; `ImageInputError`→HTTP 400 with index)
- [x] 2.5 Cap max image resolution/tokens and batch size to bound eager-attention activation memory (O5) — `MAX_IMAGE_EDGE` downscale, `MAX_BATCH_SIZE`, `MAX_INPUT_ITEMS`, `MAX_IMAGE_BYTES`
- [x] 2.6 Implement `/health` reflecting model-loaded readiness and expose Prometheus metrics in the existing format — `/health` 503 until loaded; metrics reuse `inference_requests_total`/`inference_duration_seconds`/`active_requests`/`model_loaded`/`gpu_*` names
- [x] 2.7 Write a `Dockerfile` (CUDA base compatible with `sm_61`) installing torch + pinned `colpali-engine` deps — `nvidia/cuda:12.1.1` + torch 2.4.1 cu121

## 3. Model fetch & GPU layout

- [x] 3.1 Update `gpu-server/scripts/download-models.sh` to snapshot `nomic-ai/nomic-embed-multimodal-3b` into `./models` (replacing the `nomic-embed-text-v1.5` GGUF download) — added `download_hf_snapshot`; snapshots the adapter **and** the required `Qwen/Qwen2.5-VL-3B-Instruct` base into the HF cache under `/models`.
- [x] 3.2 Add the new service to `gpu-server/docker-compose.yml` on a freed GPU UUID (default: a low-traffic NSFW chat GPU), with healthcheck, mem limits, and Prometheus network — `multimodal-embed` on `GPU-f417c539` (1-indexed GPU 7), port 8100, healthcheck, 8g mem, `gpu-network`.
- [x] 3.3 Remove that GPU UUID from the chat service it was reassigned from — removed `gpu-server-7` (NSFW now GPU 4-6) and the co-located `embedding-server-7` (a dedicated card cannot also run an 8B chat / text-embed server).
- [ ] 3.4 Bring up the service standalone; smoke-test a text embedding and an image embedding end-to-end — **on PEA** (`bench.py`).

## 4. Precision & VRAM benchmark (resolve O1)

- [ ] 4.1 Benchmark fp16 on 1 GPU: record VRAM, latency for text and image requests, and OOM behavior
- [ ] 4.2 Benchmark fp32 (1 GPU if it fits, else 2-GPU `device_map` shard): record VRAM, latency, OOM behavior
- [ ] 4.3 Pick the default precision + final GPU count; set the env var and finalize compose GPU UUID assignment(s)
- [ ] 4.4 Record the chosen precision, dimension, and measured latency in the design's resolved Open Questions and in `CLAUDE.md`

## 5. Monitoring & supervision

- [x] 5.1 Add the embed service as a Prometheus scrape target in `gpu-server/configs/prometheus.yml` — added `multimodal-embed` job (`pea-embed-mm-1:9091`, `model_type: embed-multimodal`); dropped the removed `pea-gpu-7`.
- [x] 5.2 Add it to the GPU/memory watchdog so it is restarted on hang/OOM — `gpu-watchdog.sh` GPU index 6 now maps to `pea-embed-mm-1` (VRAM=0 / stopped → restart); added `GPU_HEALTH_PORTS[6]=8100` for the optional health check.

## 6. LiteLLM cutover

- [x] 6.1 Replace the 7 `heartcode-embed` deployments in `litellm/config.yaml` with the new service endpoint(s), keeping `model_name: heartcode-embed` and `mode: embedding` — single deployment → `192.168.0.144:8100/v1`, `mode: embedding`, `timeout: 120`.
- [x] 6.2 Re-tune `model_rate_limits`, parallelism, and embedding `request_timeout` for the heavier/lower-throughput profile — added `heartcode-embed` rpm 20; NSFW rpm 45→34 (3 GPUs); `global_max_parallel_requests` 14→13; per-deployment `timeout: 120`.
- [ ] 6.3 Restart LiteLLM and validate `heartcode-embed` text + image requests through the proxy — **on Prod (elm/192.168.0.152)**; not in the PEA authorization.
- [ ] 6.4 Confirm rollback path works: reverting config to the old 7 deployments restores text embeddings — **on Prod**; `git checkout HEAD~1 -- litellm/config.yaml`, embed-1..6 still up.

## 7. Decommission & docs

- [ ] 7.1 Trigger downstream re-indexing of stored `heartcode-embed` vectors against the new model (breaking dimension change)
- [ ] 7.2 Remove the 7 `embedding-server-*` services from `docker-compose.yml` and delete the old `nomic-embed-text-v1.5` GGUF
- [x] 7.3 Update `CLAUDE.md` (Models table, port/GPU layout, safe limits) and `docs/pea-server-setup.md` — both updated: repo structure, topology, Models table, port/GPU layout, mem limits, rate limits, bring-up/verify steps, model details.
- [ ] 7.4 Run `openspec validate switch-to-nomic-multimodal-embed` and confirm the deployed system matches the spec scenarios
