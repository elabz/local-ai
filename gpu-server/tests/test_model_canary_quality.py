import unittest

from scripts.model_canary_quality import response_record, sha256_text


class ModelCanaryQualityTest(unittest.TestCase):
    def test_response_evidence_contains_hash_not_content(self):
        content, record = response_record(
            {"choices": [{"message": {"content": "A synthetic answer."}}]}
        )
        self.assertEqual(content, "A synthetic answer.")
        self.assertEqual(record["sha256"], sha256_text(content))
        self.assertNotIn("content", record)
        self.assertFalse(record["blank"])

    def test_refusal_and_reasoning_are_aggregate_flags(self):
        _, record = response_record(
            {
                "choices": [
                    {
                        "message": {
                            "content": "I cannot help with that request.",
                            "reasoning_content": "hidden",
                        }
                    }
                ]
            }
        )
        self.assertTrue(record["refusal_marker"])
        self.assertTrue(record["reasoning_nonempty"])

    def test_visible_thought_channel_is_detected(self):
        _, record = response_record(
            {"choices": [{"message": {"content": "<|channel>thought\nanswer"}}]}
        )
        self.assertTrue(record["visible_reasoning_marker"])


if __name__ == "__main__":
    unittest.main()
