"""Input parsing for the multimodal /v1/embeddings endpoint.

The OpenAI /v1/embeddings schema only defines text ``input``. We extend it with
a documented convention (design D5):

  - A plain string is embedded as TEXT, UNLESS it is a ``data:image/...;base64``
    URI, in which case it is treated as an image.
  - An object ``{"image": "<value>"}`` is an image. ``<value>`` may be a
    ``data:`` URI, raw base64, or an http(s) URL (if allowed).
  - An object ``{"text": "<string>"}`` is text.

Each parsed item is returned as an ``InputItem`` recording its original index,
modality, and payload (the text string or a decoded PIL image). Malformed image
items raise ``ImageInputError`` (mapped to HTTP 400 by the route), naming the
offending index, and never crash the server.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Union

from PIL import Image

from config import settings

_DATA_URI_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,", re.IGNORECASE)
_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class ImageInputError(ValueError):
    """Raised when an item declared as an image cannot be decoded."""

    def __init__(self, index: int, message: str):
        self.index = index
        super().__init__(f"input[{index}]: {message}")


@dataclass
class InputItem:
    index: int
    modality: str  # "text" | "image"
    text: Optional[str] = None
    image: Optional[Image.Image] = None


def _looks_like_image_string(value: str) -> bool:
    """A bare string is an image only if it is a data:image URI."""
    return bool(_DATA_URI_RE.match(value.strip()))


def _decode_base64_image(index: int, payload: str) -> Image.Image:
    raw = payload.strip()
    if _DATA_URI_RE.match(raw):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ImageInputError(index, f"invalid base64 image data ({e})")
    return _open_image(index, data)


def _fetch_url_image(index: int, url: str) -> Image.Image:
    if not settings.allow_image_urls:
        raise ImageInputError(index, "image URLs are not allowed on this server")
    import httpx

    try:
        with httpx.Client(timeout=settings.image_fetch_timeout, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.content
    except Exception as e:  # network, status, timeout
        raise ImageInputError(index, f"could not fetch image URL ({e})")
    if len(data) > settings.max_image_bytes:
        raise ImageInputError(index, "fetched image exceeds max_image_bytes")
    return _open_image(index, data)


def _open_image(index: int, data: bytes) -> Image.Image:
    if len(data) > settings.max_image_bytes:
        raise ImageInputError(index, "image exceeds max_image_bytes")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise ImageInputError(index, f"undecodable image ({e})")
    img = img.convert("RGB")
    return _downscale(img)


def _downscale(img: Image.Image) -> Image.Image:
    """Bound the longest edge to cap image-token / activation memory."""
    cap = settings.max_image_edge
    w, h = img.size
    longest = max(w, h)
    if longest > cap:
        scale = cap / float(longest)
        img = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    return img


def _decode_image_value(index: int, value: str) -> Image.Image:
    value = value.strip()
    if _HTTP_URL_RE.match(value):
        return _fetch_url_image(index, value)
    # data: URI or raw base64
    return _decode_base64_image(index, value)


def parse_input(raw_input: Union[str, dict, List[Any]]) -> List[InputItem]:
    """Normalize the request ``input`` into ordered, classified items.

    Raises ``ImageInputError`` for malformed image items and ``ValueError`` for
    structurally invalid input (both -> HTTP 400 in the route).
    """
    if raw_input is None:
        raise ValueError("'input' is required")

    items = raw_input if isinstance(raw_input, list) else [raw_input]
    if len(items) == 0:
        raise ValueError("'input' must contain at least one item")
    if len(items) > settings.max_input_items:
        raise ValueError(
            f"'input' has {len(items)} items, exceeds max_input_items "
            f"({settings.max_input_items})"
        )

    parsed: List[InputItem] = []
    for i, item in enumerate(items):
        if isinstance(item, str):
            if _looks_like_image_string(item):
                parsed.append(InputItem(i, "image", image=_decode_image_value(i, item)))
            else:
                parsed.append(InputItem(i, "text", text=item))
        elif isinstance(item, dict):
            if "image" in item:
                val = item["image"]
                if not isinstance(val, str):
                    raise ImageInputError(i, "'image' must be a string (data URI, base64, or url)")
                parsed.append(InputItem(i, "image", image=_decode_image_value(i, val)))
            elif "text" in item:
                val = item["text"]
                if not isinstance(val, str):
                    raise ValueError(f"input[{i}]: 'text' must be a string")
                parsed.append(InputItem(i, "text", text=val))
            else:
                raise ValueError(f"input[{i}]: object must contain 'text' or 'image'")
        else:
            raise ValueError(
                f"input[{i}]: unsupported item type {type(item).__name__}; "
                "expected string or object"
            )

    return parsed
