#!/usr/bin/env python3
"""Healthcheck that also keeps the configured Speaches STT model resident."""

import json
import os
from urllib.parse import quote
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:8000"
MODEL_ID = os.environ["STT_MODEL_ID"]


def request(path: str, method: str = "GET") -> bytes:
    with urlopen(Request(f"{BASE_URL}{path}", method=method), timeout=55) as response:
        return response.read()


request("/health")
loaded = json.loads(request("/api/ps"))["models"]
if MODEL_ID not in loaded:
    request(f"/api/ps/{quote(MODEL_ID, safe='')}", method="POST")
    loaded = json.loads(request("/api/ps"))["models"]
if MODEL_ID not in loaded:
    raise SystemExit(f"STT model is not resident: {MODEL_ID}")
