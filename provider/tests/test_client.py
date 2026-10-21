import errno
import http.client
import io
import json
import logging
import socket
import unittest
import urllib.error
import urllib.request
import urllib.response
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, FrozenInstanceError
from datetime import datetime, timedelta
from email.message import Message
from unittest.mock import MagicMock, patch

from provider import (
    ApiUnavailableError, AuthenticationError, InvalidResponseError,
    LiaraProviderException, NetworkError, ProviderConfig,
    RateLimitError, ResourceNotFoundError, SecretStr, TimeoutError,
)
from provider.exceptions import InvalidRequestError


TOKEN = "private-liara-token-DO-NOT-PRINT"


class CredentialAndExceptionTests(unittest.TestCase):
    def test_config_and_secret_are_safe_to_format_log_and_convert(self):
        config = ProviderConfig(TOKEN)
        output = io.StringIO()
        logger = logging.Logger("provider-test")
        logger.addHandler(logging.StreamHandler(output))
        logger.warning("config=%s repr=%r secret=%s", config, config, config.api_key)
        for text in (output.getvalue(), str(config), repr(config), str(config.api_key),
                     repr(config.api_key), repr(asdict(config)), json.dumps(config.to_dict())):
            self.assertNotIn(TOKEN, text)
        self.assertEqual(config.api_key.get_secret_value(), TOKEN)
        self.assertIn("**********", str(config))
        with self.assertRaises(FrozenInstanceError):
            config.timeout = 3
        with self.assertRaises(TypeError):
            json.dumps(asdict(config))

    def test_config_defaults(self):
        config = ProviderConfig(TOKEN)
        self.assertEqual(config.base_url, "https://api.iran.liara.ir")
        self.assertEqual(config.timeout, 10.0)
        self.assertFalse(config.is_mock)
        self.assertIsInstance(ProviderConfig(SecretStr(TOKEN)).api_key, SecretStr)

    def test_invalid_config_errors_do_not_echo_values(self):
        cases = (
            {"api_key": ""}, {"api_key": None}, {"api_key": "Bearer " + TOKEN},
            {"api_key": TOKEN + "\r\nHeader: injected"}, {"api_key": "non-ascii-\u2603"},
            {"base_url": "http://example.invalid/" + TOKEN},
            {"base_url": "https://" + TOKEN + "@example.invalid"},
            {"base_url": "https://example.invalid/?key=" + TOKEN},
            {"base_url": "https://example.invalid/#" + TOKEN},
            {"base_url": "https://example.invalid/\n" + TOKEN},
            {"base_url": "https://example.invalid:bad"},
            {"base_url": "https://example.invalid:0"},
            {"base_url": "https://[invalid"}, {"base_url": None},
            {"timeout": 0}, {"timeout": -1}, {"timeout": float("nan")},
            {"timeout": float("inf")}, {"timeout": True}, {"timeout": TOKEN},
            {"timeout": 10 ** 500},
            {"is_mock": "yes"},
        )
        for values in cases:
            with self.subTest(fields=list(values)), self.assertRaises(ValueError) as raised:
                ProviderConfig(**{"api_key": TOKEN, **values})
            self.assertNotIn(TOKEN, str(raised.exception))

    def test_every_exception_discards_untrusted_message(self):
        for cls in (LiaraProviderException, AuthenticationError, RateLimitError, TimeoutError,
                    ApiUnavailableError, ResourceNotFoundError, NetworkError, InvalidResponseError,
                    InvalidRequestError):
            with self.subTest(exception=cls.__name__):
                error = cls("Authorization: Bearer " + TOKEN)
                self.assertIsInstance(error, LiaraProviderException)
                for value in (str(error), repr(error), repr(error.args), repr(vars(error)), repr(error.to_error())):
                    self.assertNotIn(TOKEN, value)
                output = io.StringIO()
                logger = logging.Logger("provider-exception-test")
                logger.addHandler(logging.StreamHandler(output))
                logger.error("error=%s repr=%r", error, error)
                self.assertNotIn(TOKEN, output.getvalue())
                self.assertEqual(error.to_error().code, cls.code)
                self.assertEqual(error.to_error().retryable, cls.retryable)
        self.assertEqual(AuthenticationError(http_status=403).to_error().http_status, 403)
        self.assertIsNone(AuthenticationError(http_status=TOKEN).to_error().http_status)


if __name__ == "__main__":
    unittest.main()
