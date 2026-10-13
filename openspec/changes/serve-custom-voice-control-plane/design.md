# Design: serve-custom-voice-control-plane

## Context

`custom_voice/` already holds every build stage and its safety rules:

- signed requests with a replay store, a durable job queue, and root-confined
  intake;
- the pinned KVoiceWalk worker, digest-sealed artifacts, Kokoro compatibility
  and held-out evaluation;
- the registry, and reference-aware deletion.

What was missing is everything that makes those stages a service. Nobody
served the API, nobody claimed queued jobs, samples could not reach Pea, and
some contract schemas could not be satisfied. HeartCode's
`add-admin-custom-voices` design addendum (C1–C8) adopts this contract. This
design is the serving side.

## Decisions

### 1. Two processes, one queue file

The API (`custom_voice.service:app` in compose, port 8210) and the runner
(`custom_voice.runner` under systemd on the host) share
`private/custom-voice-jobs/jobs.sqlite3`, in WAL mode on one host filesystem.

- The API has no GPU, no Docker socket and a read-only rootfs, and runs as the
  service UID.
- The runner needs Docker to start the pinned worker and compatibility
  containers. It runs as the same service UID, whose docker group membership
  is the system's only Docker access. That is the "narrowly scoped host-side
  service" `blue_green.py` and OPERATIONS.md already anticipate.
- Builder containers still never get the socket. Putting the runner in a
  container would have meant mounting the socket into it, which is worse.

### 2. Intake is pulled, verified, then frozen

`POST /custom-voice-intakes` carries ten samples. Each has a role, a signed
`fetch_url`, a SHA-256, a transcript and its PCM format.

- Pea parses every URL to `scheme://host:port` and compares it exactly
  against `CUSTOM_VOICE_SAMPLE_ORIGINS`. It fetches without following
  redirects and streams under the profile's whole-intake byte cap.
- It verifies the digest and checks the WAV header (mono, 16-bit, the declared
  rate) before writing a byte.
- The directory is written to a temporary name and renamed into place.
  `prepare_workspace` then runs on it unchanged, so the build stays
  filesystem-only: the worker network never reaches HeartCode.
- Idempotency is per `intake_id`, over a fingerprint of every content field
  except `fetch_url`. HeartCode re-signs URLs because they expire after 300 s,
  so a retry with new URLs returns the stored digest without fetching. Different
  content is `409 intake_conflict`.

The manifest also records `stable_voice_id` and `version`. That is how the
runner knows where `run_postbuild.sh` seals the artifact.

### 3. Jobs are views, and callbacks only signal

`build_job_view` maps a row to `BuildJob` (`schema_version`, RFC 3339 times,
`result` only when succeeded, `error` as a `SafeError`, `events` on reads). No
raw column (`caller_id`, `idempotency_key`, `safe_result_json`) leaves the
service.

Each transition delivers the latest event to the job's allow-listed callback,
using `callbacks.CallbackDispatcher`. Delivery is best effort: it runs in a
background thread in the API, and a lost callback costs latency only, because
HeartCode reconciles by reading the job. A build naming an unknown callback ID,
a missing intake or a mismatched manifest digest is refused at submission, not
hours later.

### 4. The registry and the serving map move together

The gateway resolves `custom-*` voices through `custom-voice-map.json`, and the
registry records versions. `lifecycle.Lifecycle` changes both files.

- **Activate and rollback.** The handlers repeat the gateway's current checks:
  the registry entry and artifact bytes match the digest, the SBOM bytes match
  `sbom_sha256`, and the attestation document is approved, scoped
  `internal_pea`, bound to both digests, has the three confirmations, and has an
  unresolved-licence count equal to the one recomputed from the SBOM. Kokoro
  must also list `cv_<id>`. Any failure leaves both files untouched.
- **Stage.** The manifest digest and language come from local-ai's own seal.
  A successful build is already staged by the runner, so staging again with the
  same digest is an idempotent read.
- **Retire.** Retiring the active version unmaps the voice first, then marks it
  retired. HeartCode's "retire voice" means exactly that, and no version stays
  served.
- **Delete.** Detach the rollback reference, queue it, run
  `garbage_collection` confined to the artifact root, then remove the
  version's previews. The runner lists their IDs in `previews.json` beside the
  seal, because previews live flat under the preview root. The active version
  cannot be deleted.

### 5. The runner wires existing stages and invents none

The stages run in order: claim, `prepare_workspace`, `run_worker.sh`,
`run_postbuild.sh`, `run_sbom.sh`, `stage_for_review`.

- **Result.** `BuildResult` is built from the seal manifest, `evaluation.json`,
  `compatibility.json` and the SBOM line.
- **Failures.** Each ends the job `failed` with a safe code: intake rejections
  are 422, everything else 500.
- **Cancellation.** It is checked between phases. While the worker runs, the
  runner touches the worker's `cancel.requested`.
- **Recovery.** On restart, in-flight jobs are requeued by the existing
  `recover_inflight`.
- **New script.** `run_sbom.sh` runs `sbom.py` inside the pinned worker image,
  whose installed distributions are what the SBOM inventories, with no network.
  The SBOM is written beside the artifact, where activation verifies it.

## Gaps (open tasks, not invented here)

- **Loading a new voice into Kokoro.**
  - Activation requires that Kokoro already lists the voice.
  - Today that means mounting the sealed `.pt` into `speech-tts` by hand and
    recreating it, as `cv_custom_dima.pt` is mounted.
  - `blue_green.py` has the drained switch but no provider operations bound to
    it.
  - Until it does, every new version needs an operator step between approval
    and publication.
- **ASR alignment.** OPERATIONS.md step 2 says preprocessing includes ASR
  alignment, but `alignment.py` is never called. The runner does not add it.
- **The registry file format on Pea.** `registry.load_registry` requires
  `schema_version: custom-voice-registry.v1`. The file the gateway writes must
  be checked before the service starts.
- **Human naturalness.** The evaluator reports none, so the result always says
  `pending`.

## Risks / Trade-offs

- **SQLite across a container and a host process.**
  - Both open the same WAL database with `BEGIN IMMEDIATE` around every
    transition.
  - It is safe on one host filesystem, and the queue is tiny: one build at a
    time, gated by the GPU lock.
- **The API fetches from the LAN.**
  - It is limited to explicit origins, with no redirects, a byte cap and
    digest verification.
  - A compromised HeartCode key could still make Pea fetch from HeartCode
    itself, but nowhere else.
- **Two activation paths during the transition.**
  - The gateway's `:8200 activate` and the new one write the same two files
    with the same checks.
  - The old route goes once HeartCode is on `:8210`.
