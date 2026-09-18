## 1. Priority record

- [ ] 1.1 Add a priority note to `openspec/changes/serve-aligned-sfw-chat-model/proposal.md`: access-control critical since HeartCode dropped its filter (2026-08-29); ahead of `scale-chat-concurrency`

## 2. Unit tests gate CI

- [ ] 2.1 Add `gpu-server/requirements-test.txt` with pinned fastapi, pydantic, pydantic-settings, httpx, sse-starlette, prometheus-client, orjson, pyyaml, pytest, numpy
- [ ] 2.2 Fix the `metrics` stubs in `tests/test_gpu_health.py` (around lines 173 and 292) so they include `inference_admission_total`; prefer deriving the stub from the real module's names so it can't go stale again
- [ ] 2.3 Fix the embed-route `PydanticUserError` failures (vision/dino/multimodal) under the pinned versions
- [ ] 2.4 Fix or correct `test_old_queue_with_recent_completion_is_progressing_not_stuck` (`idle_probe_failure` vs `busy_probe_timeout`); decide whether the test or the code is wrong
- [ ] 2.5 Make `test_custom_voice_compatibility_runner.py` collect (numpy via test requirements, or `importorskip` for GPU-only deps)
- [ ] 2.6 Confirm a clean-venv run is fully green locally (Python 3.12, not the local 3.11 alpha)
- [ ] 2.7 Add a `unit-tests` job to `.github/workflows/gpu-build.yml` (`pytest gpu-server/tests --ignore=gpu-server/tests/integration`); merge only after a green run

## 3. Alert delivery

- [ ] 3.1 Add an `alertmanager` service (64m memory limit, no GPU) to PEA's monitoring compose, with a Slack receiver reading the existing webhook from gitignored env
- [ ] 3.2 Add an `alerting:` block to `gpu-server/configs/prometheus.yml`; set grouping/repeat intervals to hours
- [ ] 3.3 Deploy on PEA (monitoring containers only); confirm `/api/v1/alertmanagers` lists it as active
- [ ] 3.4 Fire a synthetic alert and record the Slack arrival timestamp here
- [ ] 3.5 Uncheck `enforce-capacity-guardrails` 4.2, then re-check it with the 3.4 evidence
- [ ] 3.6 Retire or mark as not deployed `monitoring/prometheus/alerts.yml` and the dormant Prod monitoring stack so one rules source remains

## 4. Generated topology docs

- [ ] 4.1 Add BEGIN/END GENERATED markers around the Models and Port Layout tables in CLAUDE.md
- [ ] 4.2 Extend `render-config.py` to render both tables from `models.yaml` (including STT/TTS) and include the block in `--check`
- [ ] 4.3 Fix the stale prose outside the markers: image instance count, vision-embed/text-embed deployment counts and ports in Key Configuration and the LiteLLM section
- [ ] 4.4 Add a `test_render_config.py` case: a hand-edited row inside the block fails `--check`

## 5. OpenSpec triage (docs-only — no host changes; see design D1–D5)

- [x] 5.1 Delete `openspec/changes/prevent-load-induced-gpu-restarts/` (duplicate of the archived 2026-08-21 change) _(2026-09-18; a second duplicate, `deploy-heartcode-speech-runtime`, an older 10/18 snapshot of the change archived 2026-07-14 at 18/18, was deleted too)_
- [x] 5.2 Ask the owner for dispositions of `rerun-dima-v2-custom-voice-build` (did v2 qualify?) and `diagnose-dima-voice-candidates` _(2026-09-18: no trial qualified; both abandoned and archived with --skip-specs)_
- [x] 5.3 For each change marked Archive or Archive-partial in D5: verify each delta requirement against the live system with read-only probes, trim or reconcile it (D2), and add the "Dropped at triage" closing note _(2026-09-18: archived serve-dinov2-visual-embed, optimize-custom-voice-build-performance, fix-cicd-pipeline (cd-deploy delta dropped), serve-photo-embeddings, finalize-vision-embed-rollout (rollback requirement dropped), restore-nsfw-chat-capacity, evaluate-modern-chat-model-canaries. `enforce-capacity-guardrails` held open: 4.2 unchecked, since no Alertmanager exists)_
- [x] 5.4 Rebase the two `MODIFIED` deltas (`gpu-rebalance`, `custom-kokoro-voice-builds`) onto the current main spec text (D3) _(gpu-rebalance: base text identical, archived as-is 2026-09-18; custom-kokoro-voice-builds moot, since its change was abandoned with --skip-specs)_
- [x] 5.5 Archive in chronological order of each change's last real activity; after each one, run `git diff openspec/specs/` and read it before continuing
- [ ] 5.6 Open small, dated follow-up changes only for leftovers still wanted (candidates: CD runner and Environment setup, speech observability after section 3, the photo-embedding offline eval)
- [x] 5.8 Correct main-spec requirements that are false today, even when no open change touches them _(2026-09-18: `gpu-rebalance` still required two image servers on GPU 7+8; replaced via the archived `reconcile-specs-with-deployment`. No other count or placement claims in the main specs were wrong.)_
- [ ] 5.9 Follow-up (production config, outside the docs-only triage): remove the `heartcode-chat-gemma-3-12b-canary` (:18085) and `heartcode-chat-gemma4-luchador-nsfw-canary` (:18086) routes from `litellm/config.base.yaml`. No canary container runs, and the file's own rule is "add an entry only when its model is actually loaded". Then re-render and deploy to Prod.
- [x] 5.10 Follow-up: Prod's LiteLLM checkout is at 12d9da1 while `main` is at d1bb71b; confirm the difference is docs/alerts only, or pull _(2026-09-18: `git diff 12d9da1 d1bb71b -- litellm/` is empty; Prod serves the current config)_
- [ ] 5.7 Run `openspec validate --all --strict` and confirm that only Keep changes remain open

## 6. Repo clutter

- [ ] 6.1 Remove `generated-avatar.png` from the repo root (move it if something references it)
- [ ] 6.2 Merge `gpu-server/OPTIMIZATION-ANALYSIS.md`, `gpu-server/OPTIMIZATION-SUMMARY.txt`, `gpu-server/QUICK-OPTIMIZATION-GUIDE.md` and `gpu-server/RELIABILITY-IMPROVEMENTS.md` into one current doc, and delete the rest
- [ ] 6.3 Document the purpose of `docker-compose.gpu-health-canary.yml`, `docker-compose.model-canaries.yml` and `docker-compose.qwen3-nothink.yml` in `gpu-server/README.md`, or remove the ones that are dead
- [ ] 6.4 Decide whether to keep `.codex`, `.gemini`, `.qwen` and `.opencode`; drop the unused ones
