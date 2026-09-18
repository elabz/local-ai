# Final canary comparison — 2026-09-04

This report closes tasks 4.3, 4.4 (machine-scorable part), 4.5, 5.1, 5.2, and
5.3 of `evaluate-modern-chat-model-canaries`. It supersedes the gate columns
of the 2026-08-25 and 2026-08-29 evidence where they disagree; provenance and
context matrices recorded there remain valid.

## Outcome in one paragraph

No SFW candidate passes every selection gate, so the `site-2017` failed-call
mop-up (task 5.2) is **not triggered** and production aliases stay unchanged.
Gemma 3 12B Q4_K_M is mechanically qualified at 16K and is the first model in
this benchmark's history to return 100% valid output and 100% high-risk recall
with zero identifier leaks and zero invented evidence, but its actionable
precision (57.9%) and recall (61.1%) fail the frozen benchmark's 90% precision
gate. Gemma 3 4B Q8_0 fails validity (90.0% of labeled outputs, 80/100 threads
exported). On the NSFW side, Luchador Q5_K_M remains the only 2026 challenger
that passes every mechanical and safety gate; its qualitative gate is a blind
prose packet that still needs a human score. A separate, unplanned finding is
that **Pea's GPU 5 corrupts generation whenever a process holds more than
about 7.6 GiB of the card**, which invalidated the SFW canary slot for 12B-class
occupants and explains the 2026-08-25 "grammar/control-token" failure.

## SFW: frozen `site-2017` benchmark (task 4.3)

Both mechanically qualified Gemma 3 configurations processed the frozen
100-thread manifest (`benchmark-manifest-2026-08-11.json`, prompt/schema
contract `tool-demand-extractor-1.3.0`, 2,048-token output ceiling,
24,000-character chunks) and were scored against the 30 GPT-5.6-Sol reference
labels with the archived `llm_tool_demand_benchmark.py score` command. Runs
were issued from the operator workstation directly to the canary port, not
through LiteLLM, so proxy retries and cooldowns cannot mask model behaviour.
Prompt-constrained JSON mode was used for the scored run because it is the
mode the 2026-08-25 evidence qualified; native `json_schema` was also probed
(below).

| Metric (gate) | Gemma 3 12B Q4_K_M, 16K, GPU 6 | Gemma 3 4B Q8_0, 16K, GPU 5 | Stheno 8B v1.2 (2026-08-12) | Gemini 2.5 Flash v1.2 (2026-08-12) |
|---|---:|---:|---:|---:|
| Valid labeled outputs (≥98%) | **100.0%** | 90.0% | 86.7% | 100% |
| Actionable precision (≥90%) | 57.9% | 59.3% | 66.7% | 64.0% |
| Actionable recall (reported) | 61.1% | 88.9% | 88.9% | 88.9% |
| High-risk flag recall (100%) | **100.0%** | 82.4% | 73.3% | 52.9% |
| Identifier leaks / invented evidence (0 / 0) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| Threads exported | **100/100** | 80/100 | 80/100 | 100/100 |
| Schema-valid calls | **125/125** | 94/125 | 92/125 | 125/125 |
| Passes unattended gates | no | no | no | no |

Validity split from the ledgers (`site2017-run-summary-*.json`):

| Run | Native pure JSON on first reply | Cleanup-assisted (fence stripping only) | Repair-assisted (one bounded retry) | Irrecoverable | Transport failures |
|---|---:|---:|---:|---:|---:|
| 12B | 0 | 125 | 0 | 0 | 0 |
| 4B | 0 | 66 | 28 | 31 | 0 |

Both Gemma models wrap every prompt-mode answer in a Markdown code fence, so
"cleanup-assisted" here means fence removal only; no field was added, coerced,
or inferred. The 4B's 31 irrecoverable calls were 20 closed-enum `stakes`
violations and 11 non-object replies, and its failure rate rose with prompt
size (11 of 16 calls whose summed prompt exceeded 10K tokens failed). One 4B
export row was withheld by the privacy scan. Replaying three failed and three
successful 4B calls on GPU 6 reproduced the same coherent-but-noncompliant
behaviour, so the 4B result is the model's, not GPU 5's.

Latency and throughput on the frozen workload (single slot, Q8 KV, batch
128/64, `--cache-reuse` ignored because llama.cpp disables it for Gemma 3's
sliding-window cache):

| Run | Calls | Mean / median / p95 / max call latency | Prompt tokens (mean / max per call) | Output tokens | Wall time |
|---|---:|---|---|---:|---:|
| 12B | 125 | 57.1 s / 43.9 s / 107.4 s / 195.7 s | 3,118 / 7,194 | 63,178 | 2.0 h |
| 4B | 125 | 49.1 s / 36.2 s / 108.2 s / 209.8 s | 4,791 / 8,357¹ | 111,404 | 1.7 h |

¹ The 4B ledger records 16,713 for one call because a repair retry sums two
prompts; no single request exceeded the 16K context.

The Gemma tokenizer packs the same threads into fewer tokens than Llama 3
(389,752 prompt tokens for the 12B run against 485,989 for Stheno on the same
manifest), so the largest single prompt was 7,194 tokens rather than the
~14K measured for Llama; 16K context still leaves headroom for the 2,048-token
output.

### Native `json_schema` re-check

Four short manifest threads (783 to 1,915 prompt tokens) and the longest single
12B benchmark prompt (6,938 tokens) were re-run with provider-side
`json_schema` on both models. Every call returned a pure JSON object with no
grammar error on either GPU 6 (12B) or GPU 5 (4B at 4.3 GiB). The 2026-08-25
failure "empty grammar stack after a Gemma unused/control token" therefore did
not reproduce on healthy hardware and is now attributed to the GPU 5 fault
below. Native mode is viable for a future Gemma run; prompt mode remains the
scored configuration for this change.

### Throughput gates (unchanged)

The 2026-08-25 progressive matrix stands: 12B p10 13.2 t/s at 16K (floor 10),
24K failed to allocate; 4B p10 24.9 t/s at 16K. HeartCode's separate
measurement of 9.4 t/s cold for the 12B at a 2,150-token production prompt is
below its own 12 t/s floor and is recorded in that repository's canary log.

## Pea GPU 5 fault (new finding)

The first 12B benchmark attempt ran on the designated SFW slot, GPU 5
(`GPU-d8525241`), at the qualified 16K configuration. The first call was clean;
the second and third returned multilingual gibberish and a repair reply about
"a series of increasingly absurd sentences". Controlled replays of the same
request on a fresh process gave:

| GPU | Config | VRAM in use | Result |
|---|---|---:|---|
| 5 | 16K, Q8 KV, batch 128/64 | 7,949 MiB | garbage |
| 5 | 8K, Q8 KV, batch 2048/512 | 7,707 MiB | garbage |
| 5 | 4K, f16 KV, batch 128/64 | 7,727 MiB | empty |
| 5 | 4K, Q8 KV, batch 2048/512 | 7,567 MiB | **valid JSON** |
| 5 | Gemma 3 4B, 8K | 4,231 MiB | **valid JSON** |
| 6 | 16K, Q8 KV, batch 128/64 | 7,949 MiB | **valid JSON** |

`nvidia-smi` reports no ECC, retired-page, Xid, or throttle events, and the
card ran at 86–90 °C under load (slowdown threshold 93 °C). The evidence is
crossover only, not a memory test. The 12B benchmark was therefore moved to
GPU 6, the 4B was kept on GPU 5 well below the threshold, and the aborted GPU 5
attempt is preserved as `site2017-run-summary-gemma-3-12b-gpu5-aborted-2026-09-04.json`.
The HeartCode SFW canary slot at 4,096 context measured 7,567 MiB with the
production batch sizes, which is within 150 MiB of the failing region. GPU 5
should be memtested or retired from near-full-card duty in a separate change;
this is recorded in the operator memory and the HeartCode canary log.

## NSFW (task 4.4)

See [the 2026-09-04 rerun](nsfw-gemma4-rerun-2026-09-04.md) for today's rerun
and the blind packet, and [the 2026-08-29 comparison](nsfw-gemma4-comparison-2026-08-29.md)
for the three-candidate context matrix and rejections.

| Candidate | Context / p10 | Direct response | Fixed suite (v1.2.0 today; v1.1.0 on 08-29) | Prohibited refusals | Decision |
|---|---|---|---|---|---|
| Luchador Q5_K_M | 4K 19.4 t/s (today); 8K 18.9; 16K 17.6 | pass; multi-turn tool fails | 0 blanks, 0 leaks, 0 allowed-adult refusals, 14/14 style checks | 2/2 | provisional winner, human prose score pending |
| Gemma4 12B Balanced Q4_K_M | 4K 13.3 t/s | fails (visible thought markers) | reasoning leaked 11/11 | 0/2 | rejected |
| Gemma 4 E4B Aggressive Q6_K_P | 4K 20.0 t/s | pass | no refusals | 0/2 | rejected, lab-only control |
| Lumimaid v0.2 8B (control, GPU 4) | production | production API | 0 blanks, 0 refusals, 14/14 style checks | 2/2 | remains production control |

## Monitoring (task 4.5)

Snapshots at 09:51, 10:31, and 11:57 UTC plus the post-restore snapshot are
in the private monitoring log on Pea. Across the whole window: zero container
restarts, zero OOM kills, zero `dmesg` Xid or OOM lines, all surviving
replicas (`pea-gpu-4`, `pea-embed-4`, `pea-embed-dino-1`, both vision embeds,
`pea-gpu-1..3`) healthy. Host swap grew from 2.2 GiB to 5.3 GiB while swap
in/out stayed at 0–10 KiB/s, so no thrashing. Both canary containers sat at
their 8 GiB cgroup ceiling with ~8 GiB of anonymous memory each on the pinned
build 10566, whereas production workers on build 8027 use ~500 MiB; that
memory profile is a runtime observation to check before any promotion on this
build. GPU 5 and GPU 6 reached 90 °C under sustained load.

## Restoration (task 5.3)

Terminal state after the run, verified healthy with zero restarts: the ad-hoc
4B container removed; `sfw-model-canary` and `nsfw-model-canary` removed;
`pea-embed-5`, `pea-gpu-6`, and `pea-embed-dino-2` started via the documented
`restore-sfw` / `restore-nsfw` commands; canary ports 18085–18087 closed;
GPU 5 at 237 MiB (text embed only), GPU 6 at 7,645 MiB (Lumimaid + DINO).
`pea-gpu-5` was not started: it was already stopped before this window, it is
not routed by LiteLLM, and Lumimaid plus text embed on GPU 5 would land in the
faulty VRAM region. No public alias changed. The HeartCode dropdown entries
that point at 18085/18086 are dead until an operator reloads a canary, which
was also the state before this window.

## Decisions

- **SFW**: no winner. Gemma 3 12B is the strongest candidate on validity,
  safety recall, and privacy, and it refuses in role on the SFW route (HeartCode
  log, 2026-08-29), but it fails the benchmark's precision gate and HeartCode's
  cold-throughput floor. The precision gate has now failed for every model
  tried (Stheno, Gemini, both Gemmas), which suggests the gate or the prompt
  contract, not only the model, needs review before any SFW promotion.
- **Mop-up (5.2)**: not run; condition not met.
- **NSFW**: Luchador stays provisional pending the blind prose scores and the
  product-owner decision on multi-turn tool support.
- **Infrastructure**: GPU 5 needs a memtest or replacement before it hosts any
  near-full-card canary; a permanent embedding relocation remains a separate
  change (task 5.4).
