"""Multimodal embedding server configuration.

Reads settings from environment variables (Pydantic). Mirrors the pattern of
gpu-server/config.py but for the PyTorch + colpali-engine multimodal embedder
(nomic-embed-multimodal-3b on Qwen2.5-VL-3B) instead of llama.cpp.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Server configuration from environment variables."""

    # Server settings
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    server_id: str = Field(default="embed-mm-1")

    # Model configuration
    # The adapter repo (nomic) is a PEFT/LoRA adapter on the Qwen2.5-VL-3B base.
    # colpali-engine's BiQwen2_5.from_pretrained resolves the base from
    # adapter_config.json; download-models.sh snapshots BOTH into models_dir.
    model_id: str = Field(default="nomic-ai/nomic-embed-multimodal-3b")
    base_model_id: str = Field(default="Qwen/Qwen2.5-VL-3B-Instruct")
    # HF cache / snapshot root. Mounted read-write so first load can resolve the
    # base model if it was not pre-snapshotted.
    models_dir: str = Field(default="/models")

    # Precision — Pascal P104-100 (sm_61) has NO bf16 and crippled fp16.
    # Must be "float32" or "float16"; NEVER "bfloat16". Default chosen by the
    # on-hardware benchmark (see openspec change tasks 4.x). Default float32 is
    # the correctness-safe baseline; float16 halves VRAM (fits 1 card) but is
    # ~1:64 throughput on Pascal.
    precision: str = Field(default="float32")

    # device_map for HF/accelerate. Empty => auto-pick: single visible GPU loads
    # on cuda:0; multiple visible GPUs shard via "auto". Override with an
    # explicit value ("cuda:0", "auto") if needed. CPU offload is disabled
    # (no-AVX host) by capping CPU memory to 0 when sharding.
    device_map: str = Field(default="")

    # Attention backend — flash-attn (FA2) needs sm_80; Pascal cannot use it.
    attn_implementation: str = Field(default="eager")

    # Input safety caps (eager attention activation memory grows with image
    # tokens; bound it to avoid OOM).
    max_image_edge: int = Field(default=1024)  # px; larger images are downscaled
    max_batch_size: int = Field(default=4)     # items per forward pass
    max_input_items: int = Field(default=64)   # reject oversized request arrays
    max_image_bytes: int = Field(default=10 * 1024 * 1024)  # 10 MB per image
    image_fetch_timeout: int = Field(default=10)  # seconds for http(s) image URLs
    allow_image_urls: bool = Field(default=True)  # allow {"image": "http(s)://..."}

    # Startup
    model_load_timeout: int = Field(default=1800)  # seconds (first run downloads base)

    # Metrics
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9091)

    # Logging
    log_level: str = Field(default="INFO")

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"
        # model_id / model_load_timeout would otherwise warn about Pydantic v2's
        # protected "model_" namespace.
        protected_namespaces = ()


settings = Settings()
