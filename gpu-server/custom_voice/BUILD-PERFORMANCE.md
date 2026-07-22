# Custom voice build performance evidence

This file contains content-free operational evidence only. No transcripts, audio,
paths, credentials, preview identifiers, or input-derived hashes are recorded.

## 2026-07-20 P104-100 checkpoint rollout

The pinned worker image was built on Pea and passed launcher preflight. A three-step,
three-fitness-text authorized benchmark compared exhaustive sequential scoring with
an interrupted/resumed early-rejection run.

| Evidence | Exhaustive | Optimized resume |
|---|---:|---:|
| Final score | 30.707600 | 30.707600 |
| Target similarity | 0.646665 | 0.646665 |
| Improvements | 0 | 0 |
| Search steps | 3 | 3 |
| Fitness utterances in final process | 12 | 3 |
| Final-process candidate-loop duration | 23.201 s | 6.758 s |
| Peak observed worker GPU memory | 3,634 MiB | 3,636 MiB |
| Minimum observed free GPU memory | 4,558 MiB | 4,556 MiB |
| Resume count | 0 | 1 |

The optimized job was stopped after checkpoint sequence 2 and resumed for its final
step. Its artifact digest and all final selection values exactly matched the
exhaustive run. Cumulative active time correctly included both processes; measured
live-service waits remained excluded from that budget.

The GPU utilization exporter reported zero during the interval and `nvidia-smi`
reported a device-handle error for the second visible GPU, so duty-cycle evidence is
not accepted as valid. Task 1.1 remains open until that exporter is repaired and an
exhaustive baseline is repeated.

Prepared-input reuse is disabled because the pinned Kokoro API has no proven stable
prepared-input boundary. Within-candidate batching is also disabled: the generic
conformance gate is implemented, but no supported Kokoro/Resemblyzer batch probe can
be benchmarked until such an API is selected. The strict profile keeps adaptive
stopping disabled.

An authenticated stable `custom-dima` synthesis returned HTTP 200, 99,050 RIFF
bytes in 1.755 seconds after the benchmark. Provider discovery contained
`cv_custom_dima`; HeartCode's dynamic catalog reported `custom-dima` available, and
focused catalog/preference/preview tests passed.

## Rollback and legacy handling

- Select `exhaustive_sequential` in the digest-bound plan to disable early rejection.
- Keep `batch_backend_enabled` false and `plateau_policy` null for the production
  profile until independent benchmarks pass.
- A `checkpoint.pt` best-tensor file is legacy evidence, not resumable state. Preserve
  it for diagnosis and start a clean job/output directory.
- A v2 checkpoint mismatch or integrity failure must fail closed; never delete it and
  silently restart in the occupied output directory.
