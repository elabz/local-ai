# GPU Server Reliability Improvements

## Overview

The GPU server experienced container crashes during load testing. This document outlines approaches to increase reliability while maintaining stable performance at 30 rpm (3 rpm per GPU average).

## Current Status

**Verified Safe Operating Point**: 30 rpm from 10 users (0.5 req/sec total)
- 8 NVIDIA P106-100 GPUs (6GB each)
- Prompt size: ~500 tokens (max)
- Container memory limits: 1536m per chat, 512m per embed
- Health check interval: 15 seconds
- Max parallel requests: 12 (LiteLLM)

## Approaches to Increase Reliability

### 1. **Watchdog Service Improvements** ✅ IMPLEMENTED

**Changes Made**:
- Reduced POLL_INTERVAL from 30s to 5s for faster detection
- Added check for stopped containers (not just VRAM check)
- Faster health check timeout (3s instead of 5s)
- Prioritized detection order: stopped containers → VRAM → health endpoints

**Impact**: Containers restart within 5-10 seconds of failure detection

**Configuration**:
```bash
# In gpu-watchdog.service
Environment="POLL_INTERVAL=5"
Environment="HEALTH_CHECK_TIMEOUT=3"
```

---

### 2. **Memory Management & Limits** ✅ CONFIGURED

**Current Settings**:
```yaml
# Chat containers (8 GPUs)
mem_limit: 1536m        # Hard limit
memswap_limit: 2048m    # Allow limited swap

# Embedding containers (8 GPUs)
mem_limit: 512m
memswap_limit: 768m
```

**Why This Works**:
- 8 chat × 1.5GB = 12GB (+ overhead ≈ 14GB of 16GB)
- Prevents memory exhaustion cascading failures
- Hard limit forces fast failure instead of OOMKill hangs
- Swap allows graceful degradation under temporary spikes

**Note**: If containers OOMKill, watchdog detects via VRAM check and restarts within 5 seconds

---

### 3. **LiteLLM Rate Limiting & Concurrency** ✅ OPTIMIZED FOR 30 RPM

**Request Flow**:
```
Frontend → Backend → LiteLLM Proxy → GPU Servers
           Rate limit at                ↓
           Backend (via task queue)   Health check
                                      Load balance
```

**LiteLLM Configuration for 30 rpm**:
```yaml
general_settings:
  max_parallel_requests: 8        # One per GPU - prevent queue buildup
  global_max_parallel_requests: 12 # Small buffer (30% headroom)
  request_timeout: 90              # Fail fast on slow responses

router_settings:
  routing_strategy: "least-busy"  # Distribute by actual load
  health_check_interval: 15       # Detect failures quickly
  allowed_fails: 2                # Mark unhealthy after 2 failures
  cooldown_time: 60               # Brief lockout before retry
  num_retries: 2                  # Limited retries to fail fast
  retry_after: 3                  # Quick retry
```

**Capacity Planning**:
- 8 GPUs × 3-4 rpm per GPU = 24-32 rpm capacity
- Safety margin: 30 rpm is ~90% of capacity
- No queueing at LiteLLM level (all requests served directly)

---

### 4. **Health Checks & Monitoring**

**Docker Health Checks** (per-container):
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
  interval: 30s        # Detects slow/hanging servers
  timeout: 10s
  retries: 3           # Allows brief latency spikes
  start_period: 120s   # Model load time
```

**LiteLLM Health Checks** (proxy-level):
```yaml
enable_health_check: true
health_check_interval: 15s  # More frequent than Docker checks
```

**Watchdog Service** (system-level):
```bash
./gpu-watchdog.sh --daemon  # Checks every 5 seconds
```

**Three-Layer Detection**:
1. Container crashes → Watchdog restarts (5s)
2. Slow responses → LiteLLM marks unhealthy (15s)
3. Hanging containers → Docker health check (30s)

---

### 5. **Request Timeout Management**

**Timeout Chain** (request fails fastest at bottleneck):
```
Frontend (30s) ← Backend (90s) ← LiteLLM (90s) ← GPU Server (no timeout, inherits LiteLLM)
```

**Behavior**:
- If GPU server takes >90s: LiteLLM fails request, marks server unhealthy
- Triggers retry to different GPU (up to 2 retries)
- Failing GPU is skipped for 60 seconds (cooldown_time)
- Watchdog may restart it in parallel

---

### 6. **Request Prioritization & Backpressure**

**Backend Task Queue Strategy**:
```python
# In backend, use Celery priority queue
@celery_app.task(bind=True, priority=5)
async def generate_chat_response(self, ...):
    # Long-running chat task
    pass

@celery_app.task(bind=True, priority=10)  # Higher priority
async def generate_embedding(self, ...):
    # Fast embedding task (usually <1s)
    pass
```

**Queuing Prevents**:
- LiteLLM overload (tasks wait in backend queue)
- VRAM exhaustion (gradual request flow)
- Watchdog false restarts (stable GPU utilization)

---

### 7. **Graceful Degradation & Circuit Breaking**

**LiteLLM Least-Busy Routing**:
- Monitors actual queue depth per GPU
- Routes new requests to least-loaded GPU
- Automatically avoids overloaded servers

**Fallback Behavior**:
```
Request to GPU 3 (overloaded)
  ↓ (times out)
Retry 1 → GPU 5 (healthy)
  ↓ (succeeds)
Response to client
```

**When All GPUs Fail**:
```
LiteLLM returns 503 Service Unavailable
Backend retries task exponentially: 5s, 10s, 20s, ...
Watchdog attempts restart in parallel
System recovers within 60s (cooldown_time)
```

---

### 8. **Monitoring & Metrics**

**Key Metrics to Monitor**:

| Metric | Target | Alert If |
|--------|--------|----------|
| GPU VRAM Usage | <50% | >70% (sign of large prompts) |
| Inference Latency (p50) | 5-8s | >30s |
| Inference Latency (p95) | 10-15s | >45s |
| LiteLLM Queue Depth | 0-2 | >5 (system overloaded) |
| Container Restart Rate | <1/hour | >5/hour (instability) |
| Health Check Failures | 0 | >0 (GPU down) |

**Tools**:
- Prometheus: Scrapes LiteLLM metrics, node-exporter, DCGM exporter
- Grafana: Visualize trends and set up dashboards
- Langfuse: Track per-request latency, errors, and model usage

**Prometheus Config** (already in `configs/prometheus.yml`):
```yaml
scrape_configs:
  - job_name: 'litellm'
    static_configs:
      - targets: ['localhost:4000']
    metrics_path: '/metrics'
```

---

### 9. **Safe Scaling Beyond 30 rpm**

**Path to 60 rpm** (not yet tested):

1. **Increase max_parallel_requests**: 12 → 16
   - Each GPU handles 2 concurrent requests
   - Requires: Queue management at backend to prevent thundering herd

2. **Increase container memory**: 1536m → 2048m
   - Risk: Less headroom, higher OOM crash risk
   - Mitigation: Implement prompt truncation at backend (max 10k tokens context)

3. **Add request queuing at LiteLLM**:
   - Use Redis for distributed queuing
   - Set `max_queue_size: 20` to prevent resource exhaustion

4. **Implement model caching**:
   - Keep models in VRAM longer
   - Reduce load spike from model-load operations

5. **Use faster models**:
   - Current: Stheno-L3.1-8B (good quality, ~8-10s per 200 token output)
   - Alternative: Mistral-7B (faster, ~5-7s per 200 token output)

---

### 10. **Failure Recovery Automation**

**Systemd Service Auto-Restart**:
```ini
[Service]
Restart=always
RestartSec=10
```

**Docker Restart Policy**:
```yaml
services:
  gpu-server-1:
    restart: unless-stopped  # Restarts unless explicitly stopped
```

**LiteLLM Retry Logic**:
- Automatic retries on timeout (2 retries to different GPUs)
- Exponential backoff before cooldown
- Graceful 503 after all retries exhausted

---

## Implementation Checklist

- [x] Reduce watchdog POLL_INTERVAL to 5 seconds
- [x] Add stopped container detection to watchdog
- [x] Optimize LiteLLM concurrency settings for 30 rpm
- [x] Document timeout chain and health checks
- [ ] Set up Prometheus alerts for key metrics
- [ ] Configure Grafana dashboards
- [ ] Implement backend task queue prioritization
- [ ] Load test at 30 rpm for 30 minutes with monitoring
- [ ] Document scaling path to 60+ rpm

---

## Quick Troubleshooting

| Issue | Symptom | Solution |
|-------|---------|----------|
| Container crashes | VRAM = 0, restart rate >5/hour | Check prompt size, reduce N_CTX or N_BATCH |
| Slow inference | Latency p95 >45s | Check GPU VRAM, reduce concurrent requests |
| Request queuing | LiteLLM queue_depth >5 | Reduce backend request rate, add more GPUs |
| One GPU unhealthy | One GPU not receiving requests | Wait 60s (cooldown), or restart: `docker restart local-ai-gpu-N` |
| Health check failures | All GPU health checks failing | Check network connectivity, model load time >120s |

---

## References

- **Load Test Results**: See `infrastructure/load-tests/` directory
- **Watchdog Logs**: `/var/log/gpu-watchdog.log` on ASH server
- **Container Logs**: `docker compose logs -f local-ai-gpu-1`
- **Langfuse Dashboard**: http://192.168.0.145:3002 (ASH server)
- **Prometheus**: http://192.168.0.145:9090 (ASH server)
