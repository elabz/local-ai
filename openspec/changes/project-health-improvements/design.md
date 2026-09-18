## Context

The inference stack is stable as of 2026-09-18. The problems are in the records around it:

- `openspec/specs/` holds 7 capabilities. 14 changes are still open, and their deltas describe 10 more (`capacity-manifest`, `ci-validation`, `cd-deploy`, `visual-embeddings`, and others) that never reached the main specs. An agent reading the specs sees an incomplete, partly aspirational picture.
- Some open changes are finished, some are half done, some were overtaken by later work, and one (`prevent-load-induced-gpu-restarts`) is a stale pre-implementation copy of a change archived on 2026-08-21 with 17/17 tasks. It came back with the 2026-09-04 live-checkout merge.
- Checkboxes are not proof. `enforce-capacity-guardrails` 4.2 ("verify alert delivery") is checked, but PEA's Prometheus has no Alertmanager (verified 2026-09-17).
- The CI workflow runs lint and config checks but not pytest. `deploy.yml` has never run, and no self-hosted runner is registered (`gh api .../actions/runners` returns none).

## Goals / Non-Goals

**Goals:**
- Every open change ends in an explicit disposition, and the main specs describe what is actually deployed.
- The unit tests pass and gate CI.
- A firing alert reaches a human.
- CLAUDE.md topology cannot drift from `models.yaml` again.

**Non-Goals:**
- Finishing the leftover work of stalled changes. Triage records what was done and drops or defers the rest; it does not resume it.
- Changing the model, routing, compose, or anything else on the inference path. The one production touch is the Alertmanager add-on.
- Picking the aligned SFW model. That belongs to `serve-aligned-sfw-chat-model`.

## Decisions

### D1. Triage is docs-only and read-only toward production

A triage commit may touch only `openspec/` (plus CLAUDE.md where a disposition corrects it). Checking a change against reality uses read-only probes only: `git log`, the manifest and compose files, `ssh pea 'cd /home/boss/local-ai/gpu-server && docker compose ps'`, LiteLLM `/model/info`, `/health`, and Prometheus queries. No `compose up`, restart, deploy or config render on a host. If a check shows a deployed state that differs from `main`, record the gap as a follow-up instead of fixing it in triage.

*Why:* archiving is pure text, so separating it from operations means triage cannot break anything that is running. *Alternative rejected:* finishing each change's remaining tasks. That is exactly the "dredging up May work" risk.

### D2. The spec follows reality, not the delta

For each change, compare every requirement in its delta against the live system before archiving:
- **Deployed as written:** keep it.
- **Deployed differently:** edit the delta to match what runs, with a one-line `<!-- reconciled 2026-09-xx: ... -->` note.
- **Never built, or superseded:** delete it from the delta and list it in the change's `tasks.md` under a closing note ("Dropped at triage: …").

Then archive. The main specs gain only true statements.

### D3. Rebase deltas onto the current main spec before archiving

`openspec archive` applies a delta against today's main spec, not the one it was written against. An old `MODIFIED` block would **replace** newer text with May-era text. Two open deltas use `MODIFIED`:
- `evaluate-modern-chat-model-canaries` → `gpu-rebalance`
- `diagnose-dima-voice-candidates` → `custom-kokoro-voice-builds`

Before archiving either, re-copy the current requirement from `openspec/specs/` and re-apply only the intended edit. For every archive, diff `openspec/specs/` before and after and read the diff. Archive in **chronological order of each change's last real activity**, so later truths land last.

### D4. Five dispositions

| Disposition | When | Command |
|---|---|---|
| **Archive** | all tasks done and verified live | `openspec archive <c> -y` |
| **Archive-partial** | the core shipped, the leftovers are optional, blocked or obsolete | trim the delta (D2), add the closing note, `openspec archive <c> -y` |
| **Archive-no-specs** | a one-off operation or an abandoned direction with no lasting behavior | closing note, `openspec archive <c> --skip-specs -y` |
| **Delete** | a duplicate of an archived change | `git rm -r` (history keeps it) |
| **Keep** | active and still wanted | leave open, re-scope the tasks if needed |

Leftover work worth keeping moves into a **new, small, dated change** rather than keeping a months-old change open. That way it is re-proposed against the current system instead of against May's.

### D5. Proposed dispositions (confirm during triage)

| Change | Tasks | Proposed | Notes |
|---|---|---|---|
| `prevent-load-induced-gpu-restarts` | 0/17 | **Delete** | duplicate of the archived `2026-08-21-…` (17/17) |
| `evaluate-modern-chat-model-canaries` | 24/24 | Archive | rebase the `gpu-rebalance` MODIFIED (D3) |
| `enforce-capacity-guardrails` | 8/8 | Archive after 4.2 | **uncheck 4.2**; it closes when section 3 of this change proves delivery |
| `serve-dinov2-visual-embed` | 12/13 | Archive | remaining 1.2 is optional |
| `restore-nsfw-chat-capacity` | 8/9 | Archive-partial | 2.4 (SFW canary on GPU 6) was overtaken by the capacity work; GPU 6 is back on NSFW |
| `fix-cicd-pipeline` | 21/23 | Archive-partial | archive `ci-validation` and `model-manifest` (live); drop the `cd-deploy` delta, since `deploy.yml` has never run and there is no runner. Move the runner and Environment setup to a follow-up if still wanted |
| `serve-photo-embeddings` + `finalize-vision-embed-rollout` | 8/13, 7/12 | Archive-partial, both | the model is deployed and in use; the offline eval (the leftover in both) becomes an optional future change. Drop "provisional pending eval" wording from CLAUDE.md, or keep it deliberately |
| `deploy-heartcode-speech-runtime` | 10/18 | Archive-partial | the runtime is live; the observability and alert leftovers (3.2–4.3) depend on alert delivery, so re-propose them after section 3 |
| `optimize-custom-voice-build-performance` | 35/37 | Archive-partial | leftovers are benchmarks |
| `rerun-dima-v2-custom-voice-build` | 33/40 | **Ask owner** | an operation, not a capability. If Dima v2 qualified, Archive; if not, Archive-no-specs with the outcome recorded |
| `diagnose-dima-voice-candidates` | 6/30 | **Ask owner** | likely Archive-no-specs (abandoned diagnostic direction); rebase the MODIFIED if any of it is kept |
| `scale-chat-concurrency` | 0/8 | Keep | proposed 2026-09-16, current |
| `serve-aligned-sfw-chat-model` | 0/27 | Keep, **top priority** | the SFW route no longer refuses adult content |
| `project-health-improvements` | — | Keep | this change |

### D6. Unit tests: fix first, then gate

Pin test dependencies in `gpu-server/requirements-test.txt`. The runtime pins (`pydantic==2.5.3`) and the unpinned `fastapi` let a clean install pull versions that break the embed-route tests. Fix the tests before adding the job, so it lands green. Custom-voice tests that need `numpy` go in the test requirements, or are skipped with `pytest.importorskip` if they need GPU-only stacks. Integration tests stay out of CI because they need the LAN.

### D7. Alertmanager lives on PEA, next to the Prometheus that evaluates the rules

Add an `alertmanager` service to the PEA monitoring compose, with a Slack receiver that reads the existing webhook from the gitignored env, and add an `alerting:` block to `gpu-server/configs/prometheus.yml`. *Alternative rejected:* reviving the dormant `monitoring/` stack on Prod. It is a second Prometheus that scrapes nothing live today. Once PEA's is live, retire or document `monitoring/prometheus/alerts.yml` so there is one rules source.

### D8. CLAUDE.md tables are generated

`render-config.py` replaces the text between `<!-- BEGIN GENERATED: models -->` and `<!-- END GENERATED: models -->` (and the same for `ports`), and `--check` compares that block too. Prose outside the markers stays hand-written.

## Risks / Trade-offs

- **[An archived delta overwrites newer spec text]** → D3 rebase, plus reading the before/after spec diff on every archive.
- **[Dropping requirements loses an intended design]** → the dropped items stay in the archived change's tasks.md and in git history, and anything still wanted is re-proposed as a new change.
- **[Adding Alertmanager on PEA competes with the 2-core Celeron]** → Alertmanager is idle nearly all the time. Give it a 64m memory limit and no GPU.
- **[Existing alert rules fire noisily once delivery works]** → start with the Slack receiver and a `group_interval`/`repeat_interval` of hours; tune or silence the noisy rules in the first week.
- **[The test job blocks unrelated PRs while it is flaky]** → land it only after a green run on `main`.
