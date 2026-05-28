"""Multimodal Embedding Server - FastAPI wrapper for nomic-embed-multimodal-3b.

PyTorch + colpali-engine (BiQwen2_5) service that mirrors the gpu-server FastAPI
pattern (server.py/routes.py/metrics.py) but loads the model in-process instead
of spawning llama.cpp. Serves an OpenAI-compatible /v1/embeddings for text and
images on Pascal P104-100 GPUs.
"""

import asyncio
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes import router
from embed_model import DinoEmbedder
from metrics import start_metrics_server, model_loaded_gauge

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

embedder: DinoEmbedder = DinoEmbedder()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.enable_metrics:
        start_metrics_server(settings.metrics_port)
        logger.info(f"Metrics server started on port {settings.metrics_port}")

    # Make the model snapshot dir the HF cache so pre-downloaded weights (adapter
    # + Qwen2.5-VL base) are found offline.
    os.environ.setdefault("HF_HOME", settings.models_dir)
    os.environ.setdefault("HF_HUB_CACHE", settings.models_dir)

    # Load the model with a timeout (first run may download the base model).
    logger.info("Loading multimodal embedding model...")
    try:
        await asyncio.wait_for(
            asyncio.to_thread(embedder.load),
            timeout=settings.model_load_timeout,
        )
    except Exception as e:
        logger.error(f"Model failed to load: {e}")
        model_loaded_gauge.set(0)
        sys.exit(1)

    model_loaded_gauge.set(1)
    app.state.embedder = embedder
    logger.info(
        f"Embedding server {settings.server_id} ready "
        f"(dim={embedder.dimension}, precision={settings.precision})"
    )

    yield

    logger.info("Shutting down embedding server...")
    model_loaded_gauge.set(0)


app = FastAPI(
    title="HeartCode DINOv2 Visual Embedding Server",
    description="DINOv2 (ViT-L/14 +reg) image-only visual-similarity embeddings for Pascal GPUs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def handle_signal(signum, frame):
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Single worker: one in-process GPU model, no forking.
    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=True,
        workers=1,
    )
