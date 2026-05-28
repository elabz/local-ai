"""Vision-embed service configuration (Pydantic settings from env vars).

Serves the natural-photo embedding pair nomic-embed-vision-v1.5 (images) +
nomic-embed-text-v1.5 (text) in one shared 768-d space, over an OpenAI
/v1/embeddings API. Mirrors gpu-server/multimodal-embed/config.py but loads the
CLIP-style nomic pair via transformers (trust_remote_code) instead of the
3B BiQwen2.5 — much lighter, runs in fp32 on Pascal P104-100.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Server configuration from environment variables."""

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    server_id: str = Field(default="embed-vision-1")
    log_level: str = Field(default="INFO")

    # Models — the aligned nomic pair (one shared 768-d space). Both are
    # trust_remote_code models; download-models.sh should snapshot them into
    # models_dir so first load is offline.
    vision_model_id: str = Field(default="nomic-ai/nomic-embed-vision-v1.5")
    text_model_id: str = Field(default="nomic-ai/nomic-embed-text-v1.5")
    # Cosmetic name reported in /v1/models and the embeddings response.
    model_id: str = Field(default="heartcode-embed-vision")
    models_dir: str = Field(default="/models")

    # Precision — Pascal P104-100 (sm_61): NO bf16, crippled fp16. These ViT/BERT
    # towers are small, so float32 is the correctness-safe default and fast enough.
    precision: str = Field(default="float32")
    # No flash-attn on Pascal; the nomic remote code falls back to standard
    # attention when flash-attn is absent (we do not install it).
    attn_implementation: str = Field(default="eager")

    # Text is embedded as a SEARCH QUERY (this service backs text→image photo
    # search). nomic-embed-text expects a task prefix; "" disables it.
    text_query_prefix: str = Field(default="search_query: ")
    max_text_tokens: int = Field(default=512)

    # Input safety caps (bound activation memory / payload size).
    max_image_edge: int = Field(default=1024)
    max_batch_size: int = Field(default=8)
    max_input_items: int = Field(default=64)
    max_image_bytes: int = Field(default=10 * 1024 * 1024)
    image_fetch_timeout: int = Field(default=10)
    allow_image_urls: bool = Field(default=True)

    # Startup (first run may download the two model snapshots).
    model_load_timeout: int = Field(default=900)

    # Metrics
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9091)

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"
        protected_namespaces = ()


settings = Settings()
