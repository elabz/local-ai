"""Export speech GPU inventory, process residency, and sampled activity."""
import os, subprocess
from aiohttp import web
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

UUID = os.getenv("SPEECH_GPU_UUID")
EXPECTED = os.getenv("SPEECH_GPU_PHYSICAL_INDEX", "6")
labels = ["gpu_uuid", "physical_index_zero_based", "display_slot_one_based"]
INFO = Gauge("speech_gpu_inventory_info", "Speech GPU identity", labels)
MATCH = Gauge("speech_gpu_inventory_match", "Configured speech GPU is present (and at the configured index where that is observable)", labels)
MEM = Gauge("speech_gpu_process_memory_bytes", "Speech process GPU memory", labels + ["process"])
UTIL = Gauge("speech_gpu_utilization_percent", "Sampled GPU utilization", labels)

def query(args):
    return subprocess.check_output(["nvidia-smi", *args], text=True, timeout=10).strip()

def inventory(rows, expected_uuid=None, expected_index=None):
    """Resolve (uuid, index_label, utilization, match) for the configured card.

    `rows` are `uuid, index, utilization.gpu` CSV lines from nvidia-smi.

    The container is pinned to one card with NVIDIA_VISIBLE_DEVICES, so
    nvidia-smi inside it renumbers that card to index 0 no matter where it sits
    on the host. Comparing that against the configured host index (6) can never
    match: the rule fired continuously from deployment until 2026-09-20, while
    the card was correctly placed all along. When only the pinned card is
    visible the host mapping is unobservable here, so the check is what this
    process can actually prove — the visible card IS the configured UUID — and
    the exported index label stays the configured one rather than the
    container-local 0. `scripts/check-placement.py` owns host-index
    verification; it runs on the host where indices are real.

    A missing UUID still fails: that means the service was handed the wrong
    card, or none. Raises LookupError, leaving the previous sample in place.
    """
    expected_uuid = UUID if expected_uuid is None else expected_uuid
    expected_index = EXPECTED if expected_index is None else expected_index
    visible = [tuple(x.strip() for x in row.split(",")) for row in rows if row.strip()]
    found = next((row for row in visible if row[0] == expected_uuid), None)
    if found is None:
        raise LookupError("configured speech GPU is not visible to this container")
    uuid, index, util = found
    pinned = len(visible) == 1
    return uuid, (expected_index if pinned else index), util, (True if pinned else index == expected_index)

async def metrics(_):
    rows = query(["--query-gpu=uuid,index,utilization.gpu", "--format=csv,noheader,nounits"]).splitlines()
    uuid, index, util, match = inventory(rows)
    base = (uuid, index, os.getenv("SPEECH_GPU_DISPLAY_SLOT", "7"))
    INFO.labels(*base).set(1); MATCH.labels(*base).set(match); UTIL.labels(*base).set(float(util))
    MEM.clear()
    try:
        for row in query([f"--id={UUID}", "--query-compute-apps=process_name,used_memory", "--format=csv,noheader,nounits"]).splitlines():
            process, mib = (x.strip() for x in row.rsplit(",", 1)); MEM.labels(*base, os.path.basename(process)[:64]).set(float(mib) * 1048576)
    except (subprocess.CalledProcessError, ValueError): pass
    return web.Response(body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

async def health(_):
    # aiohttp requires a coroutine handler; the previous sync lambda made this
    # endpoint raise. Nothing scrapes it (Prometheus uses /metrics), so it went
    # unnoticed until the 2026-09-23 exporter change.
    return web.json_response({"status": "ok"})

app=web.Application(); app.router.add_get("/metrics", metrics); app.router.add_get("/health", health)
if __name__ == "__main__":
    web.run_app(app, port=9400)
