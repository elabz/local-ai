"""Private speech data-plane proxy with bounded, low-cardinality metrics."""
import asyncio
import json
import logging
import os
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

ROUTES = {
    "/v1/audio/transcriptions": ("stt", os.getenv("STT_UPSTREAM", "http://speech-stt:8000"), os.getenv("STT_MODEL", "faster-whisper-small.en"), "speaches"),
    "/v1/audio/speech": ("tts", os.getenv("TTS_UPSTREAM", "http://speech-tts:8880"), os.getenv("TTS_MODEL", "kokoro"), "kokoro"),
}
MAX_BODY = int(os.getenv("MAX_BODY_BYTES", "26214400"))
DEFAULT_TTS_PROFILE = os.getenv("SPEECH_TTS_ENCODING_PROFILE", "opus-40k")
OPUS_PROFILES = {
    "opus-128k": 128000,
    "opus-48k": 48000,
    "opus-40k": 40000,
    "opus-32k": 32000,
}


def prepare_tts_payload(payload):
    """Return the upstream payload and bounded profile for a TTS request."""
    prepared = dict(payload)
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
    operation, base, actual, provider = ROUTES[request.path]
    started = time.monotonic()
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
        LAT.labels(operation, actual, provider).observe(time.monotonic() - started)

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
    return app


if __name__ == "__main__":
    web.run_app(create_app(), port=8080)
