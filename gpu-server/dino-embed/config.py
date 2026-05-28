"""DINOv2 visual-embedding service configuration (Pydantic settings).

Serves DINOv2 (ViT-L/14 with registers) image embeddings for fine-grained
visual / same-object similarity (image-only, no text) over an OpenAI
/v1/embeddings API. Mirrors gpu-server/vision-embed/config.py but loads a single
frozen DINOv2 backbone via transformers AutoModel. Runs fp32 on Pascal P104-100.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Server configuration from environment variables."""

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    server_id: str = Field(default="embed-dino-1")
    log_level: str = Field(default="INFO")

    # Model — DINOv2 ViT-L/14 with registers (1024-d), native in transformers
    # (no trust_remote_code). ViT-B/14 (`facebook/dinov2-with-registers-base`,
    # 768-d) is the VRAM fallback if L OOMs when co-located with chat.
    model_id: str = Field(default="facebook/dinov2-with-registers-large")
    models_dir: str = Field(default="/models")

    # Precision — Pascal (sm_61): never bf16. fp32 is the safe default for the
    # frozen ViT; float16 is available but crippled on Pascal.
    precision: str = Field(default="float32")
    attn_implementation: str = Field(default="eager")  # no flash-attn on Pascal

    # Input safety caps (co-located on an 8GB card — bound activation memory).
    max_image_edge: int = Field(default=1024)
    max_batch_size: int = Field(default=4)
    max_input_items: int = Field(default=64)
    max_image_bytes: int = Field(default=10 * 1024 * 1024)
    image_fetch_timeout: int = Field(default=10)
    allow_image_urls: bool = Field(default=True)

    # Startup (first run may download the checkpoint)
    model_load_timeout: int = Field(default=600)

    # Metrics
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9091)

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"
        protected_namespaces = ()


settings = Settings()
