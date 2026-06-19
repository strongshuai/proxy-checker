import os
import tempfile
import unittest
from unittest import mock

import server


class ServerBrowserConfigTests(unittest.TestCase):
    def setUp(self):
        self.old_values = {
            "BROWSER_CHECK_ENABLED": server.BROWSER_CHECK_ENABLED,
            "BROWSER_CHECK_TIMEOUT": server.BROWSER_CHECK_TIMEOUT,
            "BROWSER_CHECK_CONCURRENT": server.BROWSER_CHECK_CONCURRENT,
            "BROWSER_CHECK_TARGET_URL": server.BROWSER_CHECK_TARGET_URL,
            "BROWSER_CHECK_WAIT_UNTIL": server.BROWSER_CHECK_WAIT_UNTIL,
            "BROWSER_CHECK_SETTLE_MS": server.BROWSER_CHECK_SETTLE_MS,
            "BROWSER_CHECK_MIN_BODY_LENGTH": server.BROWSER_CHECK_MIN_BODY_LENGTH,
            "BROWSER_CHECK_SUCCESS_TEXT": server.BROWSER_CHECK_SUCCESS_TEXT,
            "BROWSER_CHECK_FAIL_TEXT": server.BROWSER_CHECK_FAIL_TEXT,
            "BROWSER_CHECK_SCREENSHOT_ON_FAIL": server.BROWSER_CHECK_SCREENSHOT_ON_FAIL,
            "BROWSER_CHECK_STRICT": server.BROWSER_CHECK_STRICT,
            "BROWSER_CHECK_MAX_FAILED_REQUESTS": server.BROWSER_CHECK_MAX_FAILED_REQUESTS,
            "BROWSER_CHECK_MAX_BAD_RESPONSES": server.BROWSER_CHECK_MAX_BAD_RESPONSES,
        }

    def tearDown(self):
        for key, value in self.old_values.items():
            setattr(server, key, value)

    def test_public_settings_payload_contains_browser_check_fields(self):
        payload = server.public_settings_payload()
        self.assertIn("browser_check_enabled", payload)
        self.assertIn("browser_check_target_url", payload)
        self.assertIn("browser_check_concurrent", payload)
        self.assertIn("browser_check_fail_text", payload)
        self.assertIsInstance(payload["browser_check_fail_text"], list)

    def test_apply_runtime_settings_normalizes_browser_config(self):
        server.apply_runtime_settings({
            "browser_check_enabled": True,
            "browser_check_timeout": 999,
            "browser_check_concurrent": 0,
            "browser_check_target_url": "https://dashboard.prem.io/auth/login",
            "browser_check_wait_until": "bogus",
            "browser_check_settle_ms": -1,
            "browser_check_min_body_length": 42,
            "browser_check_success_text": "Login\nPrem",
            "browser_check_fail_text": "Denied,Blocked",
            "browser_check_screenshot_on_fail": True,
            "browser_check_strict": False,
            "browser_check_max_failed_requests": 9999,
            "browser_check_max_bad_responses": -2,
        })
        self.assertTrue(server.BROWSER_CHECK_ENABLED)
        self.assertEqual(server.BROWSER_CHECK_TIMEOUT, 120)
        self.assertEqual(server.BROWSER_CHECK_CONCURRENT, 1)
        self.assertEqual(server.BROWSER_CHECK_TARGET_URL, "https://dashboard.prem.io/auth/login")
        self.assertEqual(server.BROWSER_CHECK_WAIT_UNTIL, "domcontentloaded")
        self.assertEqual(server.BROWSER_CHECK_SETTLE_MS, 0)
        self.assertEqual(server.BROWSER_CHECK_MIN_BODY_LENGTH, 42)
        self.assertEqual(server.BROWSER_CHECK_SUCCESS_TEXT, ("Login", "Prem"))
        self.assertEqual(server.BROWSER_CHECK_FAIL_TEXT, ("Denied", "Blocked"))
        self.assertTrue(server.BROWSER_CHECK_SCREENSHOT_ON_FAIL)
        self.assertFalse(server.BROWSER_CHECK_STRICT)
        self.assertEqual(server.BROWSER_CHECK_MAX_FAILED_REQUESTS, 1000)
        self.assertEqual(server.BROWSER_CHECK_MAX_BAD_RESPONSES, 0)

    def test_build_browser_config_uses_profile_url_when_target_empty(self):
        server.apply_runtime_settings({
            "browser_check_enabled": True,
            "browser_check_target_url": "",
        })
        config = server.build_browser_check_config("https://example.test/path")
        self.assertTrue(config.enabled)
        self.assertEqual(config.target_url, "https://example.test/path")


if __name__ == "__main__":
    unittest.main()
