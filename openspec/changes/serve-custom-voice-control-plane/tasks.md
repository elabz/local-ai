# Tasks: serve-custom-voice-control-plane

## 1. Contract

- [x] 1.1 Contract 1.1.0. New routes: intake, registry read, deletion read. `sbom` added to `BuildResult`, `admin_attestation` to a flat `ActivationRequest` (the 1.0 `allOf` of two closed schemas accepted nothing). Job `events` added. Callback signature, retire, stage and intake idempotency are documented, the last one excluding `fetch_url`
- [x] 1.2 Contract tests: the metadata tests updated for 1.1. Conformance tests drive the real app and validate every request and response against the YAML (`test_custom_voice_contract_conformance.py`)

## 2. Service

- [x] 2.1 `intake_pull.py`: an origin allow-list with no redirects, a whole-intake byte cap, SHA and PCM-format checks and an atomic publish. Idempotent per `intake_id` over content, excluding URLs. The round trip through the real `prepare_workspace` is tested
- [x] 2.2 `control_plane.py`: intake route; build submission refuses an unknown callback ID, a missing intake or a mismatched manifest; `BuildJob` views (`job_view.py`); registry and deletion reads; a strict `ActivationRequest`
- [x] 2.3 `lifecycle.py`: stage (digest and language from the seal, idempotent), and activate and rollback with the gateway's exact evidence checks and Kokoro discovery. Retire of the active version unmaps it. Delete is reference-aware, removes previews and refuses the active version
- [x] 2.4 Callback dispatch on every transition (`JobNotifier`), best effort
- [x] 2.5 `service.py` wiring, `Dockerfile.control-plane` (built and smoke-tested locally: health, signed read, replay refused, safe 404), and a compose service on port 8210 that passes the memory-budget and `compose config` gates

## 3. Runner

- [x] 3.1 `runner.py`: claim, `prepare_workspace`, `run_worker.sh`, `run_postbuild.sh`, `run_sbom.sh` (new), `stage_for_review`, then a contract `BuildResult`. Safe failures, cancellation through `cancel.requested`, and recovery on restart
- [x] 3.2 `custom-voice-runner.service` systemd unit and the OPERATIONS.md section
- [ ] 3.3 Bind `blue_green.py`'s provider operations, so that an approved new version is loaded into Kokoro without a hand-edited mount. Until then, loading it is an operator step before HeartCode publishes
- [ ] 3.4 Wire ASR alignment (`alignment.py`) into preprocessing, as OPERATIONS.md step 2 describes, or record that the profile does without it

## 4. Deploy on Pea (owner-approved)

- [ ] 4.1 Read-only first:
  - confirm `private/custom-voice-registry/registry.json` carries `schema_version: custom-voice-registry.v1`;
  - confirm the private directories' owner;
  - build the worker and compatibility images, or record their existing image IDs
- [ ] 4.2 Create the `custom-voice` service user and directories (`custom-voice-jobs`, `-intake`, `-workspaces`, `-results`, `-previews`, `-cache`, `-locks`). Write `service-keys.json` and `callback-targets.json` (0600) and set `CUSTOM_VOICE_SAMPLE_ORIGINS`
- [ ] 4.3 `docker compose up -d --build custom-voice-control-plane`, and install and start `custom-voice-runner`
- [ ] 4.4 A signed registry read from HeartCode dev lists `custom-dima`. HeartCode's `add-admin-custom-voices` 7.7 then runs its 6.4 drills against `:8210`
- [ ] 4.5 Once HeartCode uses `:8210`, remove the gateway's `:8200` `voice-registry` routes and its `CUSTOM_VOICE_CONTROL_PLANE_KEY`
