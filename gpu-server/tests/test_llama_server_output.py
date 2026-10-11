"""llama-server's output must never go to a pipe nobody reads.

llama.cpp logs on every request. Started with stdout/stderr=PIPE and no
reader, it filled the ~64 KB pipe buffer and blocked in pipe_write
mid-request: /health stayed green, the GPU idled, and every later request
queued behind it until the container was restarted. All six chat replicas on
Pea froze this way on 2026-10-11.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server

# Far more than any pipe buffer (Linux 64 KiB, macOS 16-64 KiB).
CHATTY_CHILD = (
    "import sys\n"
    "line = 'slot release: id 0 | task 1 | stop processing: n_tokens = 512\\n'\n"
    "for _ in range(20000):\n"
    "    sys.stderr.write(line)\n"
    "    sys.stdout.write(line)\n"
)


def _popen_kwargs():
    with patch.object(server.subprocess, "Popen") as popen:
        server.start_llama_server()
    return popen.call_args.kwargs


def test_llama_server_output_is_not_piped():
    kwargs = _popen_kwargs()
    assert kwargs.get("stdout") is not subprocess.PIPE
    assert kwargs.get("stderr") is not subprocess.PIPE


def test_a_chatty_child_started_the_same_way_never_blocks():
    """The launcher's stream settings, applied to a child that logs ~2.6 MB."""
    kwargs = _popen_kwargs()
    child = subprocess.Popen(
        [sys.executable, "-c", CHATTY_CHILD],
        stdout=subprocess.DEVNULL if kwargs.get("stdout") is None else kwargs["stdout"],
        stderr=subprocess.DEVNULL if kwargs.get("stderr") is None else kwargs["stderr"],
    )
    try:
        assert child.wait(timeout=30) == 0
    finally:
        if child.poll() is None:
            child.kill()
