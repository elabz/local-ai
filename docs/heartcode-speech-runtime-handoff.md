# HeartCode speech runtime: frontend architecture handoff

## What changed

HeartCode now has two GPU-backed speech capabilities on PEA: `heartcode-stt` for transcription and `heartcode-tts` for synthesis. LiteLLM remains the normal policy route for authentication, virtual-key accounting, rate limits, retries, cooldowns, and model routing. A backend-only direct TTS route exists for lower-latency streaming when LiteLLM buffering is undesirable.

Every speech turn carries three secret-free correlation headers:

- `X-Speech-Request-ID`: unique per STT or TTS request.
- `X-Call-ID`: stable for one voice-call session.
- `X-Turn-ID`: stable for the user/assistant turn, shared by related STT and TTS work.

LiteLLM's current audio adapters do not natively preserve custom request headers. A scoped callback/startup shim copies only these three validated headers for the `heartcode-stt` and `heartcode-tts` model groups. Authorization, cookies, arbitrary `X-*` headers, audio, transcript text, and synthesis input are not copied into observability logs or metric labels.

## Frontend and backend responsibilities

The browser may generate or receive call/turn identifiers, but it must send speech through the HeartCode backend. The browser must never know the PEA direct-stream URL or `SPEECH_DIRECT_API_KEY`.

The HeartCode backend should:

1. Create a fresh request ID for every STT/TTS operation and preserve the active call and turn IDs.
2. Use LiteLLM for normal STT and TTS requests.
3. Use direct TTS only for the explicit low-latency streaming path, attaching the backend-held service credential.
4. Store correlation IDs with message/call accounting records, but never store the direct credential in request metadata.
5. Treat interrupted playback as a client/session state transition; the completed provider request can still have a successful infrastructure status.

## UI states and failure behavior

The UI can model speech as `capturing → transcribing → thinking → synthesizing → playing`, with `interrupted` and `failed` terminal branches. Infrastructure health is intentionally not exposed directly to browsers. Backend errors should be mapped to user-safe states: retryable service unavailable, authentication/configuration failure, rate limited, or request rejected. Do not surface provider URLs, model cache details, GPU identifiers, credentials, or raw gateway errors.

Correlation IDs are for support and diagnostics. If shown at all, expose a short copyable support reference behind a diagnostic affordance rather than in the primary conversation UI.

## Operational evidence

The controlled production probe verified both routes with HTTP 200, exact request/call/turn correlation in PEA logs, a matching LiteLLM accounting row, two request-counter increments, 438,304,768 bytes of GPU process residency, and GPU UUID `GPU-f417c539-26db-94e9-4c8f-c5a775291988` at zero-based physical index 6 (display slot 7). Metrics and dashboards intentionally exclude request, call, and turn IDs to avoid high cardinality.
