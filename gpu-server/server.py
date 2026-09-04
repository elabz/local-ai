"""GPU Server - FastAPI wrapper for llama.cpp."""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes import router
from llama_client import LlamaClient
from availability import BackendAvailability
from metrics import (
    start_metrics_server, model_loaded_gauge, record_gpu_readiness,
    record_backend_state, backend_in_flight_requests, watchdog_probe_failures_total,
    watchdog_restart_decisions_total, llama_child_exits_total, backend_recovery_seconds,
)
from gpu_health import GPUHealthMonitor, GPUReadiness, configured_gpu_health_enabled, probe_nvidia_smi

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global llama.cpp process
llama_process: Optional[subprocess.Popen] = None
llama_client: Optional[LlamaClient] = None


def start_llama_server() -> subprocess.Popen:
    """Start the llama.cpp server process."""
    cmd = [
        "llama-server",
        "--model", settings.model_path,
        "--host", settings.llama_server_host,
        "--port", str(settings.llama_server_port),
        "--n-gpu-layers", str(settings.n_gpu_layers),
        "--ctx-size", str(settings.n_ctx),
        "--override-kv", f"llama.context_length=int:{settings.n_ctx}",  # Override model metadata
        "--batch-size", str(settings.n_batch),
        "--ubatch-size", str(settings.n_ubatch),  # Micro-batch for better CPU handling
        "--threads", str(settings.n_threads),
        "--parallel", str(settings.max_concurrent_requests),
        "--cont-batching",
        "--cache-reuse", str(settings.cache_reuse),  # Enable prompt caching for faster TTFT
        "--cache-type-k", settings.cache_type_k,  # Quantize KV cache
        "--cache-type-v", settings.cache_type_v,
    ]

    # Pin the chat template when models.yaml specifies one. --jinja is implied:
    # a .jinja template file is only honoured with the jinja engine enabled.
    if settings.chat_template_file:
        if not os.path.isfile(settings.chat_template_file):
            raise RuntimeError(
                f"chat template not found: {settings.chat_template_file} "
                "(is chat-templates/ mounted into the container?)"
            )
        cmd.extend(["--chat-template-file", settings.chat_template_file])
        if "--jinja" not in (settings.extra_args or ""):
            cmd.append("--jinja")

    # Append extra args (e.g. --jinja for Llama 3.1 chat templates)
    if settings.extra_args:
        cmd.extend(settings.extra_args.split())

    logger.info(f"Starting llama.cpp server: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    return process


async def wait_for_llama_server(client: LlamaClient, timeout: int = 300) -> bool:
    """Wait for llama.cpp server to be ready."""
    import httpx

    start_time = asyncio.get_event_loop().time()

    while asyncio.get_event_loop().time() - start_time < timeout:
        try:
            health = await client.health_check()
            if health.get("status") == "ok":
                logger.info("llama.cpp server is ready")
                model_loaded_gauge.set(1)
                return True
        except Exception:
            pass

        await asyncio.sleep(1)

    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global llama_process, llama_client

    # Start metrics server
    if settings.enable_metrics:
        start_metrics_server(settings.metrics_port)
        logger.info(f"Metrics server started on port {settings.metrics_port}")

    # Check if model exists
    if not os.path.exists(settings.model_path):
        logger.error(f"Model not found: {settings.model_path}")
        sys.exit(1)

    availability = BackendAvailability(
        idle_failure_limit=settings.watchdog_idle_failures,
        stuck_request_seconds=settings.watchdog_stuck_request_seconds,
        restart_limit=settings.watchdog_restart_limit,
        restart_window_seconds=settings.watchdog_restart_window_seconds,
        restart_state_path=os.path.join(settings.watchdog_state_dir, f"{settings.server_id}.json"),
        max_in_flight=settings.max_in_flight_requests,
        on_transition=record_backend_state,
    )
    app.state.backend_availability = availability
    record_backend_state("starting", "starting")
    startup_started = asyncio.get_event_loop().time()

    # Start llama.cpp server
    llama_process = start_llama_server()

    # Create client
    llama_client = LlamaClient(
        host=settings.llama_server_host,
        port=settings.llama_server_port,
    )

    # Wait for server to be ready
    if not await wait_for_llama_server(llama_client):
        logger.error("llama.cpp server failed to start")
        if llama_process:
            llama_process.terminate()
        sys.exit(1)
    availability.probe_succeeded()
    backend_recovery_seconds.observe(asyncio.get_event_loop().time() - startup_started)

    # Store client in app state
    app.state.llama_client = llama_client
    expected_uuid = os.getenv("EXPECTED_GPU_UUID", os.getenv("NVIDIA_VISIBLE_DEVICES", ""))
    readiness = GPUReadiness(enabled=configured_gpu_health_enabled(), on_transition=record_gpu_readiness)
    monitor = GPUHealthMonitor(readiness, lambda: probe_nvidia_smi(expected_uuid))
    app.state.gpu_readiness = readiness
    app.state.gpu_health_monitor = monitor
    if readiness.enabled:
        monitor.check()
        monitor.check()

    logger.info(f"GPU Server {settings.server_id} started successfully")

    # Start background watchdog to exit if llama.cpp becomes unhealthy
    async def watchdog():
        """Monitor llama.cpp process and exit if it dies or model unloads."""
        last_gpu_reason = None

        while True:
            await asyncio.sleep(settings.watchdog_interval_seconds)

            # GPU query/identity failures withdraw readiness but do not trigger
            # process exit: a persistent PCI fault would otherwise create an
            # unbounded Docker restart loop. Child failure retains the bounded
            # three-strike recreation behavior below.
            if readiness.enabled:
                gpu_snapshot = monitor.check()
                if gpu_snapshot.state != "ready" and gpu_snapshot.reason != last_gpu_reason:
                    logger.warning("GPU readiness unavailable: %s", gpu_snapshot.reason)
                last_gpu_reason = None if gpu_snapshot.state == "ready" else gpu_snapshot.reason

            # Check if the process itself is dead
            if llama_process and llama_process.poll() is not None:
                logger.error(
                    f"llama.cpp process exited with code {llama_process.returncode}"
                )
                model_loaded_gauge.set(0)
                llama_child_exits_total.inc()
                decision = availability.child_exited()
                watchdog_restart_decisions_total.labels(
                    decision="restart" if decision.restart else "suppress", reason=decision.reason,
                ).inc()
                logger.error("watchdog_decision=%s reason=%s", "restart" if decision.restart else "suppress", decision.reason)
                if decision.restart:
                    os._exit(1)
                continue

            # Check if model is still loaded
            try:
                health = await llama_client.health_check()
                if health.get("status") == "ok":
                    availability.probe_succeeded()
                else:
                    raise RuntimeError("non_ok_health_status")
            except Exception:
                decision = availability.probe_failed(child_alive=True)
                snapshot = availability.snapshot()
                backend_in_flight_requests.set(snapshot.in_flight)
                watchdog_probe_failures_total.labels(reason=decision.reason).inc()
                watchdog_restart_decisions_total.labels(
                    decision="restart" if decision.restart else "continue", reason=decision.reason,
                ).inc()
                logger.warning(
                    "watchdog_probe_failed state=%s reason=%s in_flight=%d failures=%d decision=%s",
                    snapshot.state, snapshot.reason, snapshot.in_flight,
                    snapshot.probe_failures, "restart" if decision.restart else "continue",
                )
                if not decision.restart:
                    continue
                model_loaded_gauge.set(0)
                os._exit(1)

    watchdog_task = asyncio.create_task(watchdog())

    yield

    watchdog_task.cancel()
    monitor.stop()

    # Cleanup
    logger.info("Shutting down GPU server...")
    model_loaded_gauge.set(0)

    if llama_process:
        llama_process.terminate()
        try:
            llama_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            llama_process.kill()


# Create FastAPI app
app = FastAPI(
    title="HeartCode GPU Server",
    description="llama.cpp inference server for Pascal GPUs",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)


def handle_signal(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, shutting down...")
    if llama_process:
        llama_process.terminate()
    sys.exit(0)


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Run server
    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=True,
    )
