"""Public environment validation stays offline, masked and stdlib-only."""

from dataclasses import asdict
import logging
import io
import unittest
from unittest.mock import patch

from provider.environment import read_live_settings


class EnvironmentSettingsTests(unittest.TestCase):
    def test_shared_settings_defaults_and_explicit_options(self):
        with patch("urllib.request.build_opener", side_effect=AssertionError("No transport in config")):
            settings = read_live_settings({"LIARA_API_TOKEN": "secret-test", "LIARA_PROJECT_NAME": "project"})
            self.assertEqual(settings.config.timeout, 10)
            self.assertIsNone(settings.logs_since)
            settings = read_live_settings({"LIARA_API_TOKEN": "secret-test", "LIARA_PROJECT_NAME": "project",
                "LIARA_LOGS_SINCE": "opaque-window", "LIARA_API_BASE_URL": "https://example.invalid/api/",
                "LIARA_TIMEOUT_SECONDS": "2.5"})
            self.assertEqual(settings.config.timeout, 2.5)
            self.assertEqual(settings.config.base_url, "https://example.invalid/api")
            self.assertEqual(settings.logs_since, "opaque-window")

    def test_public_validation_exceptions_and_reprs_never_echo_settings(self):
        token = "secret-settings-canary"
        base = {"LIARA_API_TOKEN": token, "LIARA_PROJECT_NAME": "private-project"}
        cases = [{}, {**base, "LIARA_TIMEOUT_SECONDS": token}, {**base, "LIARA_LOGS_SINCE": token + "\ud800"},
                 {**base, "LIARA_PROJECT_NAME": token + "\ud800"}, {**base, "LIARA_API_TOKEN": token + "\n"}]
        stream = io.StringIO()
        logger = logging.Logger("provider-settings-test")
        logger.addHandler(logging.StreamHandler(stream))
        for environment in cases:
            with self.assertRaises(ValueError) as caught:
                read_live_settings(environment)
            logger.warning("%s %r", caught.exception, caught.exception)
            self.assertTrue(caught.exception.__suppress_context__)
        settings = read_live_settings(base)
        logger.warning("%s %r", settings, settings)
        self.assertNotIn(token, stream.getvalue())
        self.assertNotIn("private-project", stream.getvalue())
        self.assertNotIn(token, repr(asdict(settings)))


if __name__ == "__main__":
    unittest.main()
