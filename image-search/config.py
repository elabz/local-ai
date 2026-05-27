"""Image-search service configuration (Pydantic settings from env vars).

Mirrors the gpu-server / multimodal-embed config pattern. This service is
model-agnostic: it calls an OpenAI-compatible /v1/embeddings endpoint
(`heartcode-embed` via LiteLLM) and an Elasticsearch cluster, both addressed by
config. The default dimension (768) matches the chosen `nomic-embed-vision-v1.5`
+ `nomic-embed-text-v1.5` pair; change EMBED_DIM if the model changes.
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Server configuration from environment variables."""

    # --- Server ---
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8200)
    server_id: str = Field(default="image-search-1")
    log_level: str = Field(default="INFO")

    # --- Embedding endpoint (heartcode-embed-vision via LiteLLM, OpenAI-compatible) ---
    embed_base_url: str = Field(default="http://192.168.0.152:4000/v1")
    embed_model: str = Field(default="heartcode-embed-vision")
    embed_api_key: str = Field(default="")
    embed_timeout: float = Field(default=120.0)
    # Embedding dimension expected by the index. Vectors of any other length are
    # rejected as a shared-space mismatch (spec: Shared-space consistency).
    embed_dim: int = Field(default=768)
    # L2-normalize vectors at index and query time (spec: Image ingestion).
    normalize: bool = Field(default=True)
    # nomic text-retrieval task prefix applied to TEXT QUERIES only (images get
    # none). Set to "" for models that need no prefix.
    text_query_prefix: str = Field(default="search_query: ")

    # --- Elasticsearch ---
    es_url: str = Field(default="http://localhost:9200")
    es_index: str = Field(default="image-embeddings")
    es_vector_field: str = Field(default="embedding")
    es_id_field: str = Field(default="image_id")
    # Auth: prefer an API key; fall back to basic auth if username/password set.
    es_api_key: str = Field(default="")
    es_username: str = Field(default="")
    es_password: str = Field(default="")
    es_timeout: float = Field(default=30.0)
    es_verify_certs: bool = Field(default=True)
    # On startup, create the index from `mapping_file` if it does not exist.
    auto_create_index: bool = Field(default=True)
    mapping_file: str = Field(default="es_mapping.json")

    # --- Search defaults ---
    default_top_k: int = Field(default=10)
    max_top_k: int = Field(default=100)
    # ES kNN candidate pool (>= k); larger = better recall, slower.
    num_candidates: int = Field(default=100)

    # --- Image input safety caps (cheap, no decode) ---
    max_image_bytes: int = Field(default=10 * 1024 * 1024)  # 10 MB per image
    max_input_items: int = Field(default=64)  # reject oversized ingest batches

    # --- Metrics ---
    enable_metrics: bool = Field(default=True)
    metrics_port: int = Field(default=9091)

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"
        protected_namespaces = ()


settings = Settings()
