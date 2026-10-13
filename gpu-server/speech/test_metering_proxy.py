import unittest

from aiohttp import web

from metering_proxy import (
    DEFAULT_OPUS_COMPRESSION_LEVEL,
    opus_compression_level,
    opus_encoder_command,
    prepare_tts_payload,
)


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




class OpusEncoderTest(unittest.TestCase):
    def test_encoder_runs_at_the_configured_effort(self):
        command = opus_encoder_command(40000, 5)
        self.assertEqual(command[command.index("-compression_level") + 1], "5")
        self.assertEqual(command[command.index("-b:a") + 1], "40000")
        self.assertEqual(command[-2:], ["ogg", "pipe:1"])

    def test_effort_setting_is_bounded(self):
        self.assertEqual(opus_compression_level("0"), 0)
        self.assertEqual(opus_compression_level("10"), 10)
        self.assertEqual(DEFAULT_OPUS_COMPRESSION_LEVEL, 0)
        for raw in ("11", "-1", "fast", None, ""):
            self.assertEqual(opus_compression_level(raw), DEFAULT_OPUS_COMPRESSION_LEVEL)

if __name__ == "__main__":
    unittest.main()
