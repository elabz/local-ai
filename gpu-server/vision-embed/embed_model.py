"""Vision+text embedder for the aligned nomic-embed-v1.5 pair.

Loads ``nomic-embed-vision-v1.5`` (images) and ``nomic-embed-text-v1.5`` (text)
via transformers (``trust_remote_code``). Both produce L2-normalized 768-d
vectors in ONE shared space, so a text query and an image are directly
comparable (cosine) downstream.

!!! BEST-EFFORT / VERIFY ON GPU (openspec serve-photo-embeddings task 2.1) !!!
This follows Nomic's documented usage, but the exact post-processing of each
tower (image = L2-normalized CLS token; text = mean-pool -> layer_norm ->
L2-normalize, with a `search_query:` prefix) has NOT been run on a P104-100.
Confirm on hardware: (a) torch.cuda is available, (b) both towers load in fp32,
(c) dim == 768 for text AND image, (d) a text/image pair of the same concept
scores high cosine. Adjust pooling/normalization here if the smoke test fails.
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional

from PIL import Image

from config import settings

logger = logging.getLogger(__name__)

_PRECISION_DTYPES = {"float32", "float16"}


class VisionEmbedder:
    def __init__(self):
        self.vision_model = None
        self.image_processor = None
        self.text_model = None
        self.tokenizer = None
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
                "bfloat16 is unsupported on Pascal (sm_61). Set PRECISION to "
                "float32 or float16."
            )
        if precision not in _PRECISION_DTYPES:
            raise ValueError(f"Unsupported precision '{settings.precision}'")
        return torch.float32 if precision == "float32" else torch.float16

    def load(self):
        import torch
        from transformers import (
            AutoImageProcessor,
            AutoModel,
            AutoTokenizer,
        )

        dtype = self._resolve_dtype()
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        logger.info(
            f"Loading nomic vision+text pair (precision={settings.precision}, "
            f"device={self.device}, cuda={torch.cuda.is_available()})"
        )

        # Image tower
        self.image_processor = AutoImageProcessor.from_pretrained(
            settings.vision_model_id
        )
        self.vision_model = (
            AutoModel.from_pretrained(
                settings.vision_model_id,
                trust_remote_code=True,
                torch_dtype=dtype,
            )
            .to(self.device)
            .eval()
        )

        # Text tower
        self.tokenizer = AutoTokenizer.from_pretrained(settings.text_model_id)
        self.text_model = (
            AutoModel.from_pretrained(
                settings.text_model_id,
                trust_remote_code=True,
                torch_dtype=dtype,
            )
            .to(self.device)
            .eval()
        )

        # Probe + assert the shared dimension (resolves the spec's shared-space
        # requirement at runtime).
        tdim = len(self._embed_text_batch(["dimension probe"])[0])
        idim = len(self._embed_image_batch([Image.new("RGB", (64, 64))])[0])
        if tdim != idim:
            raise RuntimeError(
                f"text dim {tdim} != image dim {idim} — not a shared space; "
                "check model pair / post-processing"
            )
        self.dimension = tdim
        self._loaded = True
        logger.info(f"Loaded. Shared embedding dimension = {self.dimension}")

    @property
    def loaded(self) -> bool:
        return self._loaded

    # ---- inference ---------------------------------------------------------
    @staticmethod
    def _mean_pool(last_hidden, attention_mask):
        import torch

        mask = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
        return torch.sum(last_hidden * mask, 1) / torch.clamp(mask.sum(1), min=1e-9)

    def _embed_text_batch(self, texts: List[str]) -> List[List[float]]:
        import torch
        import torch.nn.functional as F

        prefixed = [f"{settings.text_query_prefix}{t}" for t in texts]
        enc = self.tokenizer(
            prefixed,
            padding=True,
            truncation=True,
            max_length=settings.max_text_tokens,
            return_tensors="pt",
        ).to(self.device)
        with torch.no_grad():
            out = self.text_model(**enc)
        emb = self._mean_pool(out[0], enc["attention_mask"])
        # nomic-embed-text-v1.5 recommended post-processing: layer_norm then L2.
        emb = F.layer_norm(emb, normalized_shape=(emb.shape[1],))
        emb = F.normalize(emb, p=2, dim=1)
        return emb.to(torch.float32).cpu().tolist()

    def _embed_image_batch(self, images: List[Image.Image]) -> List[List[float]]:
        import torch
        import torch.nn.functional as F

        inputs = self.image_processor(images, return_tensors="pt").to(self.device)
        with torch.no_grad():
            out = self.vision_model(**inputs)
        # nomic-embed-vision-v1.5: take the CLS token, then L2-normalize.
        emb = F.normalize(out.last_hidden_state[:, 0], p=2, dim=1)
        return emb.to(torch.float32).cpu().tolist()

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
