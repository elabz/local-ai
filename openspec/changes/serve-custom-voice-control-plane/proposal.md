# Proposal: serve-custom-voice-control-plane

## Why

HeartCode's `add-admin-custom-voices` lets administrators build, review,
publish, retire and delete custom Kokoro voices. It needs a private control
plane on Pea. local-ai wrote that contract
(`docs/contracts/custom-voice-control-plane-v1.yaml`) and most of the parts
(`custom_voice/`: signed auth, job store, intake, worker, sealing, evaluation,
registry, deletion), but none of them run:

- Nothing on Pea serves the contract. On 2026-10-13, HeartCode probed `:8200`
  (the speech gateway) and got 404s for every build, preview, retire and delete
  route. The gateway carries only an ad-hoc `activate` and a registry read.
- Nothing drives a build. `JobStore` queues jobs, but no process claims them.
  `custom-dima` was built by hand.
- The contract cannot receive HeartCode's samples. Intake is operator-provisioned
  files on Pea, while HeartCode collects recordings in its admin UI.
- `ActivationRequest` combined two closed schemas with `allOf`, so nothing
  could validate against it. `BuildResult` had no SBOM, and activation had no
  attestation document, although Pea's own activation check requires both.

The HeartCode owner chose to move HeartCode onto this contract (its design
addendum C1–C8), with a pull step for samples. This change is local-ai's half.

## What Changes

- **Contract 1.1.0.**
  - New routes: `POST /custom-voice-intakes` (signed pull of HeartCode's sample
    URLs), `GET /custom-voice-registry` and `GET /custom-voice-deletions/{id}`.
  - `sbom` is added to `BuildResult`, and `admin_attestation` to a flattened
    `ActivationRequest`.
  - Build jobs carry their `events`.
  - The documentation now spells out the callback signature, retire semantics
    and intake idempotency.
- **Intake pull** (`custom_voice/intake_pull.py`).
  - Pea fetches only from an origin allow-list, refuses redirects, enforces the
    profile's byte cap, and verifies each SHA-256 and the declared PCM format.
  - It then publishes a `benchmark-intake.v1` directory atomically.
  - It is idempotent per intake over everything except `fetch_url`.
- **A real service.** `custom-voice-control-plane` runs in compose on port
  8210. It has no GPU and no Docker socket, and reads its keys and callback
  targets from 0600 files.
- **Contract-shaped responses.** Jobs serialize to `BuildJob`, never raw SQLite
  rows. Every job transition dispatches a signed callback, best effort.
- **The lifecycle moves the registry and the gateway's `custom-voice-map.json`
  together** (`custom_voice/lifecycle.py`).
  - Activation and rollback keep every evidence check the gateway's `activate`
    makes today, including Kokoro discovery.
  - Retiring the active version takes the voice out of service.
  - Deletion is reference-aware and also removes the version's previews.
- **A host-side runner** (`custom_voice/runner.py`, a systemd unit) claims
  queued jobs and drives `prepare_workspace`, then `run_worker.sh`, then
  `run_postbuild.sh`, then `run_sbom.sh` (new), then `stage_for_review`. It
  honours cancellation through the worker's own `cancel.requested`.
- **The gateway's two `:8200` routes stay** until HeartCode switches over.
  Removing them is a later task.

## Capabilities

### Modified Capabilities

- `custom-kokoro-voice-builds`: the private control plane is served, intake can
  be pulled from an allow-listed origin, builds are driven to a contract
  result, and lifecycle operations keep registry and serving map consistent.

## Impact

- New files:
  - `gpu-server/custom_voice/{intake_pull,lifecycle,job_view,service,runner}.py`
  - `run_sbom.sh`, `Dockerfile.control-plane`, `requirements-control-plane.txt`,
    `custom-voice-runner.service`
- Changed files:
  - `gpu-server/custom_voice/control_plane.py`
  - `docs/contracts/custom-voice-control-plane-v1.yaml`
  - `gpu-server/docker-compose.yml` (+1 service, 384 MiB; budget still fits)
  - `.env.example`
  - `OPERATIONS.md`
  - `requirements-test.txt` (jsonschema)
- Operator on Pea:
  - create the service user and the private directories;
  - write the key and callback-target files;
  - install the systemd runner;
  - start the service.
- HeartCode: its `add-admin-custom-voices` §7 points dev at `:8210`.
