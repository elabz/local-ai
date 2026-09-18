# PEA memory snapshot — 2026-09-18 16:05Z (read-only)

Collected after the HeartCode candidate E evaluation finished (15:47Z). Two host OOM kills of `llama-server` so far today (`journalctl -k`).

## Host

| | MiB |
|---|---:|
| RAM total | 32,023 |
| RAM used | 28,856 |
| RAM available | **3,166** (3,901 at 13:40Z) |
| Swap total | 16,383 |
| Swap used | **8,055** |

## Chat workers (`llama-server` VmRSS; cgroup `memory.peak`; limit)

| Container | RSS | Peak | mem_limit | Started |
|---|---:|---:|---:|---|
| pea-gpu-1 | 8,513 | 8,192 (at limit) | 8,192 | 12:43Z today (after OOM) |
| pea-gpu-2 | 1,778 | 5,670 | 8,192 | 12:43Z today, RestartCount 1 |
| pea-gpu-3 | 655 | 621 | 8,192 | 2026-09-16 |
| pea-gpu-4 | 7,490 | 8,192 (at limit) | 8,192 | 2026-09-16 |
| pea-gpu-5 | 7,778 | 7,838 | 8,192 | 2026-09-16 |
| pea-gpu-6 | 96 | 677 | **2,048** | 2026-09-16 |

RSS above the memcg limit on `pea-gpu-1` means the rest of it is in swap (`memswap_limit: 9216m`).

## Everything else (cgroup `memory.peak` / mem_limit, MiB)

| Container | Peak | Limit |
|---|---:|---:|
| pea-embed-4 / -5 | 322 / 122 | 768 / 768 |
| pea-embed-vision-1 / -2 | 1,684 / 1,536 | 2,560 / 2,560 |
| pea-embed-dino-1 / -2 | 1,156 / 1,329 | 3,072 / 3,072 |
| pea-image-1 | **4,096 (at limit)** | 4,096 |
| pea-speech-stt | 1,335 | 4,096 |
| pea-speech-tts | 2,278 | 3,072 |
| monitoring + speech meter/gateway/exporters (7) | ~1,080 total | unlimited |

Non-chat measured peaks sum to about **15.1 GiB**. The non-chat limits sum to **~22.5 GiB** plus 7 unlimited containers. The chat limits sum to **42 GiB**.
