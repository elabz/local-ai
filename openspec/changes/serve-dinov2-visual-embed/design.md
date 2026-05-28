## Context

`heartcode-embed-vision` (nomic CLIP, 768-d) covers text→image + coarse semantic image→image. DINOv2 adds the missing flavor: fine-grained **visual/instance** image→image similarity (no text). Best retrieval stacks run both (CLIP for text + semantics, DINOv2 for visual reranking / "more like this"). This repo serves models only; storage/search/index are downstream, and DINOv2 vectors form a **separate space** (not comparable to CLIP/text vectors).

Hardware: 8× P104-100 (8 GB, sm_61 — no bf16, no flash-attn, crippled fp16). All 8 cards are currently in use (chat 1-6, image 7-8); GPU 1-3 already ~7.4 GB (chat+vision), GPU 4-6 ~6.5 GB (chat+text-embed). DINOv2 runs frozen (feature extraction only) via `transformers` `AutoModel`, fp32, standard attention.

## Goals / Non-Goals

**Goals:** serve the best-quality *servable* DINOv2 variant as image embeddings; OpenAI `/v1/embeddings` (image-only); benchmark vs nomic-vision on image→image.

**Non-Goals:** copy/near-dup detection (that's SSCD, non-commercial — out of scope); text→image (DINOv2 has no text); replacing the CLIP model; vector storage/search (downstream); fine-tuning (use frozen features).

## Decisions

### Decision 1: DINOv2 (visual similarity), not SSCD (copy detection)
"Similar objects" = visual/instance similarity → DINOv2. SSCD would actively reject non-identical images, the opposite of what's wanted, and is CC-BY-NC. Confirmed in the explore.

### Decision 2: Variant — ViT-L/14 with registers, co-located (RESOLVED)
Serve **`facebook/dinov2-with-registers-large`** (ViT-L/14, 1024-d), **co-located with the chat servers**, `MAX_BATCH_SIZE` bounded. Contingent on VRAM fit (chat ~6.2 GB + L ~1.3 GB ≈ **7.5 GB/8 GB**, comparable to the working vision-embed co-location at ~7.4 GB). **Fallback: ViT-B/14 (+reg, 768-d, ~0.4 GB)** if it OOMs under chat load. ViT-g/14 (1.1B, ~4.4 GB) was considered "best raw quality" but won't co-locate on 8 GB and needs a dedicated card (none free) — deferred unless the eval shows a decisive quality gap.

| Variant | ~fp32 VRAM | Dim | Status |
|---------|-----------|-----|--------|
| ViT-B/14 +reg | ~0.4 GB | 768 | fallback if L OOMs |
| **ViT-L/14 +reg** ✅ | ~1.3 GB | 1024 | **chosen** — co-located with chat |
| ViT-g/14 +reg | ~4.4 GB | 1536 | deferred (needs a dedicated card) |

### Decision 6: Embed tier = 2 servers of each type, one per chat GPU (RESOLVED)
Re-layout the embed tier so each of the 6 chat GPUs co-locates exactly one embed server, **2 of each type** (supersedes the `gpu-rebalance` 3 vision + 3 text):

```
GPU 1  SFW chat  + vision-embed   heartcode-embed-vision  :8101   (keep)
GPU 2  SFW chat  + vision-embed   heartcode-embed-vision  :8102   (keep)
GPU 3  SFW chat  + DINOv2 L/14    heartcode-embed-visual  :8104   (was vision-embed-3)
GPU 4  NSFW chat + text-embed     heartcode-embed         :8093   (keep)
GPU 5  NSFW chat + text-embed     heartcode-embed         :8094   (keep)
GPU 6  NSFW chat + DINOv2 L/14    heartcode-embed-visual  :8105   (was text-embed :8095)
GPU 7-8  image (2x, unchanged)
```

Minimal-churn from the current 3+3: drop `vision-embed-3` (GPU 3) and `embedding-server-6` (GPU 6, :8095); add 2 DINOv2 on those freed slots. Each embed type ends with 2 load-balanced backends. Trade-off: vision/text capacity drops 3→2 each (accepted) to fit DINOv2 without freeing a whole card.

### Decision 3: Single global (CLS) vector for v1
Return one vector per image (CLS / pooled output). DINOv2 patch tokens enable region/object-level "find this object inside a scene" but require multi-vector storage downstream — deferred to a possible v2.

### Decision 4: Image-only OpenAI `/v1/embeddings`, separate space
Accept images (`data:` URI / base64 / http(s) URL), return OpenAI `data[]` with one vector each. **Text input → 400** (no text encoder). Document clearly that these vectors are NOT comparable to `heartcode-embed-vision`; downstream keeps a separate index.

### Decision 5: Mirror the vision-embed serving pattern; eval before commit
Build like `gpu-server/vision-embed/` (FastAPI, in-process `AutoModel`, fp32, eager, health-gated, Prometheus). Benchmark variants on image→image "similar object" probes via `docs/embedding-model-eval.md` before finalizing the variant.

## Risks / Trade-offs

- **"Best quality" (ViT-g) doesn't co-locate** → either accept ViT-L (sweet spot) or free a dedicated card; make it an explicit placement decision, not a silent downgrade.
- **ViT-L on GPU 4-6 is VRAM-tight** (~7.8 GB) → bound batch/image size; monitor; fall back to ViT-B if OOM under chat load.
- **License** → DINOv2 weights are Apache-2.0 (Meta relicensed) — verify the exact checkpoint's license before commercial use; SSCD/`with-registers` checkpoints — confirm.
- **Separate index downstream** → DINOv2 ≠ CLIP space; the downstream app must not mix them.
- **Newer alternative**: DINOv3 (2025) is higher quality but has a non-Apache custom license and larger sizes — noted as a future option, not this change.

## Migration Plan

1. Build the DINOv2 service (mirror vision-embed; frozen `AutoModel`, fp32, CLS vector) + snapshot the checkpoint.
2. On PEA: stop `vision-embed-3` (GPU 3) + `embedding-server-6` (GPU 6); start 2 DINOv2 on GPU 3 + GPU 6; **verify VRAM fits (~7.5 GB)** — if OOM, switch to ViT-B.
3. docker-compose updated for the 2+2+2 layout; LiteLLM: `heartcode-embed-visual` (2), `heartcode-embed-vision` (2), `heartcode-embed` (2); prod restart + validate.
4. Benchmark DINOv2 vs nomic-vision on image→image probes.
**Rollback:** restore the 3+3 layout (compose + LiteLLM) from git; restart.

## Open Questions

- **Registers** variant vs plain DINOv2 (registers generally cleaner; verify on our images)?
- **Patch/multi-vector** (object-region search) now or defer to v2?
- **Fusion**: does the downstream app combine CLIP + DINOv2 rankings, or expose DINOv2 as a standalone "more like this"?
- **VRAM under load**: does ViT-L hold on GPU 3/6 at peak chat context, or fall back to ViT-B?
