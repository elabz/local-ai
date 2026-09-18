## 1. Manifest guard

- [x] 1.1 Add `min_replicas` to the `models.yaml` schema and every model group; enforce in `render-config.py` (`--check` fails below minimum) with unit tests
- [x] 1.2 Document the dated-reason rule for lowering `min_replicas` in CLAUDE.md

## 2. Placement truth

- [x] 2.1 Write `scripts/check-placement.py` (live UUID/process/container mapping vs topology, pins, routing) with fixture-based tests
- [x] 2.2 Add the check to `deploy.yml` after the GPU-host rolling restart and to the availability runbook

## 3. Canary tenancy

- [x] 3.1 Topology schema v2 with optional `canary` per slot; update `gpu_failure_controller.py` to skip displaced services and alert; tests
- [x] 3.2 Record the SFW canary on GPU 6 in `gpu-topology.json` — **not applicable
      as written (2026-09-18)**: the SFW canary was retired from GPU 6 on
      2026-09-16 (`restore-nsfw-chat-capacity`); `pea-sfw-model-canary-gpu6` is
      exited and GPU 6 runs `gpu-server-6` + `dino-embed-2` again, which is what
      `gpu-topology.json` already records. Recording a canary there now would
      stop the failure controller from recovering the card and would report
      false `displaced-running` drift. Closed instead by documenting the
      record-on-displacement / remove-on-retirement procedure in
      [the availability runbook](../../../docs/gpu-inference-availability-runbook.md) (Canary rollout, steps 2 and
      8), so the next canary is recorded while it is real. Schema v2 reader and
      controller behaviour (3.1) are unchanged and tested.

## 4. Alerts

- [x] 4.1 Prometheus rules: cooldown events, 429/503 rate per model group, zero-success-with-traffic per model group over 1 h
- [x] 4.2 Verify alert delivery with a synthetic cooldown on a canary deployment _(UNCHECKED at triage 2026-09-18: PEA Prometheus `/api/v1/alertmanagers` returns no active Alertmanager, so no alert can have been delivered. **Re-checked 2026-09-18** with `project-health-improvements` 3.4 evidence: `pea-alertmanager` is registered as active on PEA's Prometheus, and a synthetic alert (`SyntheticDeliveryTest`, posted 21:30:31Z) was delivered to Slack `#hardware-alerts` by 21:31:42Z, with Slack notifications 2→3 and 0 failures. The rule half remains the promtool synthetic cooldown below. The canary route it names was removed from LiteLLM the same day, so no live canary cooldown is possible.)_
      — **earlier note, superseded by the re-check above:** verified as far as
      it could be before Alertmanager existed. What was verified:
      - `gpu-server/tests/alert_rules_capacity_test.yml` (promtool unit tests,
        `promtool test rules`) drives a synthetic cooldown on the
        `gemma4-luchador-nsfw-canary-gpu6` deployment and asserts
        `LiteLLMDeploymentCooledDown` fires with the right labels/annotations
        while `LiteLLMCooldownOnBusy` stays silent, plus firing cases for all
        three new rules and a healthy-traffic negative control. The suite was
        mutation-checked (a wrong expected annotation fails it).
      - Label semantics checked against live metrics before asserting:
        `litellm_deployment_cooled_down_total` carries the model group in
        `litellm_model_name`, `litellm_deployment_failure_responses_total`
        carries it in `requested_model` (its `litellm_model_name` is the GGUF
        file), `litellm_proxy_total_requests_metric_total` in `requested_model`.
      - Rules deployed to PEA Prometheus (bind-mounted
        `gpu-server/configs/alert_rules.yml`, `POST /-/reload` → 200): 36 rules
        load, all three new rules evaluate against live data with
        `health=ok`, no `lastError`. Previous file backed up on PEA at
        `/tmp/alert_rules.yml.bak-2026-09-18` (md5 `b44ce059…`). **PEA now runs
        this file ahead of the commit — land the same content and re-sync.**
      - **Blocker recorded:** nothing delivers. PEA's `prometheus.yml` has no
        `alerting:` block and `/api/v1/alertmanagers` reports zero active and
        zero dropped alertmanagers; no Alertmanager container runs on PEA or
        Prod (the one in `monitoring/` is undeployed). A firing alert is
        visible only in the Prometheus UI, so no live synthetic cooldown was
        induced on a production deployment — it would have proved nothing and
        would have cost real requests. Needs a follow-up change to stand up
        Alertmanager and a receiver.
