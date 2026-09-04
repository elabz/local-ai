"""Private speech data-plane proxy with bounded, low-cardinality metrics."""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
from aiohttp import ClientSession, ClientTimeout, web
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

logging.basicConfig(level=logging.INFO, format="%(message)s")
LOG = logging.getLogger("speech-meter")
REQ = Counter("speech_requests_total", "Speech requests", ["operation", "requested_model", "actual_model", "provider", "status", "fallback"])
FAIL = Counter("speech_failures_total", "Speech failures", ["operation", "actual_model", "provider", "reason"])
LAT = Histogram("speech_request_duration_seconds", "Speech request latency", ["operation", "actual_model", "provider"], buckets=(.1,.25,.5,1,2.5,5,10,20,40,80))
UNITS = Counter("speech_workload_units_total", "Speech workload", ["operation", "unit"])
ENCODED = Counter("speech_encoded_bytes_total", "Encoded TTS response bytes", ["profile"])
ENCODE_LAT = Histogram("speech_encode_duration_seconds", "TTS encoding stage duration", ["profile"], buckets=(.05,.1,.2,.35,.5,.75,1,2,5,10))
FIRST_BYTE = Histogram("speech_response_first_byte_seconds", "Speech response first-byte latency", ["operation", "profile"], buckets=(.05,.1,.2,.35,.5,.75,1,2,5,10))
PROBE_OK = Gauge("speech_controlled_probe_success", "Last controlled probe correlation result")
PROBE_TIME = Gauge("speech_controlled_probe_timestamp_seconds", "Last controlled probe completion time")
ACTIVE_REQUESTS = 0
LAST_ACTIVITY = time.monotonic()

ROUTES = {
    "/v1/audio/transcriptions": ("stt", os.getenv("STT_UPSTREAM", "http://speech-stt:8000"), os.getenv("STT_MODEL", "faster-whisper-small.en"), "speaches"),
    "/v1/audio/speech": ("tts", os.getenv("TTS_UPSTREAM", "http://speech-tts:8880"), os.getenv("TTS_MODEL", "kokoro"), "kokoro"),
}
MAX_BODY = int(os.getenv("MAX_BODY_BYTES", "26214400"))
DEFAULT_TTS_PROFILE = os.getenv("SPEECH_TTS_ENCODING_PROFILE", "opus-40k")
CUSTOM_VOICE_MAP_PATH = os.getenv("CUSTOM_VOICE_MAP_PATH", "")
CUSTOM_VOICE_REGISTRY_PATH = os.getenv("CUSTOM_VOICE_REGISTRY_PATH", "")
CUSTOM_VOICE_ARTIFACT_ROOT = os.getenv("CUSTOM_VOICE_ARTIFACT_ROOT", "")
CUSTOM_VOICE_CONTROL_PLANE_KEY = os.getenv("CUSTOM_VOICE_CONTROL_PLANE_KEY", "")
OPUS_PROFILES = {
    "opus-128k": 128000,
    "opus-48k": 48000,
    "opus-40k": 40000,
    "opus-32k": 32000,
}


def prepare_tts_payload(payload):
    """Return the upstream payload and bounded profile for a TTS request."""
    prepared = dict(payload)
    voice = prepared.get("voice")
    if isinstance(voice, str) and voice.startswith("custom-") and CUSTOM_VOICE_MAP_PATH:
        try:
            with open(CUSTOM_VOICE_MAP_PATH, encoding="utf-8") as source:
                mapping = json.load(source).get("voices", {})
            entry = mapping.get(voice)
            if not isinstance(entry, dict) or not entry.get("provider_voice_id"):
                raise web.HTTPBadRequest(text="Custom voice is not active")
            prepared["voice"] = entry["provider_voice_id"]
            prepared["lang_code"] = entry.get("language", "a")
        except (OSError, ValueError, TypeError):
            raise web.HTTPServiceUnavailable(text="Custom voice registry unavailable") from None
    profile = "not-applicable"
    if prepared.get("response_format", "mp3") == "opus":
        profile = safe(prepared.pop("encoding_profile", DEFAULT_TTS_PROFILE), DEFAULT_TTS_PROFILE)
        if profile not in OPUS_PROFILES:
            raise web.HTTPBadRequest(text="Unsupported speech encoding profile")
        if profile != "opus-128k":
            prepared["response_format"] = "pcm"
    return prepared, profile

def safe(value, fallback="unknown"):
    value = str(value or fallback)
    return value if value.replace("-", "").replace("_", "").replace(".", "").isalnum() and len(value) <= 80 else fallback


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path, value):
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".custom-voice-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def require_control_plane_auth(request):
    expected = CUSTOM_VOICE_CONTROL_PLANE_KEY
    supplied = request.headers.get("Authorization", "")
    if not expected or not hmac.compare_digest(supplied, f"Bearer {expected}"):
        raise web.HTTPUnauthorized(text=json.dumps({"error": {"code": "CONTROL_PLANE_UNAUTHORIZED", "retryable": False}}), content_type="application/json")


async def activate_custom_voice(request):
    """Verify exact private evidence, probe Kokoro, and publish a stable voice mapping."""
    require_control_plane_auth(request)
    voice_id = request.match_info["voice_id"]
    if not voice_id.startswith("custom-") or not all(c.islower() or c.isdigit() or c == "-" for c in voice_id):
        raise web.HTTPUnprocessableEntity(text=json.dumps({"error": {"code": "VOICE_ID_INVALID", "retryable": False}}), content_type="application/json")
    try:
        payload = await request.json()
        with open(CUSTOM_VOICE_REGISTRY_PATH, encoding="utf-8") as source:
            registry = json.load(source)
        version = payload["artifact_version"]
        entry = registry["voices"][voice_id]["versions"][version]
        artifact_digest = payload["artifact_digest"]
        sbom_digest = payload["sbom_sha256"]
        attestation = payload["admin_attestation"]
        artifact_dir = os.path.join(CUSTOM_VOICE_ARTIFACT_ROOT, voice_id, version)
        artifact_path = os.path.join(artifact_dir, artifact_digest + ".pt")
        sbom_path = os.path.join(artifact_dir, "sbom.spdx.json")
        with open(sbom_path, encoding="utf-8") as source:
            sbom = json.load(source)
        packages = sbom.get("packages", [])
        unresolved = sum(1 for package in packages if package.get("licenseConcluded") in {None, "", "NOASSERTION", "NONE"})
        evidence_ok = (
            entry["artifact_sha256"] == artifact_digest
            and sha256_file(artifact_path) == artifact_digest
            and sha256_file(sbom_path) == sbom_digest
            and payload.get("admin_attestation_id") == attestation.get("attestation_id")
            and attestation.get("status") == "approved"
            and attestation.get("scope") == "internal_pea"
            and attestation.get("artifact_sha256") == artifact_digest
            and attestation.get("sbom_sha256") == sbom_digest
            and attestation.get("speaker_authority_confirmed") is True
            and attestation.get("no_redistribution_confirmed") is True
            and attestation.get("license_findings_acknowledged") is True
            and attestation.get("unresolved_license_count") == unresolved
        )
        if not evidence_ok:
            raise ValueError("evidence mismatch")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise web.HTTPConflict(text=json.dumps({"error": {"code": "ACTIVATION_EVIDENCE_REJECTED", "retryable": False}}), content_type="application/json") from None

    provider_voice_id = "cv_" + voice_id.replace("-", "_")
    upstream = ROUTES["/v1/audio/speech"][1]
    async with request.app["client"].get(upstream + "/v1/audio/voices") as response:
        discovered = await response.json() if response.status == 200 else {}
    voice_values = discovered.get("voices", discovered) if isinstance(discovered, dict) else discovered
    if provider_voice_id not in json.dumps(voice_values):
        raise web.HTTPConflict(text=json.dumps({"error": {"code": "ACTIVATION_DISCOVERY_FAILED", "retryable": True}}), content_type="application/json")

    try:
        with open(CUSTOM_VOICE_MAP_PATH, encoding="utf-8") as source:
            mapping = json.load(source)
    except (OSError, ValueError):
        mapping = {"voices": {}}
    mapping.setdefault("voices", {})[voice_id] = {"provider_voice_id": provider_voice_id, "language": entry.get("language", "a")}
    atomic_json(CUSTOM_VOICE_MAP_PATH, mapping)
    registry_voice = registry["voices"][voice_id]
    prior = registry_voice.get("active_version")
    if prior and prior != version:
        registry_voice["versions"][prior]["state"] = "retired"
    entry["state"] = "active"
    registry_voice["active_version"] = version
    atomic_json(CUSTOM_VOICE_REGISTRY_PATH, registry)
    return web.json_response({"voice_id": voice_id, "artifact_digest": artifact_digest, "state": "active", "healthy": True})


async def custom_voice_registry(request):
    require_control_plane_auth(request)
    try:
        with open(CUSTOM_VOICE_MAP_PATH, encoding="utf-8") as source:
            mapping = json.load(source)
    except (OSError, ValueError):
        mapping = {"voices": {}}
    return web.json_response(mapping)


async def transcode_pcm_to_opus(upstream, response, profile, started):
    bitrate = OPUS_PROFILES[profile]
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", "pipe:0",
        "-c:a", "libopus", "-b:a", str(bitrate), "-vbr", "on",
        "-application", "voip", "-frame_duration", "20", "-f", "ogg", "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def feed_pcm():
        try:
            async for chunk in upstream.content.iter_chunked(65536):
                process.stdin.write(chunk)
                await process.stdin.drain()
        finally:
            process.stdin.close()

    feeder = asyncio.create_task(feed_pcm())
    byte_count = 0
    first_byte = True
    encode_started = time.monotonic()
    try:
        while True:
            chunk = await process.stdout.read(65536)
            if not chunk:
                break
            if first_byte:
                FIRST_BYTE.labels("tts", profile).observe(time.monotonic() - started)
                first_byte = False
            byte_count += len(chunk)
            await response.write(chunk)
        await feeder
        return_code = await process.wait()
        if return_code:
            error = (await process.stderr.read()).decode("utf-8", "replace")[:500]
            raise RuntimeError(f"ffmpeg opus encoder failed ({return_code}): {error}")
        ENCODED.labels(profile).inc(byte_count)
        ENCODE_LAT.labels(profile).observe(time.monotonic() - encode_started)
        return byte_count
    finally:
        if not feeder.done():
            feeder.cancel()
            await asyncio.gather(feeder, return_exceptions=True)
        if process.returncode is None:
            process.kill()
            await process.wait()

async def proxy(request):
    global ACTIVE_REQUESTS, LAST_ACTIVITY
    operation, base, actual, provider = ROUTES[request.path]
    started = time.monotonic()
    ACTIVE_REQUESTS += 1
    LAST_ACTIVITY = started
    try:
        body = await request.read()
        if len(body) > MAX_BODY:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=len(body))
        requested = actual
        chars = 0
        payload = None
        profile = "not-applicable"
        if request.content_type == "application/json":
            try:
                payload = json.loads(body)
                requested = safe(payload.get("model"), actual)
                chars = len(payload.get("input", "")) if operation == "tts" else 0
                if operation == "tts":
                    payload, profile = prepare_tts_payload(payload)
                    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            except (ValueError, TypeError):
                pass
        fallback = "true" if request.headers.get("X-LiteLLM-Fallback", "").lower() == "true" else "false"
        headers = {k: v for k, v in request.headers.items() if k.lower() in {"content-type", "accept", "x-speech-request-id", "x-call-id", "x-turn-id", "x-litellm-call-id"}}
    except Exception:
        ACTIVE_REQUESTS -= 1
        LAST_ACTIVITY = time.monotonic()
        LAT.labels(operation, actual, provider).observe(LAST_ACTIVITY - started)
        raise
    try:
        async with request.app["client"].post(base + request.path, data=body, headers=headers) as upstream:
            transcode = operation == "tts" and profile in OPUS_PROFILES and profile != "opus-128k" and upstream.status < 400
            content_type = "audio/opus" if transcode else upstream.headers.get("Content-Type", "application/octet-stream")
            response = web.StreamResponse(status=upstream.status, headers={"Content-Type": content_type})
            await response.prepare(request)
            byte_count = 0
            first_byte = True
            if transcode:
                byte_count = await transcode_pcm_to_opus(upstream, response, profile, started)
            else:
                async for chunk in upstream.content.iter_chunked(65536):
                    if first_byte:
                        FIRST_BYTE.labels(operation, profile).observe(time.monotonic() - started)
                        first_byte = False
                    byte_count += len(chunk)
                    await response.write(chunk)
                if operation == "tts":
                    ENCODED.labels(profile).inc(byte_count)
            await response.write_eof()
            status = str(upstream.status // 100) + "xx"
            if upstream.status >= 400:
                FAIL.labels(operation, actual, provider, "upstream_status").inc()
            REQ.labels(operation, requested, actual, provider, status, fallback).inc()
            if operation == "tts":
                UNITS.labels(operation, "characters").inc(chars)
                UNITS.labels(operation, "response_bytes").inc(byte_count)
            elif request.headers.get("X-Audio-Duration-Seconds"):
                try: UNITS.labels(operation, "audio_seconds").inc(max(0, float(request.headers["X-Audio-Duration-Seconds"])))
                except ValueError: pass
            LOG.info(json.dumps({"event":"speech_request","operation":operation,"status":upstream.status,"encoding_profile":profile,"response_bytes":byte_count,"speech_request_id":request.headers.get("X-Speech-Request-ID", ""),"call_id":request.headers.get("X-Call-ID", ""),"turn_id":request.headers.get("X-Turn-ID", ""),"litellm_call_id":request.headers.get("X-LiteLLM-Call-ID", "")}))
            return response
    except Exception:
        FAIL.labels(operation, actual, provider, "upstream_error").inc()
        REQ.labels(operation, requested, actual, provider, "5xx", fallback).inc()
        raise
    finally:
        ACTIVE_REQUESTS -= 1
        LAST_ACTIVITY = time.monotonic()
        LAT.labels(operation, actual, provider).observe(time.monotonic() - started)

async def activity(_):
    return web.json_response({"active_requests": ACTIVE_REQUESTS, "idle_seconds": max(0.0, time.monotonic() - LAST_ACTIVITY)})

async def metrics(_):
    try:
        files = [os.path.join("/evidence", f) for f in os.listdir("/evidence") if f.endswith(".json")]
        latest = max(files, key=os.path.getmtime)
        with open(latest, encoding="utf-8") as handle: evidence = json.load(handle)
        ok = evidence["correlation"]["meter_log_hits"] >= 2 and evidence["correlation"]["accounting_rows"] >= 1
        PROBE_OK.set(ok); PROBE_TIME.set(os.path.getmtime(latest))
    except (OSError, ValueError, KeyError):
        PROBE_OK.set(0); PROBE_TIME.set(0)
    return web.Response(body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

async def context(app):
    app["client"] = ClientSession(timeout=ClientTimeout(total=float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "120"))))
    yield
    await app["client"].close()

def create_app():
    app = web.Application(client_max_size=MAX_BODY)
    app.cleanup_ctx.append(context)
    app.router.add_post("/v1/audio/transcriptions", proxy)
    app.router.add_post("/v1/audio/speech", proxy)
    app.router.add_get("/metrics", metrics)
    app.router.add_get("/health", lambda _: web.json_response({"status":"ok"}))
    app.router.add_get("/internal/activity", activity)
    app.router.add_post("/internal/v1/voice-registry/{voice_id}/activate", activate_custom_voice)
    app.router.add_get("/internal/v1/voice-registry", custom_voice_registry)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), port=8080)
