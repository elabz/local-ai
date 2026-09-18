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
    # Host-RAM prompt cache bound in MiB (llama-server --cache-ram). Always passed:
    # left unset, each worker grows up to llama.cpp's 8192 MiB default, and six of
    # them OOM the 31 GB host. 8192 only makes that default explicit; compose sets
    # the qualified bound. 0 (may disable --cache-reuse) and -1 (unlimited) are refused.
    cache_ram: int = Field(default=8192, gt=0)
    cache_type_k: str = Field(default="q8_0")  # Quantize KV cache keys
    cache_type_v: str = Field(default="q8_0")  # Quantize KV cache values

    # llama.cpp server settings
    llama_server_host: str = Field(default="127.0.0.1")
    llama_server_port: int = Field(default=8081)
    extra_args: str = Field(default="")  # Extra llama-server args, e.g. "--jinja"
    # Pin the chat template instead of trusting the one embedded in the GGUF.
    # Set from models.yaml via GPU_N_CHAT_TEMPLATE (see chat-templates/).
    # Empty = use the GGUF's own template, which is the historical behaviour.
    chat_template_file: str = Field(default="")

    # Inference defaults
    default_temperature: float = Field(default=0.8)
    default_top_p: float = Field(default=0.95)
    default_top_k: int = Field(default=40)
    default_repeat_penalty: float = Field(default=1.1)
    default_max_tokens: int = Field(default=512)

    # Rate limiting
    max_concurrent_requests: int = Field(default=1)  # 1 slot = 4096 tokens per conversation
    request_timeout: int = Field(default=180)

    # Occupancy-aware watchdog
    watchdog_interval_seconds: float = Field(default=15.0)
    watchdog_idle_failures: int = Field(default=3)
    watchdog_stuck_request_seconds: float = Field(default=300.0)
    watchdog_restart_limit: int = Field(default=3)
    watchdog_restart_window_seconds: float = Field(default=900.0)
    watchdog_state_dir: str = Field(default="/var/lib/pea-gpu-state")
    max_in_flight_requests: int = Field(default=1)
    # Bounded admission queue: seconds a request may wait for a free inference
    # slot before the wrapper answers 429 BACKEND_BUSY. 0 = reject immediately.
    admission_wait_seconds: float = Field(default=60.0)
    # Upper bound for the Retry-After hint sent with a 429 BACKEND_BUSY.
    admission_retry_after_max_seconds: int = Field(default=30)

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
