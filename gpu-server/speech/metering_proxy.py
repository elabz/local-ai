"""Private speech data-plane proxy with bounded, low-cardinality metrics."""
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
PROBE_OK = Gauge("speech_controlled_probe_success", "Last controlled probe correlation result")
PROBE_TIME = Gauge("speech_controlled_probe_timestamp_seconds", "Last controlled probe completion time")

ROUTES = {
    "/v1/audio/transcriptions": ("stt", os.getenv("STT_UPSTREAM", "http://speech-stt:8000"), os.getenv("STT_MODEL", "faster-whisper-small.en"), "speaches"),
    "/v1/audio/speech": ("tts", os.getenv("TTS_UPSTREAM", "http://speech-tts:8880"), os.getenv("TTS_MODEL", "kokoro"), "kokoro"),
}
MAX_BODY = int(os.getenv("MAX_BODY_BYTES", "26214400"))

def safe(value, fallback="unknown"):
    value = str(value or fallback)
    return value if value.replace("-", "").replace("_", "").replace(".", "").isalnum() and len(value) <= 80 else fallback

async def proxy(request):
    operation, base, actual, provider = ROUTES[request.path]
    started = time.monotonic()
    body = await request.read()
    if len(body) > MAX_BODY:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=len(body))
    requested = actual
    chars = 0
    if request.content_type == "application/json":
        try:
            payload = json.loads(body)
            requested = safe(payload.get("model"), actual)
            chars = len(payload.get("input", "")) if operation == "tts" else 0
        except (ValueError, TypeError):
            pass
    fallback = "true" if request.headers.get("X-LiteLLM-Fallback", "").lower() == "true" else "false"
    headers = {k: v for k, v in request.headers.items() if k.lower() in {"content-type", "accept", "x-speech-request-id", "x-call-id", "x-turn-id", "x-litellm-call-id"}}
    try:
        async with request.app["client"].post(base + request.path, data=body, headers=headers) as upstream:
            response = web.StreamResponse(status=upstream.status, headers={"Content-Type": upstream.headers.get("Content-Type", "application/octet-stream")})
            await response.prepare(request)
            byte_count = 0
            async for chunk in upstream.content.iter_chunked(65536):
                byte_count += len(chunk)
                await response.write(chunk)
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
            LOG.info(json.dumps({"event":"speech_request","operation":operation,"status":upstream.status,"speech_request_id":request.headers.get("X-Speech-Request-ID", ""),"call_id":request.headers.get("X-Call-ID", ""),"turn_id":request.headers.get("X-Turn-ID", ""),"litellm_call_id":request.headers.get("X-LiteLLM-Call-ID", "")}))
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

app = web.Application(client_max_size=MAX_BODY)
app.cleanup_ctx.append(context)
app.router.add_post("/v1/audio/transcriptions", proxy)
app.router.add_post("/v1/audio/speech", proxy)
app.router.add_get("/metrics", metrics)
app.router.add_get("/health", lambda _: web.json_response({"status":"ok"}))
web.run_app(app, port=8080)
