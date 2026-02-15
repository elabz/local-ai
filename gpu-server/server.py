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
from metrics import start_metrics_server, model_loaded_gauge

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
        "--mlock",
        "--cache-reuse", str(settings.cache_reuse),  # Enable prompt caching for faster TTFT
        "--cache-type-k", settings.cache_type_k,  # Quantize KV cache
        "--cache-type-v", settings.cache_type_v,
    ]

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

    # Store client in app state
    app.state.llama_client = llama_client

    logger.info(f"GPU Server {settings.server_id} started successfully")

    yield

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
