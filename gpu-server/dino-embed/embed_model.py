"""DINOv2 visual embedder (image-only).

Loads a frozen DINOv2 backbone (ViT-L/14 with registers) via transformers
``AutoModel`` and returns one L2-normalized image embedding per input (the
pooled CLS representation). NO text encoder — text is rejected at the route.

!!! BEST-EFFORT / VERIFY ON GPU (openspec serve-dinov2-visual-embed task 3.2) !!!
Follows the standard DINOv2 usage (pooler_output, else CLS token), but has NOT
been run on a P104-100. Confirm on hardware: torch.cuda available, loads in fp32,
dimension == 1024 (ViT-L), VRAM fits co-located with chat (~7.5GB/8GB). If it
OOMs, switch MODEL_ID to `facebook/dinov2-with-registers-base` (768-d).
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from PIL import Image

from config import settings

logger = logging.getLogger(__name__)

_PRECISION_DTYPES = {"float32", "float16"}


class DinoEmbedder:
    def __init__(self):
        self.model = None
        self.processor = None
        self.device = None
        self.dimension: Optional[int] = None
        self._lock = threading.Lock()
        self._loaded = False

    def _resolve_dtype(self):
        import torch

        precision = settings.precision.lower()
        if precision == "bfloat16":
            raise ValueError(
                "bfloat16 is unsupported on Pascal (sm_61). Set PRECISION to "
                "float32 or float16."
            )
        if precision not in _PRECISION_DTYPES:
            raise ValueError(f"Unsupported precision '{settings.precision}'")
        return torch.float32 if precision == "float32" else torch.float16

    def load(self):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        dtype = self._resolve_dtype()
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        logger.info(
            f"Loading {settings.model_id} (precision={settings.precision}, "
            f"device={self.device}, cuda={torch.cuda.is_available()})"
        )
        self.processor = AutoImageProcessor.from_pretrained(settings.model_id)
        self.model = (
            AutoModel.from_pretrained(settings.model_id, torch_dtype=dtype)
            .to(self.device)
            .eval()
        )
        self.dimension = len(self._embed_batch([Image.new("RGB", (64, 64))])[0])
        self._loaded = True
        logger.info(f"Loaded. Embedding dimension = {self.dimension}, device = {self.device}")

    @property
    def loaded(self) -> bool:
        return self._loaded

    def _embed_batch(self, images: List[Image.Image]) -> List[List[float]]:
        import torch
        import torch.nn.functional as F

        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        with torch.no_grad():
            out = self.model(**inputs)
        # DINOv2: pooled CLS representation is the image-level embedding; fall
        # back to the CLS token of last_hidden_state if pooler_output is absent.
        emb = getattr(out, "pooler_output", None)
        if emb is None:
            emb = out.last_hidden_state[:, 0]
        emb = F.normalize(emb, p=2, dim=1)
        return emb.to(torch.float32).cpu().tolist()

    def _chunked(self, seq: List, size: int):
        for i in range(0, len(seq), size):
            yield seq[i : i + size]

    def embed_images(self, images: List[Image.Image]) -> List[List[float]]:
        if not images:
            return []
        with self._lock:
            results: List[List[float]] = []
            for chunk in self._chunked(images, settings.max_batch_size):
                results.extend(self._embed_batch(chunk))
            return results
