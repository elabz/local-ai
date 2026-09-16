import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


GPU_SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GPU_SERVER))

from availability import BackendAvailability  # noqa: E402
from metrics import inference_admission_total, inference_admission_wait_seconds  # noqa: E402
from routes import _admission_wait_seconds, begin_inference, end_inference, health_check  # noqa: E402


def admission_count(status: str) -> float:
    return inference_admission_total.labels(status=status)._value.get()


def admission_wait_samples() -> float:
    return inference_admission_wait_seconds._sum.get()


def request_with(availability, llama_client=None):
    state = types.SimpleNamespace(backend_availability=availability)
    if llama_client is not None:
        state.llama_client = llama_client
    return types.SimpleNamespace(app=types.SimpleNamespace(state=state))


class ChatAdmissionTest(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_the_single_slot_instead_of_immediate_503(self):
        availability = BackendAvailability(max_in_flight=1)
        availability.probe_succeeded()
        self.assertTrue(availability.begin_request())
        request = request_with(availability)

        async def release_active_request():
            await asyncio.sleep(0.01)
            availability.end_request()

        release = asyncio.create_task(release_active_request())
        with patch.dict(os.environ, {"ADMISSION_WAIT_SECONDS": "0.2"}):
            await begin_inference(request)
        await release
        self.assertEqual(availability.snapshot().in_flight, 1)
        end_inference(request)

    async def test_queue_timeout_is_429_busy_with_retry_after_not_503(self):
        availability = BackendAvailability(max_in_flight=1)
        availability.probe_succeeded()
        self.assertTrue(availability.begin_request())
        request = request_with(availability)
        rejected_before = admission_count("rejected")

        with patch.dict(os.environ, {"ADMISSION_WAIT_SECONDS": "0.01"}):
            with self.assertRaises(HTTPException) as raised:
                await begin_inference(request)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertNotEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["code"], "BACKEND_BUSY")
        retry_after = int(raised.exception.headers["Retry-After"])
        self.assertGreaterEqual(retry_after, 1)
        self.assertLessEqual(retry_after, 30)
        self.assertEqual(admission_count("rejected"), rejected_before + 1)
        availability.end_request()

    async def test_admission_metrics_distinguish_admitted_from_queued(self):
        availability = BackendAvailability(max_in_flight=1)
        availability.probe_succeeded()
        request = request_with(availability)
        admitted_before = admission_count("admitted")
        queued_before = admission_count("queued")
        wait_before = admission_wait_samples()

        # Slot free on arrival -> admitted, no wait.
        with patch.dict(os.environ, {"ADMISSION_WAIT_SECONDS": "0.2"}):
            await begin_inference(request)
        self.assertEqual(admission_count("admitted"), admitted_before + 1)
        self.assertEqual(admission_count("queued"), queued_before)

        # Slot busy on arrival but freed within the bound -> queued, wait observed.
        async def release_active_request():
            await asyncio.sleep(0.02)
            end_inference(request)

        release = asyncio.create_task(release_active_request())
        with patch.dict(os.environ, {"ADMISSION_WAIT_SECONDS": "0.5"}):
            await begin_inference(request)
        await release
        self.assertEqual(admission_count("queued"), queued_before + 1)
        self.assertEqual(admission_count("admitted"), admitted_before + 1)
        self.assertGreater(admission_wait_samples(), wait_before)
        end_inference(request)

    def test_default_wait_bound_is_one_generation_not_zero(self):
        env = {k: v for k, v in os.environ.items() if k != "ADMISSION_WAIT_SECONDS"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(_admission_wait_seconds(), 60.0)
        with patch.dict(os.environ, {"ADMISSION_WAIT_SECONDS": "0"}):
            self.assertEqual(_admission_wait_seconds(), 0.0)
        with patch.dict(os.environ, {"ADMISSION_WAIT_SECONDS": "not-a-number"}):
            self.assertEqual(_admission_wait_seconds(), 60.0)

    def test_unavailable_paths_still_use_503(self):
        """Busy moved to 429; GPU_UNAVAILABLE / BACKEND_UNAVAILABLE stay 503."""
        source = (GPU_SERVER / "routes.py").read_text()
        for code in ("GPU_UNAVAILABLE", "BACKEND_UNAVAILABLE"):
            self.assertIn(code, source)
            for block in source.split("raise HTTPException(")[1:]:
                head = block.split(")", 1)[0]
                if code in head:
                    self.assertIn("status_code=503", head, code)
        busy_blocks = [b for b in source.split("raise HTTPException(")[1:] if "BACKEND_BUSY" in b.split(")", 1)[0]]
        self.assertTrue(busy_blocks)
        for block in busy_blocks:
            self.assertIn("status_code=429", block.split(")", 1)[0])

    async def test_busy_backend_remains_healthy_for_router_checks(self):
        availability = BackendAvailability(max_in_flight=1)
        availability.probe_succeeded()
        self.assertTrue(availability.begin_request())

        class Child:
            async def health_check(self):
                raise AssertionError("busy health must not probe the occupied child")

        result = await health_check(request_with(availability, Child()))
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["backend_state"], "busy")
        self.assertEqual(result["llama_status"], "busy")
        availability.end_request()


if __name__ == "__main__":
    unittest.main()
