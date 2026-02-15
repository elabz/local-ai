"""GPU Server configuration."""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Server configuration from environment variables."""

    # Server settings
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    server_id: str = Field(default="gpu-1")

    # Model configuration
    model_path: str = Field(default="/models/model.gguf")
    n_gpu_layers: int = Field(default=33)
    n_ctx: int = Field(default=8192)  # Total context budget per GPU (increased from 4096)
    n_batch: int = Field(default=128)  # Reduced for 2-core CPU (was 512)
    n_ubatch: int = Field(default=128)  # Increased from 64 to match n_batch - GPU underutilization fix
    n_threads: int = Field(default=2)  # Match physical cores on 2-core CPU (was 4)

    # KV Cache optimization for faster TTFT
    cache_reuse: int = Field(default=256)  # Enable prompt caching
    cache_type_k: str = Field(default="q8_0")  # Quantize KV cache keys
    cache_type_v: str = Field(default="q8_0")  # Quantize KV cache values

    # llama.cpp server settings
    llama_server_host: str = Field(default="127.0.0.1")
    llama_server_port: int = Field(default=8081)
    extra_args: str = Field(default="")  # Extra llama-server args, e.g. "--jinja"

    # Inference defaults
    default_temperature: float = Field(default=0.8)
    default_top_p: float = Field(default=0.95)
    default_top_k: int = Field(default=40)
    default_repeat_penalty: float = Field(default=1.1)
    default_max_tokens: int = Field(default=512)

    # Rate limiting
    max_concurrent_requests: int = Field(default=1)  # 1 slot = 4096 tokens per conversation
    request_timeout: int = Field(default=120)

    # Metrics
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9091)

    # Logging
    log_level: str = Field(default="INFO")

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Ignore Langfuse and other env vars not defined here


settings = Settings()
