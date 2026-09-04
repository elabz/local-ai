import unittest

from aiohttp import web

from metering_proxy import prepare_tts_payload


class EncodingProfileTest(unittest.TestCase):
    def test_provider_profile_passes_through_without_private_field(self):
        payload, profile = prepare_tts_payload(
            {"response_format": "opus", "encoding_profile": "opus-128k"}
        )
        self.assertEqual(profile, "opus-128k")
        self.assertEqual(payload, {"response_format": "opus"})

    def test_lower_profile_requests_raw_pcm_upstream(self):
        payload, profile = prepare_tts_payload(
            {"response_format": "opus", "encoding_profile": "opus-40k"}
        )
        self.assertEqual(profile, "opus-40k")
        self.assertEqual(payload, {"response_format": "pcm"})

    def test_mp3_preview_is_unchanged(self):
        payload, profile = prepare_tts_payload(
            {"response_format": "mp3", "encoding_profile": "ignored"}
        )
        self.assertEqual(profile, "not-applicable")
        self.assertEqual(
            payload, {"response_format": "mp3", "encoding_profile": "ignored"}
        )

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(web.HTTPBadRequest):
            prepare_tts_payload(
                {"response_format": "opus", "encoding_profile": "opus-24k"}
            )


if __name__ == "__main__":
    unittest.main()
