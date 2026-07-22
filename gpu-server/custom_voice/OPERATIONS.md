# Custom Voice Operations

This subsystem is private infrastructure. Do not route its build, preview,
registry, or deletion operations through LiteLLM or the public speech gateway.
HeartCode owns authorization and publication approval; local-ai owns execution
and serving state.

## Deployment identity and isolation

- Production builder profile: `kvoicewalk-multireference.v1`.
- Builder source: KVoiceWalk commit
  `3a38c6030cc4657df073c67ded37cdf7627c4969`.
- Kokoro runtime: v0.6.0 image digest
  `560e5ba33e78597cf35d266a5591c3ce7558dce318b3019fb6d94e28b466080b`.
- Speech device: `GPU-f417c539-26db-94e9-4c8f-c5a775291988`.
- Build concurrency: one, enforced through the shared GPU lock.
- Container limits: 2 CPU, 4 GiB RAM/swap, 256 PIDs, read-only root,
  no capabilities, no privilege escalation, six-hour worker deadline.
- Admission: 5,000 MiB free VRAM and healthy live TTS. Runtime abort floor:
  1,024 MiB free VRAM, checked throughout selection and the walk.

Build the worker and compatibility runner from this directory. Record the
resulting exact image IDs; never use a mutable tag as provenance. Launch builds
through `run_worker.sh`, supplying the private root, exact local image, image
digest, and immutable job ID. The worker network is limited to the internal
speech network for the TTS health probe; source ingestion is filesystem-only.
Set `umask 077` in the host launcher before creating or redirecting any worker
log; launcher output is content-free but remains private operational evidence.

## Filesystem layout and permissions

Use separate host roots beneath the private volume:

- `custom-voice-intake`: operator-provisioned immutable source manifests,
  recordings, transcript sidecars, and authorization references;
- `custom-voice-workspaces`: normalized per-job inputs and build plans;
- `custom-voice-results`: checkpoints and unsealed build results;
- `custom-voice-artifacts`: content-addressed immutable versions/manifests;
- `custom-voice-previews`: protected held-out previews;
- `custom-voice-cache`: pinned model cache with no source recordings;
- `custom-voice-registry`: registry, events, and deletion requests;
- `custom-voice-backups`: encrypted approved artifact/registry backups.

Directories are `0700`; files containing protected content or provenance are
`0600`. Workers run as the owning service UID. Intake is mounted read-only.
Workers never mount the active Kokoro voice directory or Docker socket.

## Secrets and scopes

Use a dedicated service credential distinct from speech inference keys. Define
separate `build`, `read`, `preview.read`, `activate`, and `delete` scopes.
Activation and deletion credentials are not present in builder containers.
Callback secrets are distinct, rotated independently, and never logged.
Requests require timestamps/nonces and replay protection. Activation approval
is a digest-bound HeartCode admin attestation, not a decision invented by
local-ai.

## Build and evaluation runbook

1. Verify the intake manifest SHA-256 and restrictive ownership/modes.
2. Run secure preprocessing and ASR alignment. A rejection stops the job.
3. Confirm TTS/STT health and at least 5,000 MiB free VRAM.
4. Launch through `run_worker.sh`; observe content-free phase, resource, and
   health metrics. A second worker must fail the shared lock.
5. On success, verify `result.json`, artifact/preview digests, duration and
   resource thresholds. A checkpoint without a successful result is not an
   eligible artifact.
6. Seal into the immutable store, run held-out evaluation, then run the clean
   pinned compatibility container. Preserve reports by digest.
7. Generate the exact SPDX SBOM and obtain an authenticated HeartCode admin
   attestation for internal Pea use bound to both artifact and SBOM digests.
8. Stage for protected human review. Staging never exposes public discovery.
9. Activate only the exact approved version/digest through the blue/green
   health-probed switch. Verify discovery and `opus-40k` synthesis.

## Monitoring and capacity response

Alert on queue age/depth, failed phases, worker duration, GPU reserve, container
RAM, TTS/STT health, registry drift, activation failure, and deletion backlog.
Metrics and alerts contain only opaque IDs, safe reason codes, states, counts,
durations, and resource values.

If TTS becomes unhealthy, latency crosses the accepted threshold, or free VRAM
approaches 1,024 MiB, stop accepting work and cancel the worker gracefully.
Preserve its checkpoint and safe event record, verify TTS recovery, and do not
resume until capacity is healthy. Never restart or evict live speech merely to
make an offline build finish.

For resumable workers, `checkpoint.v2.json` is identity-bound and may be reused
only by the exact manifest, plan, builder, image, model/runtime, backend, device,
and seed. Legacy `checkpoint.pt` files are non-resumable. Performance rollout
evidence and the exhaustive fallback procedure are recorded in
`BUILD-PERFORMANCE.md`.

## Activation, rollback, and reconciliation

The pinned Kokoro provider caches loaded tensors and cannot safely replace a
stable filename in place. Use a versioned read-only voice mount and drained
blue/green provider replacement. Probe exact-digest synthesis before switching
traffic. Only then atomically update the stable registry mapping.

If activation or health probing fails, leave the prior mapping untouched. To
roll back, name the exact retained version and digest, repeat the clean health
probe, switch traffic, and reconcile loaded versus declared digests. Missing or
mismatched active bytes mark that voice unhealthy and remove it from discovery;
unrelated built-in and custom voices remain available.

## Retention and deletion

Raw intake retention follows the external authorization/retention policy and is
never shortened implicitly by a successful build. Failed temporary workspaces
are cleaned immediately; evidentiary reports, SBOMs, approvals, and active or
rollback-retained artifacts follow the approved production retention schedule.

Deletion is asynchronous and reference-aware. It inventories workspace, cache,
preview, artifact, registry, and backup references. Active and rollback-retained
versions cannot be queued. After explicit detachment, removal is confined to
configured roots and verified before registry state becomes `deleted`.

## Incident response and disaster recovery

For suspected content disclosure, credential misuse, artifact substitution, or
unauthorized impersonation: disable the private control-plane credential,
pause the queue, preserve access-controlled audit evidence, reconcile every
active digest, and remove affected voices from discovery. Rotate credentials
and require new exact attestations after rebuilding evidence.

Back up encrypted immutable artifacts/manifests, registry state/events, SBOMs,
and approvals. Do not back up transient model caches unless operationally
required. A restore goes into a new private root, verifies every digest and
reference, starts with all custom voices non-active, runs compatibility and
provider health probes, then reactivates exact approved versions one at a time.
Unknown or incomplete state fails closed.
