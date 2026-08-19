# Secret-free acceptance evidence

## Baseline — 2026-08-18 EDT

Before implementation, Pea reported the following SFW container restart counts:

| Backend | Restarts | OOM killed |
| --- | ---: | --- |
| pea-gpu-1 | 392 | false |
| pea-gpu-2 | 380 | false |
| pea-gpu-3 | 353 | false |

Recent bounded logs on all three backends showed three consecutive llama.cpp
health timeouts followed by wrapper exit and successful model startup. The
observed startup/recovery interval was approximately 38–47 seconds. Successful
completions occurred between these cycles. This reproduces the pre-change false
restart behavior without retaining request or response content.

Fixed synthetic probes measured idle wrapper health at 0.43–0.58 seconds and a
normal eight-token completion at 7.84 seconds. Busy probes crossed the existing
five-second timeout in the captured watchdog evidence.

The proposal's earlier snapshot was 304/293/265 restarts; the larger counts
above demonstrate continued regression before mitigation.

## Reproducer

`gpu-server/scripts/sustained-chat-concurrency.py` runs fixed synthetic requests
with bounded concurrency for at least five watchdog intervals. Its output is
restricted to aggregate status counts and min/p50/max latency.

## Post-change acceptance

The refined canary completed 17/17 fixed synthetic requests across five
watchdog intervals. Five busy probe timeouts were classified with
`decision=continue`; restart count remained zero.

A hard `SIGKILL` of the canary llama.cpp child caused immediate withdrawal,
one bounded container restart, model readiness recovery, and a successful
HTTP 200 completion afterward.

During the first fleet observation window, the kernel killed the GPU 1
llama.cpp child inside its 2 GiB memory cgroup. Docker still reported
`OOMKilled=false` because the Python wrapper remained alive. Kernel evidence
showed approximately 1.94 GiB anonymous RSS plus 0.33 GiB file RSS. The wrapper
correctly recovered the genuine child exit, but the event produced two proxy
failures. Initial 2.5 GiB and 3 GiB limits remained too low during extended
observation: a single active long-context llama.cpp process reached about
3.06 GiB anonymous RSS plus 0.14 GiB file/shmem. With bounded admission active,
the production working set reached 4.34–5.44 GiB with one request serving and
one queued, eventually pressuring unrelated chat services on the 16 GiB host.
The final deployment matches admission to the one llama.cpp slot per backend,
uses a 6 GiB ceiling with 7 GiB memory+swap, aligns proxy/backend timeouts at
180 seconds, and removes wrapper-internal retries. LiteLLM is the sole bounded
retry/queue boundary. The stale `--mlock` setting was also removed so the
measured 16 GiB RAM/16 GiB swap host can reclaim GPU-offloaded model pages.

An early short-window candidate completed 29/29 fixed synthetic requests but
was rejected after longer observation exposed cgroup and host-memory pressure.
The final configuration was therefore qualified over a full 15-minute restart
window under live production load: restart counts stayed 0/0/0, cgroup OOM
events stayed zero, successful proxy responses increased by 66, peak backend
memory was 3.19 GiB of 5 GiB, host available memory remained above 5 GiB, and
swap free did not decline. In the final five-watchdog-interval steady-state
check, successful responses increased 206 to 212 while unexpected
500/502/504 responses remained exactly 8; controlled saturation returned 503.
A later long-context request briefly reached about 5.3 GiB RSS, demonstrating
that the earlier 5 GiB cgroup ceiling was undersized despite healthy host
headroom. The final 6 GiB/7 GiB bounds were re-qualified after rollout.
Across an extended five-minute post-rollout window, eleven 30-second samples
held restart counts at 0/0/0 with no Docker or kernel OOM event. Peak observed
memory at the end of the window remained below 2.4 GiB per backend. In the
following five-watchdog-interval steady-state check, successful responses rose
from 4416 to 4422, unexpected 500/502/504 responses stayed flat at 44, and the
LiteLLM Prometheus target remained up.

LiteLLM routing acceptance passed 3/3 in a disposable stack: an unavailable
deployment was excluded in favor of a healthy sibling, all-unavailable returned
bounded HTTP 503, and the router used one retry with a 90-second cooldown.
LiteLLM's Prometheus callback is enabled; Pea Prometheus reports the `elm`
scrape target up and evaluates the validated failure alert.

The final focused current-source suite passed 34/34, including availability,
timeout classification, sampling passthrough, and client/no-retry coverage. Python compilation, compose
interpolation, LiteLLM structural validation, Prometheus configuration/rules,
and strict OpenSpec validation passed.

During rollout, GPU slot 2 at PCI `04:00.0` was found under replacement UUID
`GPU-c90a5967-fa44-e206-d2a9-9c9f86b2343f`; compose and the bounded topology
inventory were reconciled to that live slot before restoring the service.
