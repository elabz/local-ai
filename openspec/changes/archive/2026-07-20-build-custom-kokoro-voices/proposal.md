# Change: build-custom-kokoro-voices

## Why

The current Kokoro-FastAPI deployment is an inference server: it lists bundled voice packs, synthesizes speech, and can blend existing packs, but it does not train a new voice from recordings and transcripts. HeartCode needs a private, auditable pipeline that can evaluate an appropriate voice-building technique, turn authorized sample/transcript sets into Kokoro-compatible versioned artifacts, and activate approved artifacts without destabilizing live speech.

## What Changes

- Build a restricted, pinned multi-reference KVoiceWalk pilot and benchmark it against the pinned Kokoro runtime and Pea hardware; implementation may proceed before quality acceptance, while private Pea activation remains evidence-gated.
- Add a private authenticated voice-build control plane with idempotent asynchronous jobs, strict local-intake manifests, status/results, cancellation, and deletion.
- Validate, normalize, align, and quality-score authorized audio/transcript inputs in an isolated worker.
- Produce immutable, checksummed Kokoro-compatible voice-pack artifacts plus standard previews and evaluation reports.
- Add a versioned staging/production voice registry with atomic activation, health checks, rollback, retirement, and safe artifact cleanup.
- Keep builds resource-isolated from latency-sensitive Kokoro inference and expose only approved active packs through the existing speech path.
- Support the existing single Pea GPU server through concurrency-one admission, checkpointing, and inference-priority preemption rather than requiring a second GPU host.

## Capabilities

### New Capabilities

- `custom-kokoro-voice-builds`: A private worker builds and evaluates versioned Kokoro-compatible voices from validated audio/transcript manifests.
- `kokoro-voice-registry`: Operators and authorized clients can stage, activate, roll back, retire, reconcile, and delete custom voice-pack versions safely.

### Modified Capabilities

- `heartcode-speech-runtime`: Kokoro serving discovers active custom voice packs while preserving the existing authenticated TTS contract, built-in voices, and accepted live audio profile.

## Impact

- **Pea runtime:** new control-plane and worker services, root-confined private local intake/artifact stores, job database/queue, and controlled Kokoro voice-pack mount or registry integration.
- **GPU/CPU/storage:** preprocessing and voice construction consume bounded offline resources; capacity and scheduling are determined by the feasibility benchmark.
- **Security/privacy:** raw recordings and transcripts stay in private local filesystem roots and off public/LiteLLM routes, use least-privilege filesystem and service authorization, and are excluded from logs and metrics.
- **Operations:** version/digest reconciliation, health probes, rollback, retention, and audit events are required before internal Pea activation.
- **Distribution boundary:** custom artifacts remain on Pea and are never offered as public downloads or redistributed outside the private deployment.
- **Dependency:** coordinated HeartCode change `add-admin-custom-voices` owns admin UX, consent/provenance records, SBOM/license review, human review, and the final internal-activation decision.
