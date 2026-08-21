## Why

Sustained `heartcode-chat-sfw` traffic reproduced a false-failure loop on PEA. The wrapper probes llama.cpp every 15 seconds with a five-second timeout; while llama.cpp is busy serving inference, the probe can time out even though requests continue to complete successfully. Three consecutive probe failures make the wrapper call `os._exit(1)`, Docker restarts the backend, and LiteLLM returns downstream connection errors as HTTP 500 responses.

This is an established reliability problem rather than an isolated research-run artifact. On 2026-08-18 the three SFW containers had accumulated 304, 293, and 265 restarts. Docker reported `OOMKilled=false`, and successful completions occurred between failed health probes. HeartCode needs liveness behavior that does not turn ordinary model occupancy into an outage.

## What Changes

- Separate child-process liveness from request-serving readiness and load/occupancy.
- Prevent watchdog restarts when llama.cpp is alive but its HTTP health endpoint is temporarily delayed by active inference.
- Add bounded degradation and recovery behavior for genuinely dead or wedged llama.cpp children.
- Improve LiteLLM backend cooldown/failover so requests avoid a restarting deployment and do not repeatedly select it during one retry chain.
- Add restart-rate, probe-reason, backend-state, and proxy-5xx observability suitable for HeartCode operations.
- Validate the behavior under sustained concurrent inference and injected child-process failure.

## Capabilities

### New Capabilities

- `gpu-inference-availability`: PEA chat backends remain available under sustained inference load, recover from genuine child failure, and expose actionable health and restart evidence.

### Modified Capabilities

<!-- None established in openspec/specs/. -->

## Impact

- `gpu-server/server.py` watchdog semantics and `gpu-server/llama_client.py` health probing.
- Docker health configuration for PEA chat backends.
- LiteLLM routing, cooldown, and retry policy for HeartCode chat model groups.
- Prometheus alerts and dashboards for backend restarts and proxy failures.
- No model, prompt, or public API contract change is intended.
