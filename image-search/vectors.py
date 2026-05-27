"""Vector helpers: L2 normalization and dimension checks.

Pure-Python (no numpy dep) — vectors are small (768-d) and these run per
request. Keeping the dependency surface minimal matches the lightweight
FastAPI services in this repo.
"""

from __future__ import annotations

import math
from typing import List


class DimensionMismatch(ValueError):
    """Raised when an embedding's length does not match the index dimension."""

    def __init__(self, got: int, expected: int):
        self.got = got
        self.expected = expected
        super().__init__(
            f"embedding dimension {got} does not match index dimension "
            f"{expected}; a re-index is required after a model/dimension change"
        )


def l2_normalize(vec: List[float]) -> List[float]:
    """Return the unit-length vector (cosine == dot product after this)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


def check_dim(vec: List[float], expected: int) -> None:
    """Raise DimensionMismatch unless len(vec) == expected."""
    if len(vec) != expected:
        raise DimensionMismatch(len(vec), expected)
