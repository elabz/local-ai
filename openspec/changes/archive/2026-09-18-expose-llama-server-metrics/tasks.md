## 1. Implementation

- [x] 1.1 `server.py` passes `--metrics`; the wrapper relays llama-server's metrics at `/llama/metrics` (`routes.py`, `llama_client.metrics()`); tests in `test_llama_server_command.py` and `test_llama_metrics_relay.py`
- [x] 1.2 `--metrics` on the text-embed anchor, `qwen3-canary`, `docker-compose.model-canaries.yml` and `docker-compose.qwen3-nothink.yml`
- [x] 1.3 Prometheus: add `llama-server` (8 targets) and `dino-embed` (2) jobs; drop `pea-image-2` and `pea-embed-vision-3`

## 2. Rollout (2026-09-18)

- [x] 2.1 Remove stale targets and add DINOv2; restart Prometheus. 18/18 targets up (8a540ad)
- [x] 2.2 Recreate `embedding-server-4/5` and restart `pea-gpu-1..6` one at a time; confirm `--metrics` and `llamacpp:*` series on each (61ff98f) _(18:36–18:48Z: each healthy with `--metrics` and `--cache-ram 1024` and 11 `llamacpp:*` series)_
- [x] 2.3 Restart Prometheus; confirm every target, including the 8 `llama-server` ones, is up _(26/26 up; `count by (job) (llamacpp:prompt_tokens_total)` = 8)_
