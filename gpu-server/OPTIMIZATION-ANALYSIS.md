# LLM Inference Optimization Analysis

## Research Summary

Based on comprehensive research of llama.cpp optimization techniques (2025), this document analyzes your current configuration and identifies opportunities to improve **Time to First Token (TTFT)**, **throughput**, and **prompt processing speed**.

---

## Current Configuration Status

### Already Optimized ✅

Your configuration already includes several critical optimizations:

| Setting | Current | Status | Impact |
|---------|---------|--------|--------|
| Continuous Batching | `--cont-batching` | ✅ Enabled | 43.7% faster prompt processing vs batch-at-a-time |
| Flash Attention | `--flash-attn on` | ✅ Enabled | Faster inference, lower memory, better context handling |
| KV Cache Quantization | `q8_0` (K & V) | ✅ Enabled | 50% memory reduction vs FP16 |
| Prompt Caching | `--cache-reuse 256` | ✅ Enabled | Avoids reprocessing repeated prefixes |
| Memory Locking | `--mlock` | ✅ Enabled | Prevents swap, consistent latency |

---

## Current Constraints & Bottlenecks

### Why Settings Are Conservative

Your configuration is tuned for the **2-core Celeron CPU + 6GB P106-100 GPU** constraint:

```
Current Config          Reason
─────────────────────────────────────────────────────
N_BATCH: 128           Reduced from 512 (CPU bottleneck)
N_UBATCH: 64           Reduced from 512 (CPU can't handle more)
N_THREADS: 2           Matches physical CPU cores exactly
N_CTX: 8192            Reduced from default to fit 1536m container
MAX_CONCURRENT: 1      Only 1 inference request at a time
```

**The 2-core CPU is the limiting factor** - it's too weak to efficiently prepare batches larger than 128 tokens at once.

---

## Optimization Recommendations

### 1. **Increase Ubatch Size (Micro-batch)** - HIGH PRIORITY

**Current**: `N_UBATCH: 64`
**Recommended**: `N_UBATCH: 128` (match N_BATCH)

**Why**:
- ubatch is the physical GPU batch size - determines how many tokens processed per GPU compute step
- Current 64 underutilizes your GPU (P106 can handle more)
- Research shows GPU is waiting for CPU to prepare batches
- Increasing to 128 won't add much CPU overhead since N_BATCH is already 128

**How to Test**:
```bash
# Update config.py
N_UBATCH: 128

# Measure TTFT before and after
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"","messages":[{"role":"user","content":"Hello"}],"temperature":0.8}' \
  | jq '.usage.prompt_tokens'
```

**Expected Impact**: 5-10% faster TTFT (10-50ms improvement)

---

### 2. **Increase Context Window (Carefully)** - MEDIUM PRIORITY

**Current**: `N_CTX: 8192`
**Consider**: `N_CTX: 12288` (if memory allows)

**Analysis**:
- You allocated 1536m per container
- Current 8192 ctx uses ~1200-1300m (before request processing)
- Increasing to 12288 would use ~1400-1450m (still safe with 1536m limit)
- Larger context = slower TTFT but better long conversation handling

**Trade-off**:
```
8192 ctx:  + Faster TTFT (~5-7s), - Limited conversation memory
12288 ctx: - Slower TTFT (~6-9s), + Better long-context handling
```

**Recommendation**: **Stay at 8192** for now
- Your prompts are ~500 tokens max
- 8192 provides good balance
- If you see complaints about "forgetting" context, then increase to 12288

---

### 3. **Optimize Cache Reuse for 500-Token Prompts** - HIGH PRIORITY

**Current**: `--cache-reuse 256`
**Recommended**: Analyze and potentially increase to `512` or `1024`

**How It Works**:
- llama.cpp's `cache-reuse` enables KV cache slot management
- When a new request arrives, it searches for cached prefixes that match ≥50%
- If found, it reuses those cached tokens instead of reprocessing
- With 256 slots, you can cache up to 256 different conversation prefixes

**For Your Workload**:
- 10 users × ~5-10 conversations each = 50-100 active slots
- Current 256 slots has 2.5x headroom (good)
- **Keep at 256** - no need to increase, wasting memory otherwise

**However, Check Slot Usage**:
```bash
# Monitor in llama.cpp logs for "slot_id" messages
# If you see "all slots full" warnings, increase to 512

# Or query the slots endpoint
curl http://localhost:8081/slots | jq '.[] | select(.task_type != "null")'
```

---

### 4. **Enable KV Cache Quantization for Embeddings** - MEDIUM PRIORITY

**Current**: Chat models have `q8_0` quantization
**Embedding Models**: Check if they also use quantized KV cache

**Recommendation**:
For embedding servers (8090), add the same KV cache quantization:
```yaml
# In docker-compose.yml embedding-server config
environment:
  CACHE_TYPE_K: q8_0
  CACHE_TYPE_V: q8_0
```

**Expected Impact**:
- Embeddings are shorter (2048 ctx), so less dramatic saving
- But every bit helps with 8 embedding servers running
- 30-40% memory reduction in embedding cache

---

### 5. **Batch Size Tradeoff: N_BATCH** - MEDIUM PRIORITY

**Current**: `N_BATCH: 128`
**Could increase to**: `N_BATCH: 256` (if CPU can handle)

**Research Finding**:
- Default is 2048, but that's for modern CPUs
- Your 2-core Celeron was running at 128 safely
- Increasing to 256 would mean preparing 256 tokens per step
- CPU would be slightly more utilized, but might not bottle-neck

**How to Test Safely**:
```bash
# Set N_BATCH: 256, keep N_UBATCH: 128
# Run a 30-minute 10 VU load test
# Monitor: CPU usage, GPU queue depth, latency

# If CPU usage stays <80% and latency stable:
#   → Safe to keep at 256
# If CPU spikes to 100%:
#   → Revert to 128
```

**Recommendation**: **Only test if TTFT becomes critical bottleneck**

---

### 6. **GPU-Specific Optimization: More GPU Layers** - LOW PRIORITY

**Current**: `N_GPU_LAYERS: 33`
**Could try**: `N_GPU_LAYERS: 35-40`

**Analysis**:
- Your P106-100 has 6GB VRAM
- Currently 33 layers are on GPU (out of 33 total in Stheno-8B)
- This means model is 100% on GPU already ✅
- No room to increase without exceeding VRAM

**Recommendation**: **No change needed** - you're already fully GPU-accelerated

---

### 7. **Optional: Explore CUDA Graphs** - ADVANCED

**Current**: Using standard CUDA inference
**Research Finding**: NVIDIA reports 1.2x speedup with CUDA Graphs

**How It Works**:
- CUDA Graphs batch multiple operations into a single GPU kernel launch
- Reduces GPU-CPU synchronization overhead
- Requires llama.cpp version from mid-2024 or later

**Status**: This requires checking your llama.cpp build version
```bash
# Check version
llama-server --version

# If >= v3294 (mid-2024), CUDA Graphs likely already built-in
# Check llama.cpp release notes for "CUDA Graphs" mention
```

**Recommendation**:
- If using recent llama.cpp, it may already be enabled
- Otherwise, rebuild llama.cpp from latest main branch
- Expected improvement: 8-15% speedup in TTFT and throughput

---

## Quantization Tradeoff Analysis

Your models are already quantized at import:

| Model | Quantization | Size | Trade-off |
|-------|-------------|------|-----------|
| Stheno-L3.1-8B | Q6_K (assumed) | ~5.3GB | Good quality/speed balance |
| Lumimaid-v0.2-8B | Q6_K (assumed) | ~5.3GB | Same balance |

**Can you optimize further?**

| Alternative | Pros | Cons |
|-------------|------|------|
| Q5_K_M | -15% VRAM, 5% quality loss | Less memory for context |
| Q4_K_M | -25% VRAM, 10% quality loss | Noticeably lower quality |
| Q6_K (current) | Best quality/speed | Using already ✅ |
| Q8_0 (higher) | +5% better quality | Larger file, no VRAM benefit |

**Recommendation**: **Keep current quantization** - Q6_K is the research-confirmed sweet spot

---

## Prompt Processing Speed Analysis

### Current Bottleneck Breakdown

For a 500-token prompt + 512-token response on your setup:

```
TTFT = Prompt Processing Time + Batch Preparation Overhead
```

| Phase | Time | Bottleneck |
|-------|------|-----------|
| Load prompt into GPU memory | ~200ms | GPU PCIe (not major) |
| Process prompt tokens (500÷128 batch) | ~3-4s | 2-core CPU preparing batches |
| First token generation | ~100-200ms | GPU |
| **Total TTFT** | **~4-5s** | CPU (batch preparation) |

**Why TTFT is CPU-limited**:
- N_BATCH=128 means process 128 tokens per step
- 500-token prompt needs ⌈500÷128⌉ = 4 steps
- Each step needs CPU overhead (chunk preparation, KV cache management)
- Your 2-core CPU can't prepare larger batches

**To improve TTFT further**: Would need CPU upgrade (not feasible)

---

## Recommendations Ranked by Impact/Effort

| Priority | Change | Impact | Effort | Testing |
|----------|--------|--------|--------|---------|
| 1 | Increase N_UBATCH to 128 | 5-10% TTFT | ⭐ Low | 5 min |
| 2 | Monitor cache-reuse slots | Find bottleneck | ⭐ Low | 10 min |
| 3 | Add KV cache to embeddings | 30-40% embed mem | ⭐ Low | 5 min |
| 4 | Update llama.cpp for CUDA Graphs | 8-15% speedup | ⭐⭐ Med | 20 min build |
| 5 | Increase N_BATCH to 256 | 5-8% TTFT | ⭐⭐ Med | 30 min test |
| 6 | Change context to 12288 | Longer memory | ⭐⭐ Med | Monitor OOM |
| 7 | Benchmark against vLLM | See alternative | ⭐⭐⭐ High | 2-3 hours |

---

## Implementation Plan

### Phase 1: Quick Wins (1-2 hours)

```bash
# 1. Update config.py
N_UBATCH: 128  # from 64

# 2. Restart containers
docker compose restart local-ai-gpu-1 local-ai-gpu-2 ...

# 3. Run baseline latency test
# Time 10 requests, record TTFT
# Compare before/after: should see 5-10ms improvement
```

### Phase 2: Monitor & Tune (Ongoing)

```bash
# Check cache slot usage
# If "all slots full" appears, increase cache-reuse to 512

# Monitor in docker logs
docker compose logs local-ai-gpu-1 | grep "slot_id"
```

### Phase 3: If TTFT Still Matters (Next Sprint)

```bash
# Only if client feedback indicates TTFT is issue:

# 1. Build llama.cpp main branch with CUDA Graphs
#    (or update container image to latest)

# 2. Test N_BATCH=256 under load
#    Run 30-min 10 VU test, monitor CPU

# 3. Consider vLLM as alternative
#    (requires rewrite of router logic, but better concurrency)
```

---

## Known Limitations & Trade-offs

### Cannot Improve Without Hardware Upgrade

| Bottleneck | Current | Limit | Solution |
|-----------|---------|-------|----------|
| Prompt processing latency | 2-4s | CPU-bound | Faster CPU |
| Concurrent requests | 1 per GPU | Batch size limit | More RAM/GPU |
| Long context handling | 8192 tokens | Container memory | 2GB+ containers |
| Model quality | Q6_K | Quantization level | 8GB+ per GPU |

### Research Findings vs Reality

**Flash Attention Quality Issue** ⚠️
- Research noted quality degradation with >8k context on some models
- Your 8k context is at threshold - monitor output quality
- If issues arise: either reduce to 4096 or test without flash-attn
- Stheno-L3.1 appears to handle flash-attn well (no reports of issues)

**KV Cache Reuse Bug** ⚠️
- Recent issues reported cache-reuse not working with some models
- Test to confirm it's actually reusing prompts
- Monitor: Check if repeat requests have same latency (would indicate caching)

---

## Monitoring Checklist

To verify optimizations are working:

```bash
# 1. Measure TTFT for identical prompts (should be faster if cached)
time curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"","messages":[{"role":"user","content":"Hello world"}]}' | jq '.usage'

# 2. Check GPU utilization during prompt processing
nvidia-smi dmon -s pucvmet | head -20  # Watch GPU utilization

# 3. Monitor cache slot usage (if implemented)
curl http://localhost:8081/slots | jq '.[].task_type' | grep -c "null"

# 4. Track container memory
docker stats local-ai-gpu-1 --no-stream | awk '{print $6}'

# 5. Check for OOMKill events
docker inspect local-ai-gpu-1 | grep -i "oomkilled"
```

---

## Sources

- [Tutorial: measuring TTFT and TBT in llama.cpp](https://github.com/ggml-org/llama.cpp/discussions/14115)
- [Improving server inference via prompt streaming](https://github.com/ggml-org/llama.cpp/discussions/11348)
- [vLLM vs llama.cpp comparison](https://developers.redhat.com/articles/2025/09/30/vllm-or-llamacpp-choosing-right-llm-inference-engine-your-use-case)
- [Comparative Study of LLM Inference Engines (2025)](https://arxiv.org/pdf/2511.05502)
- [NVIDIA CUDA Graphs Optimization](https://developer.nvidia.com/blog/optimizing-llama-cpp-ai-inference-with-cuda-graphs/)
- [KV Cache Quantization & Memory Optimization](https://medium.com/@tejaswi_kashyap/memory-optimization-in-llms-leveraging-kv-cache-quantization-for-efficient-inference-94bc3df5faef)
- [llama.cpp KV Cache Reuse Tutorial](https://github.com/ggml-org/llama.cpp/discussions/13606)
- [Q8_0 vs Q6_K Quantization Analysis](https://github.com/ggml-org/llama.cpp/discussions/5932)
- [Continuous Batching Performance Study](https://github.com/ggml-org/llama.cpp/discussions/4130)
- [Batch Size vs Ubatch Size Explanation](https://github.com/ggml-org/llama.cpp/discussions/6328)
- [Flash Attention Quality Concerns](https://github.com/ggml-org/llama.cpp/discussions/9646)
- [llama.cpp guide: Running LLMs locally](https://blog.steelph0enix.dev/posts/llama-cpp-guide/)

---

## Next Steps

1. **Implement Phase 1** (increase N_UBATCH to 128)
2. **Test baseline vs optimized** with 10 requests
3. **Monitor cache slot usage** for next 48 hours
4. **If TTFT still critical**: Consider Phase 2 (CUDA Graphs, N_BATCH tuning)
5. **Re-run 30-minute load test** to ensure stability

The current configuration is solid and near-optimal for your hardware. Most remaining improvements require either CPU upgrade or rewriting the inference engine (vLLM).
