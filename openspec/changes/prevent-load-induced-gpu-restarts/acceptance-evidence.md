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
failures. SFW limits were therefore raised to 2.5 GiB with 4 GiB memory+swap;
the final acceptance window is recorded below.

After the 2.5 GiB SFW limits were active on all three backends, the canary
completed 29/29 fixed synthetic requests across five watchdog intervals.
Restart counts remained 0/0/0. A subsequent 75-second production observation
left the cumulative SFW proxy-failure counter unchanged at 28 and produced no
new llama.cpp cgroup OOM event.

LiteLLM routing acceptance passed 3/3 in a disposable stack: an unavailable
deployment was excluded in favor of a healthy sibling, all-unavailable returned
bounded HTTP 503, and the router used one retry with a 90-second cooldown.
LiteLLM's Prometheus callback is enabled; Pea Prometheus reports the `elm`
scrape target up and evaluates the validated failure alert.

Focused current-source tests passed 31/31. Python compilation, compose
interpolation, LiteLLM structural validation, Prometheus configuration/rules,
and strict OpenSpec validation passed.

During rollout, GPU slot 2 at PCI `04:00.0` was found under replacement UUID
`GPU-c90a5967-fa44-e206-d2a9-9c9f86b2343f`; compose and the bounded topology
inventory were reconciled to that live slot before restoring the service.
