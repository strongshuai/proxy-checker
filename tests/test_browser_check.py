import unittest

from browser_check import (
    BrowserCheckConfig,
    BrowserCheckResult,
    apply_browser_result_to_proxy_result,
    build_browser_verdict,
    normalize_proxy_for_playwright,
)


class BrowserCheckPureTests(unittest.TestCase):
    def test_normalize_http_proxy_for_playwright(self):
        normalized = normalize_proxy_for_playwright("http://127.0.0.1:8080")
        self.assertEqual(normalized.proxy, {"server": "http://127.0.0.1:8080"})
        self.assertIsNone(normalized.error_type)
        self.assertIsNone(normalized.note)

    def test_normalize_socks5h_to_socks5_with_note(self):
        normalized = normalize_proxy_for_playwright("socks5h://user:pass@127.0.0.1:1080")
        self.assertEqual(normalized.proxy, {"server": "socks5://127.0.0.1:1080", "username": "user", "password": "pass"})
        self.assertEqual(normalized.note, "socks5h 已按 Playwright 支持转换为 socks5")
        self.assertIsNone(normalized.error_type)

    def test_reject_unsupported_socks4_proxy(self):
        normalized = normalize_proxy_for_playwright("socks4://127.0.0.1:9050")
        self.assertIsNone(normalized.proxy)
        self.assertEqual(normalized.error_type, "unsupported_protocol")
        self.assertIn("socks4", normalized.error or "")

    def test_build_browser_verdict_requires_success_text_when_configured(self):
        config = BrowserCheckConfig(
            enabled=True,
            target_url="https://dashboard.prem.io/auth/login",
            success_text=("Sign in",),
            fail_text=("Access denied",),
            min_body_length=10,
        )
        verdict = build_browser_verdict(
            config=config,
            status=200,
            body_text="Welcome to another page with enough content",
            request_failed_count=0,
            bad_response_count=0,
        )
        self.assertFalse(verdict.ready)
        self.assertEqual(verdict.error_type, "success_text_missing")

    def test_build_browser_verdict_flags_cf_challenge(self):
        config = BrowserCheckConfig(enabled=True, fail_text=(), min_body_length=10)
        verdict = build_browser_verdict(
            config=config,
            status=200,
            body_text="Just a moment Checking your browser before accessing the site",
            request_failed_count=0,
            bad_response_count=0,
        )
        self.assertFalse(verdict.ready)
        self.assertEqual(verdict.error_type, "cf_challenge")
        self.assertIn("Just a moment", verdict.fail_text_matched)

    def test_apply_browser_result_strict_demotes_http_valid_result(self):
        result = {"valid": True, "grade": "A", "recommended_use": "generic"}
        browser = BrowserCheckResult(
            checked=True,
            ready=False,
            error="浏览器页面不可用",
            error_type="timeout",
            detail={"target": "https://dashboard.prem.io/auth/login"},
        )
        merged = apply_browser_result_to_proxy_result(result, browser, strict=True)
        self.assertTrue(merged["http_valid"])
        self.assertFalse(merged["valid"])
        self.assertFalse(merged["usable_for_browser"])
        self.assertTrue(merged["browser_checked"])
        self.assertEqual(merged["browser_error_type"], "timeout")
        self.assertEqual(merged["recommended_use"], "http_only")

    def test_apply_browser_result_non_strict_preserves_http_valid(self):
        result = {"valid": True, "grade": "A", "recommended_use": "generic"}
        browser = BrowserCheckResult(checked=True, ready=False, error_type="content_too_short")
        merged = apply_browser_result_to_proxy_result(result, browser, strict=False)
        self.assertTrue(merged["http_valid"])
        self.assertTrue(merged["valid"])
        self.assertFalse(merged["usable_for_browser"])


if __name__ == "__main__":
    unittest.main()
