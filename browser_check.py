from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse, urlunparse, unquote

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except Exception:  # pragma: no cover - depends on optional runtime dependency
    async_playwright = None
    PlaywrightTimeoutError = TimeoutError
    PLAYWRIGHT_AVAILABLE = False

DEFAULT_BROWSER_FAIL_TEXT: Tuple[str, ...] = (
    "Just a moment",
    "Checking your browser",
    "Verify you are human",
    "Access denied",
    "cf-turnstile",
    "challenge-platform",
)
CF_BROWSER_INDICATORS: Tuple[str, ...] = (
    "Just a moment",
    "Checking your browser",
    "Verify you are human",
    "cf-turnstile",
    "challenge-platform",
    "cf-chl",
    "cf-turnstile-response",
    "cf_mitigated",
)
SUPPORTED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}
WAIT_UNTIL_VALUES = {"commit", "domcontentloaded", "load", "networkidle"}


@dataclass(frozen=True)
class NormalizedBrowserProxy:
    proxy: Optional[Dict[str, str]]
    error_type: Optional[str] = None
    error: Optional[str] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class BrowserCheckConfig:
    enabled: bool = False
    timeout: int = 30
    concurrent: int = 3
    target_url: str = ""
    wait_until: str = "domcontentloaded"
    settle_ms: int = 3000
    min_body_length: int = 100
    success_text: Tuple[str, ...] = ()
    fail_text: Tuple[str, ...] = DEFAULT_BROWSER_FAIL_TEXT
    screenshot_on_fail: bool = False
    strict: bool = True
    max_failed_requests: int = 10
    max_bad_responses: int = 10
    screenshots_dir: str = "browser_check_artifacts/screenshots"

    def normalized(self) -> "BrowserCheckConfig":
        wait_until = self.wait_until if self.wait_until in WAIT_UNTIL_VALUES else "domcontentloaded"
        return BrowserCheckConfig(
            enabled=bool(self.enabled),
            timeout=max(3, min(120, int(self.timeout or 30))),
            concurrent=max(1, min(50, int(self.concurrent or 3))),
            target_url=normalize_browser_target_url(self.target_url),
            wait_until=wait_until,
            settle_ms=max(0, min(30000, int(self.settle_ms or 0))),
            min_body_length=max(0, min(100000, int(self.min_body_length or 0))),
            success_text=tuple(_clean_text_list(self.success_text)),
            fail_text=tuple(_clean_text_list(self.fail_text)) or DEFAULT_BROWSER_FAIL_TEXT,
            screenshot_on_fail=bool(self.screenshot_on_fail),
            strict=bool(self.strict),
            max_failed_requests=max(0, min(1000, int(self.max_failed_requests or 0))),
            max_bad_responses=max(0, min(1000, int(self.max_bad_responses or 0))),
            screenshots_dir=str(self.screenshots_dir or "browser_check_artifacts/screenshots"),
        )


@dataclass(frozen=True)
class BrowserVerdict:
    ready: bool
    error_type: Optional[str] = None
    error: Optional[str] = None
    success_text_matched: Tuple[str, ...] = ()
    fail_text_matched: Tuple[str, ...] = ()
    cf_challenge: bool = False


@dataclass
class BrowserCheckResult:
    checked: bool = False
    ready: Optional[bool] = None
    status: Optional[int] = None
    title: Optional[str] = None
    final_url: Optional[str] = None
    latency: Optional[int] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    detail: Dict[str, object] = field(default_factory=dict)

    def to_public_fields(self) -> Dict[str, object]:
        return {
            "browser_checked": self.checked,
            "browser_ready": self.ready,
            "browser_status": self.status,
            "browser_title": self.title,
            "browser_final_url": self.final_url,
            "browser_latency": self.latency,
            "browser_error": self.error,
            "browser_error_type": self.error_type,
            "browser_detail": self.detail,
        }


def normalize_browser_target_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return raw


def parse_text_list(value: object) -> Tuple[str, ...]:
    return tuple(_clean_text_list(value))


def _clean_text_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        pieces = re.split(r"[\r\n,]+", value)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        pieces = [str(item) for item in value]
    else:
        pieces = [str(value)]
    seen = set()
    cleaned: List[str] = []
    for piece in pieces:
        text = str(piece or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def normalize_proxy_for_playwright(proxy_str: str) -> NormalizedBrowserProxy:
    raw = str(proxy_str or "").strip()
    if not raw:
        return NormalizedBrowserProxy(None, "invalid_proxy", "代理为空")
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return NormalizedBrowserProxy(None, "invalid_proxy", "浏览器检测需要带协议的代理地址")
    scheme = parsed.scheme.lower()
    if scheme == "socks4":
        return NormalizedBrowserProxy(None, "unsupported_protocol", "Playwright 浏览器检测不支持 socks4 代理")
    if scheme not in SUPPORTED_PROXY_SCHEMES:
        return NormalizedBrowserProxy(None, "unsupported_protocol", f"Playwright 浏览器检测不支持 {scheme} 代理")

    note = None
    server_scheme = scheme
    if scheme == "socks5h":
        server_scheme = "socks5"
        note = "socks5h 已按 Playwright 支持转换为 socks5"

    hostname = parsed.hostname
    port = parsed.port
    if not hostname or port is None:
        return NormalizedBrowserProxy(None, "invalid_proxy", "代理地址缺少主机或端口")
    host = hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    server = urlunparse((server_scheme, f"{host}:{port}", "", "", "", ""))
    proxy: Dict[str, str] = {"server": server}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return NormalizedBrowserProxy(proxy, note=note)


def build_browser_verdict(
    *,
    config: BrowserCheckConfig,
    status: Optional[int],
    body_text: str,
    request_failed_count: int,
    bad_response_count: int,
) -> BrowserVerdict:
    normalized = config.normalized()
    text = body_text or ""
    text_lower = text.lower()
    success_matches = tuple(item for item in normalized.success_text if item.lower() in text_lower)
    fail_matches = tuple(item for item in normalized.fail_text if item.lower() in text_lower)
    cf_matches = tuple(item for item in CF_BROWSER_INDICATORS if item.lower() in text_lower)
    combined_fail_matches = tuple(dict.fromkeys([*fail_matches, *cf_matches]))

    if status is None:
        return BrowserVerdict(False, "navigation_failed", "未获取到主文档响应", success_matches, combined_fail_matches, bool(cf_matches))
    if status < 200 or status >= 400:
        return BrowserVerdict(False, "http_status_failed", f"浏览器主文档 HTTP {status}", success_matches, combined_fail_matches, bool(cf_matches))
    if cf_matches:
        return BrowserVerdict(False, "cf_challenge", "浏览器页面命中 Cloudflare/验证页特征", success_matches, combined_fail_matches, True)
    if fail_matches:
        return BrowserVerdict(False, "fail_text_matched", "浏览器页面命中失败关键词", success_matches, combined_fail_matches, False)
    if len(text.strip()) < normalized.min_body_length:
        return BrowserVerdict(False, "content_too_short", f"页面正文过短({len(text.strip())}/{normalized.min_body_length})", success_matches, combined_fail_matches, False)
    if normalized.success_text and not success_matches:
        return BrowserVerdict(False, "success_text_missing", "未命中浏览器成功关键词", success_matches, combined_fail_matches, False)
    if request_failed_count > normalized.max_failed_requests:
        return BrowserVerdict(False, "too_many_request_failures", f"失败请求过多({request_failed_count})", success_matches, combined_fail_matches, False)
    if bad_response_count > normalized.max_bad_responses:
        return BrowserVerdict(False, "too_many_bad_responses", f"异常响应过多({bad_response_count})", success_matches, combined_fail_matches, False)
    return BrowserVerdict(True, success_text_matched=success_matches, fail_text_matched=combined_fail_matches, cf_challenge=False)


def apply_browser_result_to_proxy_result(
    result: Mapping[str, object],
    browser_result: BrowserCheckResult,
    strict: bool = True,
) -> Dict[str, object]:
    merged = dict(result)
    http_valid = bool(merged.get("http_valid", merged.get("valid", False)))
    merged["http_valid"] = http_valid
    merged.update(browser_result.to_public_fields())
    if not browser_result.checked:
        merged.setdefault("usable_for_browser", http_valid)
        return merged
    ready = browser_result.ready is True
    merged["usable_for_browser"] = ready
    if strict:
        merged["valid"] = http_valid and ready
        if http_valid and not ready:
            merged["unstable"] = False
            merged["recommended_use"] = "http_only"
            if browser_result.error:
                merged["error"] = browser_result.error
    else:
        merged["valid"] = http_valid
    return merged


def default_browser_fields(result: Mapping[str, object]) -> Dict[str, object]:
    merged = dict(result)
    http_valid = bool(merged.get("valid", False))
    merged.setdefault("http_valid", http_valid)
    merged.setdefault("browser_checked", False)
    merged.setdefault("browser_ready", None)
    merged.setdefault("usable_for_browser", http_valid)
    return merged


def should_browser_check_result(result: Mapping[str, object]) -> bool:
    if result.get("browser_checked"):
        return False
    if result.get("http_valid", result.get("valid")):
        return True
    if result.get("unstable"):
        return True
    return str(result.get("grade") or "").upper() in {"A", "B", "C"}


def classify_browser_exception(exc: BaseException) -> Tuple[str, str]:
    text = str(exc) or exc.__class__.__name__
    lower = text.lower()
    if isinstance(exc, PlaywrightTimeoutError) or "timeout" in lower:
        return "timeout", "浏览器打开页面超时"
    if "err_proxy_connection_failed" in lower or "proxy_connection_failed" in lower:
        return "proxy_connection_failed", "浏览器代理连接失败"
    if "err_tunnel_connection_failed" in lower or "tunnel" in lower:
        return "proxy_tunnel_failed", "浏览器代理隧道建立失败"
    if "err_name_not_resolved" in lower or "dns" in lower:
        return "dns_failed", "浏览器 DNS 解析失败"
    if "ssl" in lower or "tls" in lower or "certificate" in lower:
        return "tls_failed", "浏览器 TLS/证书错误"
    return "navigation_failed", text[:200]


class BrowserCheckEngine:
    def __init__(self, config: BrowserCheckConfig):
        self.config = config.normalized()
        self._playwright = None
        self._browser = None
        self._semaphore = asyncio.Semaphore(self.config.concurrent)

    async def __aenter__(self) -> "BrowserCheckEngine":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            finally:
                self._playwright = None

    async def _ensure_browser(self):
        if not PLAYWRIGHT_AVAILABLE or async_playwright is None:
            raise RuntimeError("playwright unavailable")
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        return self._browser

    async def check_proxy(self, proxy_str: str, target_url: Optional[str] = None) -> BrowserCheckResult:
        target = normalize_browser_target_url(target_url or self.config.target_url)
        start = time.time()
        if not self.config.enabled:
            return BrowserCheckResult(checked=False, ready=None, detail={"target": target})
        if not target:
            return BrowserCheckResult(checked=True, ready=False, error="浏览器检测目标 URL 无效", error_type="invalid_target", detail={"target": target})
        normalized_proxy = normalize_proxy_for_playwright(proxy_str)
        if normalized_proxy.error_type:
            return BrowserCheckResult(
                checked=True,
                ready=False,
                latency=round((time.time() - start) * 1000),
                error=normalized_proxy.error,
                error_type=normalized_proxy.error_type,
                detail={"target": target, "proxy_note": normalized_proxy.note},
            )
        if not PLAYWRIGHT_AVAILABLE:
            return BrowserCheckResult(
                checked=True,
                ready=False,
                latency=round((time.time() - start) * 1000),
                error="playwright 未安装或不可用",
                error_type="playwright_unavailable",
                detail={"target": target, "proxy_note": normalized_proxy.note},
            )

        async with self._semaphore:
            context = None
            page = None
            request_failed: List[Dict[str, str]] = []
            bad_responses: List[Dict[str, object]] = []
            status: Optional[int] = None
            title: Optional[str] = None
            final_url: Optional[str] = None
            body_text = ""
            screenshot_path: Optional[str] = None
            try:
                browser = await self._ensure_browser()
                context = await browser.new_context(
                    proxy=normalized_proxy.proxy,
                    ignore_https_errors=False,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1366, "height": 768},
                )
                page = await context.new_page()

                def on_request_failed(request):
                    if len(request_failed) >= 50:
                        return
                    failure = request.failure or "request failed"
                    request_failed.append({"url": request.url, "method": request.method, "error": str(failure)[:200]})

                def on_response(response):
                    try:
                        if response.status >= 400 and len(bad_responses) < 50:
                            bad_responses.append({"url": response.url, "status": response.status})
                    except Exception:
                        return

                page.on("requestfailed", on_request_failed)
                page.on("response", on_response)
                response = await page.goto(target, wait_until=self.config.wait_until, timeout=self.config.timeout * 1000)
                if self.config.settle_ms:
                    await page.wait_for_timeout(self.config.settle_ms)
                if response is not None:
                    status = int(response.status)
                title = await page.title()
                final_url = page.url
                body_text = await page.evaluate("document.body ? document.body.innerText : ''")
                verdict = build_browser_verdict(
                    config=self.config,
                    status=status,
                    body_text=body_text,
                    request_failed_count=len(request_failed),
                    bad_response_count=len(bad_responses),
                )
                detail = {
                    "target": target,
                    "main_document_ok": status is not None and 200 <= status < 400,
                    "dom_loaded": True,
                    "body_length": len(body_text or ""),
                    "success_text_matched": list(verdict.success_text_matched),
                    "fail_text_matched": list(verdict.fail_text_matched),
                    "cf_challenge": verdict.cf_challenge,
                    "request_failed_count": len(request_failed),
                    "bad_response_count": len(bad_responses),
                    "request_failures": request_failed[:10],
                    "bad_responses": bad_responses[:10],
                    "proxy_note": normalized_proxy.note,
                }
                if not verdict.ready and self.config.screenshot_on_fail and page is not None:
                    screenshot_path = await self._save_screenshot(page, proxy_str)
                    detail["screenshot"] = screenshot_path
                return BrowserCheckResult(
                    checked=True,
                    ready=verdict.ready,
                    status=status,
                    title=title,
                    final_url=final_url,
                    latency=round((time.time() - start) * 1000),
                    error=verdict.error,
                    error_type=verdict.error_type,
                    detail=detail,
                )
            except Exception as exc:
                error_type, error = classify_browser_exception(exc)
                detail = {
                    "target": target,
                    "main_document_ok": False,
                    "dom_loaded": False,
                    "body_length": len(body_text or ""),
                    "request_failed_count": len(request_failed),
                    "bad_response_count": len(bad_responses),
                    "request_failures": request_failed[:10],
                    "bad_responses": bad_responses[:10],
                    "proxy_note": normalized_proxy.note,
                    "exception": str(exc)[:500],
                }
                if self.config.screenshot_on_fail and page is not None:
                    try:
                        screenshot_path = await self._save_screenshot(page, proxy_str)
                        detail["screenshot"] = screenshot_path
                    except Exception:
                        pass
                return BrowserCheckResult(
                    checked=True,
                    ready=False,
                    status=status,
                    title=title,
                    final_url=final_url,
                    latency=round((time.time() - start) * 1000),
                    error=error,
                    error_type=error_type,
                    detail=detail,
                )
            finally:
                if context is not None:
                    try:
                        await context.close()
                    except Exception:
                        pass

    async def _save_screenshot(self, page, proxy_str: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", proxy_str)[:80] or "proxy"
        os.makedirs(self.config.screenshots_dir, exist_ok=True)
        path = os.path.join(self.config.screenshots_dir, f"{int(time.time() * 1000)}_{safe}.png")
        await page.screenshot(path=path, full_page=True)
        return path


def run_browser_check_sync(proxy_str: str, config: BrowserCheckConfig, target_url: Optional[str] = None) -> BrowserCheckResult:
    async def run() -> BrowserCheckResult:
        async with BrowserCheckEngine(config) as engine:
            return await engine.check_proxy(proxy_str, target_url=target_url)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()
