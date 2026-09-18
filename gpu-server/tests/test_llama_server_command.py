"""The llama-server command line always bounds the host-RAM prompt cache.

Without --cache-ram, llama.cpp build 8027 lets each worker grow an 8 GiB
prompt cache, and six workers OOM-killed Pea's 31 GB host on 2026-09-18
(change bound-llama-host-prompt-cache).
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
from config import Settings


def _command(monkeypatch, **overrides):
    for name, value in overrides.items():
        monkeypatch.setattr(server.settings, name, value)
    with patch.object(server.subprocess, "Popen") as popen:
        server.start_llama_server()
    return popen.call_args.args[0]


def _settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env file
    return Settings()


def _flag_value(cmd, flag):
    assert cmd.count(flag) == 1, f"{flag} must appear exactly once in {cmd}"
    return cmd[cmd.index(flag) + 1]


def test_cache_ram_is_always_passed(monkeypatch):
    cmd = _command(monkeypatch, cache_ram=1024)
    assert _flag_value(cmd, "--cache-ram") == "1024"


def test_default_makes_llama_cpp_default_explicit(monkeypatch, tmp_path):
    monkeypatch.delenv("CACHE_RAM", raising=False)
    assert _settings(monkeypatch, tmp_path).cache_ram == 8192


def test_cache_reuse_still_passed_alongside_cache_ram(monkeypatch):
    cmd = _command(monkeypatch, cache_ram=1024, cache_reuse=256)
    assert _flag_value(cmd, "--cache-reuse") == "256"
    assert _flag_value(cmd, "--cache-ram") == "1024"


def test_cache_ram_read_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CACHE_RAM", "1536")
    assert _settings(monkeypatch, tmp_path).cache_ram == 1536


@pytest.mark.parametrize("value", ["0", "-1"])
def test_disabled_or_unlimited_cache_is_refused(monkeypatch, tmp_path, value):
    # 0 may disable the --cache-reuse path; -1 is unlimited. Both fail at startup.
    monkeypatch.setenv("CACHE_RAM", value)
    with pytest.raises(ValidationError):
        _settings(monkeypatch, tmp_path)
