from pathlib import Path
import unittest

import yaml


GPU_SERVER = Path(__file__).resolve().parents[1]


class ModelCanaryWrapperTest(unittest.TestCase):
    def test_nsfw_canary_runs_through_gpu_wrapper(self):
        compose = yaml.safe_load(
            (GPU_SERVER / "docker-compose.model-canaries.yml").read_text()
        )
        service = compose["services"]["nsfw-model-canary"]
        environment = service["environment"]

        # The image default command starts FastAPI, which supervises llama-server
        # on the private child port. Do not bypass it with a llama-server entrypoint.
        self.assertNotIn("entrypoint", service)
        self.assertNotIn("command", service)
        self.assertEqual(environment["PORT"], 8080)
        self.assertEqual(environment["LLAMA_SERVER_PORT"], 8081)
        self.assertEqual(environment["GPU_HEALTH_ENABLED"], 1)
        self.assertEqual(environment["ADMISSION_WAIT_SECONDS"], 30)
        self.assertEqual(environment["DEFAULT_TOP_K"], "${CANARY_TOP_K:-64}")
        self.assertEqual(environment["DEFAULT_TOP_P"], "${CANARY_TOP_P:-0.95}")
        self.assertEqual(
            environment["DEFAULT_REPEAT_PENALTY"],
            "${CANARY_REPEAT_PENALTY:-1.0}",
        )
        self.assertEqual(environment["LLAMA_ARG_REASONING"], "off")
        self.assertEqual(environment["LLAMA_ARG_THINK"], "none")
        self.assertNotIn("LLAMA_ARG_CHAT_TEMPLATE_FILE", environment)
        extra_args = environment["EXTRA_ARGS"]
        for expected in (
            "--top-k ${CANARY_TOP_K:-64}",
            "--top-p ${CANARY_TOP_P:-0.95}",
            "--min-p ${CANARY_MIN_P:-0}",
            "--repeat-penalty ${CANARY_REPEAT_PENALTY:-1.0}",
            "--presence-penalty ${CANARY_PRESENCE_PENALTY:-0}",
        ):
            self.assertIn(expected, extra_args)
        self.assertIn("./server.py:/app/server.py:ro", service["volumes"])
        self.assertIn("./llama_client.py:/app/llama_client.py:ro", service["volumes"])


if __name__ == "__main__":
    unittest.main()
