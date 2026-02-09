# HeartCode Load Tests

Load testing suite using [k6](https://k6.io/) for performance benchmarking.

## Quick Start

```bash
# Terminal 1: Start monitoring
./monitor.sh

# Terminal 2: Run load test
k6 run --vus 50 --duration 2m characters.js

# After test: Analyze results
./analyze.sh
```

## Installation

```bash
# macOS
brew install k6

# Docker
docker pull grafana/k6
```

## Test Files

| File | Description | Target VUs |
|------|-------------|------------|
| `auth.js` | Authentication endpoints (login, refresh, me) | 20-50 |
| `characters.js` | Character browsing and search | 50-100 |
| `chat.js` | Chat streaming via backend (requires JWT) | 10-20 |
| `api-direct.js` | Direct LiteLLM API (requires hc-sk-* key) | 10-20 |
| `stress-all-gpus.js` | Stress test all 8 GPUs with health monitoring | 10-20 |
| `mixed-load.js` | Combined realistic user behavior | 100+ |

## Running Tests

### Quick Test
```bash
# Test character browsing with 50 users for 30 seconds
k6 run --vus 50 --duration 30s characters.js
```

### Full Test Suite
```bash
# Run auth tests
k6 run auth.js

# Run character browsing tests
k6 run characters.js

# Run chat tests (requires authentication)
k6 run -e TEST_TOKEN=<your-jwt-token> chat.js

# Run mixed load test
k6 run -e TEST_TOKEN=<your-jwt-token> mixed-load.js
```

### Against Different Environments
```bash
# Local development
k6 run -e BASE_URL=http://localhost:8000 characters.js

# Staging
k6 run -e BASE_URL=https://staging.heartcode.chat characters.js

# Production (be careful!)
k6 run -e BASE_URL=https://heartcode.chat --vus 10 --duration 10s characters.js
```

### Using Docker
```bash
docker run -i grafana/k6 run - <characters.js
```

## Getting a Test Token

1. Login to HeartCode
2. Open browser DevTools → Network tab
3. Look for any API request with `Authorization: Bearer xxx`
4. Copy the token value

Or use curl:
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"yourpassword"}' \
  | jq -r '.access_token'
```

## Performance Thresholds

| Metric | Target | Critical |
|--------|--------|----------|
| P95 Response Time | < 500ms | < 1000ms |
| P99 Response Time | < 1000ms | < 2000ms |
| Success Rate | > 99% | > 95% |
| Error Rate | < 1% | < 5% |

## Test Scenarios

### Smoke Test (Quick Check)
```bash
k6 run --vus 1 --duration 10s characters.js
```

### Load Test (Normal Load)
```bash
k6 run --vus 50 --duration 5m mixed-load.js
```

### Stress Test (Find Breaking Point)
```bash
k6 run --vus 200 --duration 10m mixed-load.js
```

### Spike Test (Sudden Traffic)
```bash
k6 run --stage 0s:0 --stage 10s:100 --stage 30s:100 --stage 10s:0 mixed-load.js
```

## Output Formats

```bash
# JSON output
k6 run --out json=results.json characters.js

# InfluxDB (for Grafana)
k6 run --out influxdb=http://localhost:8086/k6 characters.js

# CSV
k6 run --out csv=results.csv characters.js
```

## Interpreting Results

```
✓ http_req_duration..............: avg=45.23ms  min=12.1ms med=38.5ms max=245.3ms p(90)=89.2ms p(95)=112.4ms
✓ http_reqs......................: 12450  207.5/s
✓ iterations.....................: 1245   20.75/s
```

- **http_req_duration**: Response time statistics
- **http_reqs**: Total requests and requests/second
- **iterations**: Complete test iterations

## Pre-Test Checklist

1. [ ] Ensure test users exist (for auth tests)
2. [ ] Get valid JWT token (for authenticated tests)
3. [ ] Verify target environment is ready
4. [ ] Clear any rate limit state if needed
5. [ ] Notify team if testing production

## Monitoring During Tests

### monitor.sh

Real-time monitoring script that tracks:
- **GPU metrics**: Temperature, utilization, memory, power draw
- **Backend health**: Response times, error rates
- **Docker stats**: CPU, memory per container
- **Prometheus metrics**: Application-level metrics

```bash
# Full monitoring (requires SSH to GPU server)
./monitor.sh

# Skip GPU monitoring (no SSH needed)
./monitor.sh --no-gpu

# Run on GPU server directly
./monitor.sh --gpu-only

# Custom settings
./monitor.sh --gpu-server 192.168.0.145 --interval 2
```

Environment variables:
- `GPU_SERVER`: GPU server IP (default: 192.168.0.145)
- `GPU_SSH_USER`: SSH username (default: boss)
- `BACKEND_URL`: Backend URL (default: http://localhost:8000)
- `POLL_INTERVAL`: Seconds between samples (default: 5)

### analyze.sh

Post-test analysis script that generates:
- GPU temperature summary and warnings
- Backend health check analysis
- Container resource usage
- Recommendations based on thresholds

```bash
# Analyze most recent test
./analyze.sh

# Analyze specific test
./analyze.sh ./logs/20260109_143000
```

### Critical Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| GPU Temperature | 80°C | 85°C |
| GPU Utilization | - | - |
| Backend Latency | 500ms | 1000ms |
| Error Rate | 1% | 5% |

## Post-Test

1. Run `./analyze.sh` to get summary
2. Review test output for failures
3. Check Grafana dashboards for anomalies
4. Review application logs for errors
5. Document any performance issues found
