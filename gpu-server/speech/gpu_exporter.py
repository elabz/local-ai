"""Export speech GPU inventory, process residency, and sampled activity."""
import os, subprocess
from aiohttp import web
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

UUID = os.getenv("SPEECH_GPU_UUID")
EXPECTED = os.getenv("SPEECH_GPU_PHYSICAL_INDEX", "6")
labels = ["gpu_uuid", "physical_index_zero_based", "display_slot_one_based"]
INFO = Gauge("speech_gpu_inventory_info", "Speech GPU identity", labels)
MATCH = Gauge("speech_gpu_inventory_match", "Configured index matches discovery", labels)
MEM = Gauge("speech_gpu_process_memory_bytes", "Speech process GPU memory", labels + ["process"])
UTIL = Gauge("speech_gpu_utilization_percent", "Sampled GPU utilization", labels)

def query(args):
    return subprocess.check_output(["nvidia-smi", *args], text=True, timeout=10).strip()

async def metrics(_):
    rows = query(["--query-gpu=uuid,index,utilization.gpu", "--format=csv,noheader,nounits"]).splitlines()
    uuid, index, util = next((x.strip() for x in row.split(",")) for row in rows if row.startswith(UUID))
    base = (uuid, index, os.getenv("SPEECH_GPU_DISPLAY_SLOT", "7"))
    INFO.labels(*base).set(1); MATCH.labels(*base).set(index == EXPECTED); UTIL.labels(*base).set(float(util))
    MEM.clear()
    try:
        for row in query([f"--id={UUID}", "--query-compute-apps=process_name,used_memory", "--format=csv,noheader,nounits"]).splitlines():
            process, mib = (x.strip() for x in row.rsplit(",", 1)); MEM.labels(*base, os.path.basename(process)[:64]).set(float(mib) * 1048576)
    except (subprocess.CalledProcessError, ValueError): pass
    return web.Response(body=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})

app=web.Application(); app.router.add_get("/metrics", metrics); app.router.add_get("/health", lambda _: web.json_response({"status":"ok"})); web.run_app(app, port=9400)
