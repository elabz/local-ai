# Image-Embedding Model Evaluation

How to rank candidate **photo** embedding models on **your own image corpus** before
committing one as the production `heartcode-embed-vision` model.

> Why this matters: the model deployed today (`nomic-embed-vision-v1.5`) was chosen for
> shared-space + Apache-2.0 + Pascal fit, and **verified to work**, but it was *not* yet
> ranked for retrieval quality on real photos. Re-embedding a whole corpus is expensive,
> so confirm the model **before** a downstream bulk index. This eval is **offline** and
> **read-only** — it produces a decision, it does not deploy anything. (Vector storage /
> search live in the downstream app, not this repo.)

Tracks openspec change `finalize-vision-embed-rollout` tasks 2.x.

---

## 1. The decision this informs

Pick the model that serves `heartcode-embed-vision` (text + image → one shared vector
space), optimizing for, in order:

1. **Retrieval quality** on *your* photos (text→image and image→image).
2. **License** — must allow your intended use (commercial vs research/eval).
3. **Pascal/VRAM fit** — runs in fp32 on a P104-100 (8 GB), ideally co-locatable (~≤1.5 GB).
4. **Shared text space** — bonus if it reuses an existing text-embedding space (no text re-index).

## 2. Candidates

| Model | Dim | Params | License | Notes |
|-------|-----|--------|---------|-------|
| **`nomic-ai/nomic-embed-vision-v1.5`** (+ `nomic-embed-text-v1.5`) | 768 | ~0.2B vision + ~0.1B text | **Apache-2.0** ✅ commercial | Deployed default. Shares space with the text model we already run. Lightest on Pascal (~1.1 GB). |
| **`jinaai/jina-clip-v2`** | 1024 (Matryoshka → 64) | ~0.9B | **CC-BY-NC-4.0** ⚠️ non-commercial weights | Strong multilingual (89 langs) photo retrieval. Commercial use needs a Jina license (see §6). Heavier on Pascal. |
| **`google/siglip2-*`** (e.g. `siglip2-base-patch16-512`) | 768–1152 (by variant) | 0.2–1B+ | **Apache-2.0** ✅ commercial | High quality, commercial-safe. Separate space (would need text re-index). Native in `transformers`. |
| **`nomic-ai/nomic-embed-multimodal-3b`** (BiQwen2.5) | 3584 | 3B | **Qwen RESEARCH** ⚠️ non-commercial | Baseline only — it's a *document*-retrieval model; include it to confirm/deny the photo mismatch. Heavy (~6–7 GB). Shelved. |

**License is a first-class axis, not a footnote.** If your use is commercial, a model that
wins on quality but is CC-BY-NC (`jina-clip-v2`) or research-only (BiQwen2.5) can't ship
without a separate license — weigh that against the quality delta vs the Apache-2.0 options.

## 3. Build the eval set

You need, from your real corpus:

- **Images**: a representative sample (a few hundred to a few thousand is plenty for ranking).
- **Text→image queries**: ~30–100 natural-language descriptions, each labeled with the
  image id(s) that *should* be retrieved (relevance judgments). These are the ground truth.
- **Image→image probes** (optional): a handful of query images, each with a few known
  "similar" image ids.

Format suggestion (`eval_set.jsonl`):

```jsonl
{"type": "image", "id": "img_0001", "path": "corpus/img_0001.jpg", "meta": {"tags": ["bicycle","red"]}}
{"type": "text_query", "query": "a red bicycle leaning on a wall", "relevant_ids": ["img_0001","img_0157"]}
{"type": "image_query", "query_path": "probes/p1.jpg", "relevant_ids": ["img_0042"]}
```

Keep it honest: judgments should reflect what a *user* would consider a correct hit, not
what any single model happens to return.

## 4. Metrics

For each candidate, embed all corpus images and all queries (same model/space), then for
each query rank corpus images by **cosine similarity** (vectors L2-normalized) and compute:

- **Recall@k** (k = 1, 5, 10) — fraction of queries whose relevant image appears in the top-k. Primary.
- **nDCG@k** — rewards ranking relevant hits higher (use if you have graded relevance).
- **MRR** — mean reciprocal rank of the first relevant hit. Good single-number summary.

Report text→image and image→image separately. No vector DB needed — for a few thousand
images a brute-force cosine matrix in NumPy is instant and exact (this is a ranking study,
not a serving benchmark).

Also record, per model, on a P104-100 in **fp32**:

- **VRAM** at load + during a batch (`nvidia-smi`).
- **Latency** per text and per image embedding (median over ~50 calls).
- Whether it **co-locates** with a chat model (≤ ~1.5 GB free on a chat GPU).

## 5. How to run

Two ways to get embeddings for the candidates — pick per model:

- **Already-served model** (`nomic-embed-vision-v1.5`): hit the live endpoint
  `POST http://192.168.0.144:8101/v1/embeddings` (text strings or `{"image": "<data-uri>"}`),
  exactly like production. No extra setup.
- **A candidate not yet deployed** (`jina-clip-v2`, `siglip2`): either
  - load it locally on a P104-100 in a throwaway container (transformers, fp32 — see each
    model card for the `trust_remote_code` snippet), **or**
  - for `jina-clip-v2`, call the **Jina API** (§6) so you don't need local GPU/deps for the eval.

Sketch (`eval_run.py`, offline, stdlib + numpy):

```python
# 1. load eval_set.jsonl
# 2. for each candidate: embed corpus images + queries (HTTP to an endpoint OR local model)
#    -> L2-normalize all vectors
# 3. scores = queries @ corpus.T   (cosine, since normalized)
# 4. rank, compute recall@k / nDCG@k / MRR for text->image and image->image
# 5. print a table: model | dim | recall@1/5/10 | nDCG@10 | MRR | VRAM | latency | license
```

Record the chosen model + the numbers in this doc's results table (below), in `CLAUDE.md`,
and in the `finalize-vision-embed-rollout` design. If a non-default model wins, redeploy
`vision-embed` with it (swap `VISION_MODEL_ID`/loader) and re-point the LiteLLM backends.

## 6. Getting access to `jina-clip-v2`

`jina-clip-v2` weights are **CC-BY-NC-4.0** (non-commercial). Three ways to use it:

1. **HuggingFace download — free, non-commercial / evaluation.**
   - Model: `jinaai/jina-clip-v2`. Accept the terms on the model page if prompted
     (`huggingface-cli login` with a free HF token).
   - Load locally (needs `trust_remote_code=True`, plus `einops` and `timm`):
     ```python
     from transformers import AutoModel
     m = AutoModel.from_pretrained("jinaai/jina-clip-v2", trust_remote_code=True)
     # m.encode_text([...]) / m.encode_image([...])  -> 1024-d (truncatable)
     ```
   - On Pascal: run **fp32**, `attn_implementation="eager"` (no flash-attn). ~0.9B, heavier
     than the nomic pair but fine for an offline eval.
   - **Fine for this eval. NOT licensed for commercial production.**

2. **Jina Embeddings API — easiest for the eval, no local GPU/deps.**
   - Get a free key at <https://jina.ai/embeddings/> (free tier ~1M tokens, no card).
   - `POST https://api.jina.ai/v1/embeddings` with `Authorization: Bearer <key>`:
     ```json
     {"model": "jina-clip-v2", "input": [{"text": "a red bicycle"}, {"image": "https://…/img.jpg"}], "dimensions": 768}
     ```
   - Returns embeddings for text and images in one shared space (set `dimensions` to match
     a 768-d comparison if you like — Matryoshka). Note: data leaves your network (a hosted
     API), so use non-sensitive sample images for the eval, or prefer option 1.

3. **Commercial license — required if `jina-clip-v2` wins and you ship it.**
   - Self-hosting the weights commercially needs a license from Jina AI (sales@jina.ai), or
     use it via the metered Jina API / AWS SageMaker / Azure marketplace listings.
   - If commercial terms are a blocker, prefer the **Apache-2.0** options
     (`nomic-embed-vision-v1.5`, `siglip2`) — only adopt `jina-clip-v2` if its quality lead
     justifies the licensing.

## 7. Results (fill in after running)

| Model | Dim | Recall@1 | Recall@5 | Recall@10 | nDCG@10 | MRR | VRAM (fp32) | Latency (txt/img) | License | Co-locatable |
|-------|-----|----------|----------|-----------|---------|-----|-------------|-------------------|---------|--------------|
| nomic-embed-vision-v1.5 | 768 | | | | | | ~1.1 GB | | Apache-2.0 | yes |
| jina-clip-v2 | 1024 | | | | | | | | CC-BY-NC | TBD |
| siglip2-… | | | | | | | | | Apache-2.0 | TBD |
| nomic-embed-multimodal-3b (baseline) | 3584 | | | | | | ~6–7 GB | | Qwen RESEARCH | no |

**Decision:** _record the chosen model, why, and the date here._
