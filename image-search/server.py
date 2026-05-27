"""Image-search service - FastAPI app.

Thin orchestration layer (design Decision 5): embeddings come from the
heartcode-embed HTTP endpoint, storage/ANN from Elasticsearch. On startup it
wires the two clients, reads the index's vector dimension (creating the index
from `es_mapping.json` if missing and auto-create is on), and records it for the
shared-space consistency guard.
"""

import json
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from embed_client import EmbedClient
from es_client import ESClient
from metrics import ready_gauge, start_metrics_server
from routes import router

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _load_mapping() -> dict:
    path = settings.mapping_file
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(__file__), path)
    with open(path) as f:
        mapping = json.load(f)
    mapping.pop("_comment", None)
    return mapping


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.enable_metrics:
        start_metrics_server(settings.metrics_port)

    app.state.embed = EmbedClient()
    app.state.es = ESClient()
    app.state.index_dims = None
    ready_gauge.set(0)

    # Tolerate ES being unavailable at boot: start anyway so /health can report
    # degraded rather than crash-looping.
    try:
        dims = await app.state.es.index_dims()
        if dims is None and settings.auto_create_index:
            logger.info(f"Index '{settings.es_index}' missing; creating from mapping")
            await app.state.es.create_index(_load_mapping())
            dims = await app.state.es.index_dims()
        app.state.index_dims = dims
        if dims is not None and dims != settings.embed_dim:
            logger.warning(
                f"Index dims {dims} != embed_dim {settings.embed_dim}; "
                "queries will be rejected until a re-index aligns them"
            )
        ready = dims is not None and dims == settings.embed_dim
        ready_gauge.set(1 if ready else 0)
        logger.info(f"Image-search ready={ready} (index_dims={dims})")
    except Exception as e:
        logger.warning(f"Startup ES check failed (continuing degraded): {e}")

    yield

    await app.state.embed.aclose()
    await app.state.es.aclose()
    ready_gauge.set(0)


app = FastAPI(
    title="HeartCode Image Search",
    description="Cross-modal (text→image, image→image) search over Elasticsearch",
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
    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=True,
        workers=1,
    )
