"""Multimodal embedder backed by nomic-embed-multimodal-3b via colpali-engine.

Loads ``BiQwen2_5`` + ``BiQwen2_5_Processor`` (single dense vector / bi-encoder)
on Pascal P104-100 GPUs. Precision is forced to float32/float16 from config
(never bfloat16), and attention is eager (no flash-attn on sm_61).

Text and images are embedded into the SAME latent space: text via the processor
query branch, images via the image branch. Inference is serialized with a lock
(single GPU model) and run in a worker thread so the FastAPI event loop stays
responsive.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from PIL import Image

from config import settings

logger = logging.getLogger(__name__)

_PRECISION_DTYPES = {"float32": "float32", "float16": "float16"}


class MultimodalEmbedder:
    def __init__(self):
        self.model = None
        self.processor = None
        self.device = None
        self.dimension: Optional[int] = None
        self._lock = threading.Lock()
        self._loaded = False

    # ---- loading -----------------------------------------------------------
    def _resolve_dtype(self):
        import torch

        precision = settings.precision.lower()
        if precision == "bfloat16":
            raise ValueError(
                "bfloat16 is unsupported on Pascal (sm_61). Set PRECISION "
                "to float32 or float16."
            )
        if precision not in _PRECISION_DTYPES:
            raise ValueError(f"Unsupported precision '{settings.precision}'")
        return torch.float32 if precision == "float32" else torch.float16

    def _resolve_device_map(self):
        """Pick device_map: single visible GPU -> cuda:0; multiple -> sharded.

        CPU offload is disabled (no-AVX host); if weights do not fit the assigned
        GPU(s) the load fails loudly with CUDA OOM rather than silently spilling
        to CPU.
        """
        import torch

        if settings.device_map:
            return settings.device_map

        n = torch.cuda.device_count()
        if n <= 1:
            return "cuda:0"
        # Shard across all visible GPUs, no CPU offload.
        return "auto"

    def load(self):
        import torch
        from colpali_engine.models import BiQwen2_5, BiQwen2_5_Processor

        dtype = self._resolve_dtype()
        device_map = self._resolve_device_map()
        logger.info(
            f"Loading {settings.model_id} (precision={settings.precision}, "
            f"device_map={device_map}, attn={settings.attn_implementation}, "
            f"cuda_devices={torch.cuda.device_count()})"
        )

        from_pretrained_kwargs = dict(
            torch_dtype=dtype,
            device_map=device_map,
            attn_implementation=settings.attn_implementation,
        )
        # When sharding across >1 GPU, forbid CPU offload (no-AVX host).
        if device_map == "auto" and torch.cuda.device_count() > 1:
            max_memory: dict = {
                i: f"{self._gpu_mem_budget_gib(i)}GiB"
                for i in range(torch.cuda.device_count())
            }
            max_memory["cpu"] = "0GiB"
            from_pretrained_kwargs["max_memory"] = max_memory

        self.model = BiQwen2_5.from_pretrained(
            settings.model_id, **from_pretrained_kwargs
        ).eval()
        self.processor = BiQwen2_5_Processor.from_pretrained(settings.model_id)
        self.device = next(self.model.parameters()).device

        # Warm up + record the embedding dimension (resolves spec O2 at runtime).
        self.dimension = self._probe_dimension()
        self._loaded = True
        logger.info(
            f"Model loaded. Embedding dimension = {self.dimension}, "
            f"device = {self.device}"
        )

    @staticmethod
    def _gpu_mem_budget_gib(idx: int) -> int:
        import torch

        total = torch.cuda.get_device_properties(idx).total_memory
        # Leave ~1GiB headroom per card for activations/CUDA context.
        return max(1, int(total / (1024 ** 3)) - 1)

    def _probe_dimension(self) -> int:
        vec = self._embed_text_batch(["dimension probe"])[0]
        return len(vec)

    @property
    def loaded(self) -> bool:
        return self._loaded

    # ---- inference ---------------------------------------------------------
    def _to_vectors(self, embeddings) -> List[List[float]]:
        import torch

        # Bi-encoder returns (batch, dim). Be defensive: mean-pool if a 3D
        # (batch, seq, dim) tensor ever comes back.
        if embeddings.dim() == 3:
            embeddings = embeddings.mean(dim=1)
        return embeddings.to(torch.float32).cpu().tolist()

    def _embed_text_batch(self, texts: List[str]) -> List[List[float]]:
        import torch

        batch = self.processor.process_queries(texts).to(self.device)
        with torch.no_grad():
            out = self.model(**batch)
        return self._to_vectors(out)

    def _embed_image_batch(self, images: List[Image.Image]) -> List[List[float]]:
        import torch

        batch = self.processor.process_images(images).to(self.device)
        with torch.no_grad():
            out = self.model(**batch)
        return self._to_vectors(out)

    def _chunked(self, seq: List, size: int):
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        with self._lock:
            results: List[List[float]] = []
            for chunk in self._chunked(texts, settings.max_batch_size):
                results.extend(self._embed_text_batch(chunk))
            return results

    def embed_images(self, images: List[Image.Image]) -> List[List[float]]:
        if not images:
            return []
        with self._lock:
            results: List[List[float]] = []
            for chunk in self._chunked(images, settings.max_batch_size):
                results.extend(self._embed_image_batch(chunk))
            return results
