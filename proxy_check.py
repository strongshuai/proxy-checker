from __future__ import annotations

import asyncio
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from curl_cffi import requests as cffi_requests


DEFAULT_TARGET_CHAT = "https://chat.openai.com/"
DEFAULT_TARGET_API = "https://api.openai.com/v1/models"
DEFAULT_GENERIC_TARGET = "https://example.com/"
DEFAULT_GROK_TARGET = "https://grok.com/"
DEFAULT_GROK_API = "https://api.x.ai/v1/models"
DEFAULT_GEMINI_TARGET = "https://gemini.google.com/"
DEFAULT_GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_CLAUDE_TARGET = "https://claude.ai/"
DEFAULT_CLAUDE_API = "https://api.anthropic.com/v1/models"
DEFAULT_IP_TARGETS = ("https://httpbin.org/ip", "https://api.ipify.org?format=json")
DEFAULT_IP_INFO_TARGETS = ("https://ipinfo.io/{ip}/json", "https://ipwho.is/{ip}")

CF_BODY_INDICATORS = (
    "challenge-platform",
    "cf_chl_opt",
    "cf-chl-b",
    "cf-turnstile",
    "Just a moment",
    "Checking your browser",
    "Verify you are human",
    "Enable JavaScript and cookies",
    "ray ID",
    "challenge-running",
    "challenges.cloudflare.com",
    "turnstile.js",
    "cf-challenge",
    " managed-challenge",
    "cf_mitigated",
)

CF_HEADER_INDICATORS = ("cf-ray", "cf-chl", "cf-cache-status")
OPENAI_REAL_PAGE_INDICATORS = (
    "__next",
    "chat.openai.com",
    "ChatGPT",
    "prompt-textarea",
    "conversation-turn",
)
PROTOCOL_PREFIXES = ("http://", "https://", "socks4://", "socks5://", "socks5h://")
PROTOCOL_FALLBACK_STATUS_CODES = (200, 401, 403)
DEFAULT_TARGET_PROFILE = "generic"
GENERIC_SERVICE_OK_STATUS_CODES = tuple(range(200, 400))
SERVICE_OK_STATUS_CODES = (200, 204, 301, 302, 303, 307, 308)
API_OK_STATUS_CODES = (200, 401, 403)


class StopEvent(Protocol):
    def is_set(self) -> bool:
        ...


@dataclass(frozen=True)
class TargetProfile:
    id: str
    name: str
    service_url: str
    service_indicators: Tuple[str, ...]
    api_url: Optional[str] = None
    service_ok_statuses: Tuple[int, ...] = SERVICE_OK_STATUS_CODES
    api_ok_statuses: Tuple[int, ...] = API_OK_STATUS_CODES
    use_cf_detection: bool = False


TARGET_PROFILES: Dict[str, TargetProfile] = {
    "generic": TargetProfile(
        id="generic",
        name="常规代理检测",
        service_url=DEFAULT_GENERIC_TARGET,
        service_indicators=("example domain",),
    ),
    "openai": TargetProfile(
        id="openai",
        name="OpenAI 检测",
        service_url=DEFAULT_TARGET_CHAT,
        api_url=DEFAULT_TARGET_API,
        service_indicators=OPENAI_REAL_PAGE_INDICATORS,
        use_cf_detection=True,
    ),
    "grok": TargetProfile(
        id="grok",
        name="Grok 检测",
        service_url=DEFAULT_GROK_TARGET,
        api_url=DEFAULT_GROK_API,
        service_indicators=("grok", "x.ai", "__next"),
        use_cf_detection=True,
    ),
    "gemini": TargetProfile(
        id="gemini",
        name="Gemini 检测",
        service_url=DEFAULT_GEMINI_TARGET,
        api_url=DEFAULT_GEMINI_API,
        service_indicators=("gemini", "google", "__data"),
    ),
    "claude": TargetProfile(
        id="claude",
        name="Claude 检测",
        service_url=DEFAULT_CLAUDE_TARGET,
        api_url=DEFAULT_CLAUDE_API,
        service_indicators=("claude", "anthropic", "__next"),
        use_cf_detection=True,
    ),
}

TARGET_PROFILE_OPTIONS: Tuple[Dict[str, object], ...] = tuple(
    {
        "id": profile.id,
        "name": profile.name,
        "has_api": profile.api_url is not None,
        "has_signup": False,
        "has_cf_detection": profile.use_cf_detection,
    }
    for profile in TARGET_PROFILES.values()
)


@dataclass(frozen=True)
class CheckConfig:
    timeout: int
    detect_timeout: int
    check_rounds: int
    target_chat: str = DEFAULT_TARGET_CHAT
    target_api: str = DEFAULT_TARGET_API
    generic_target_url: str = DEFAULT_GENERIC_TARGET
    ip_targets: Tuple[str, ...] = DEFAULT_IP_TARGETS
    ip_info_targets: Tuple[str, ...] = DEFAULT_IP_INFO_TARGETS
    protocol_prefixes: Tuple[str, ...] = PROTOCOL_PREFIXES
    impersonate: str = "chrome"
    ip_info_cache_ttl: int = 3600
    default_target_profile: str = DEFAULT_TARGET_PROFILE


@dataclass(frozen=True)
class ProtocolDiscovery:
    proxy: str
    ip: Optional[str]


@dataclass(frozen=True)
class IpInfoSummary:
    ip: str
    org: str
    country: str
    ip_type: str


@dataclass(frozen=True)
class _IpInfoCacheEntry:
    value: IpInfoSummary
    expires_at: float


@dataclass
class RoundResult:
    valid: bool = False
    latency: Optional[int] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    ip: Optional[str] = None
    country: Optional[str] = None
    ip_type: Optional[str] = None
    service_reachable: Optional[bool] = None
    api_reachable: Optional[bool] = None
    cf_bypass: bool = False
    cf_challenge: bool = False
    cf_challenge_type: Optional[str] = None
    cf_indicators: List[str] = field(default_factory=list)
    registration_ready: bool = False
    registration_detail: Optional[str] = None
    checks_detail: Dict[str, object] = field(default_factory=dict)

    @classmethod
    def stopped(cls) -> "RoundResult":
        return cls(valid=False, error="已停止")


@dataclass(frozen=True)
class ScoreSummary:
    grade: str
    valid: bool
    unstable: bool
    checks_passed: int
    checks_total: int
    latency: Optional[int]
    representative: RoundResult
    detail: Dict[str, object]


class IpInfoCache:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._items: Dict[str, _IpInfoCacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, ip: str) -> Optional[IpInfoSummary]:
        now = time.monotonic()
        with self._lock:
            entry = self._items.get(ip)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._items[ip]
                return None
            return entry.value

    def set(self, summary: IpInfoSummary) -> None:
        expires_at = time.monotonic() + self.ttl_seconds
        with self._lock:
            self._items[summary.ip] = _IpInfoCacheEntry(summary, expires_at)


class ProxyCheckEngine:
    def __init__(self, config: CheckConfig):
        self.config = config
        self.ip_info_cache = IpInfoCache(config.ip_info_cache_ttl)

    async def check_many_async(
        self,
        proxies: Sequence[str],
        stop_event: Optional[StopEvent],
        rounds: int,
        max_concurrent: int,
        on_result: Callable[[Dict[str, object]], None],
        target_profile: Optional[str] = None,
    ) -> None:
        profile = self._get_profile(target_profile)
        semaphore = asyncio.Semaphore(max_concurrent)
        async with cffi_requests.AsyncSession(
            max_clients=max_concurrent,
            impersonate=self.config.impersonate,
        ) as session:
            async def check_one(proxy: str) -> None:
                if _is_stopped(stop_event):
                    return
                async with semaphore:
                    if _is_stopped(stop_event):
                        return
                    result = await self.check_proxy_full_async(proxy, session, stop_event, rounds, profile.id)
                    if result is not None:
                        on_result(result)

            await asyncio.gather(*(check_one(proxy) for proxy in proxies))

    def check_proxy_full(
        self,
        proxy_input: str,
        stop_event: Optional[StopEvent] = None,
        rounds: Optional[int] = None,
        target_profile: Optional[str] = None,
    ) -> Optional[Dict[str, object]]:
        profile = self._get_profile(target_profile)
        total_rounds = rounds if rounds is not None else self.config.check_rounds
        proxy_input = proxy_input.strip()
        if not proxy_input or proxy_input.startswith("#"):
            return None
        if _is_stopped(stop_event):
            return None

        original = proxy_input
        if not self._has_protocol(proxy_input):
            discovery = self._detect_protocol(proxy_input, profile, stop_event)
            if discovery is None:
                return self._protocol_failure(original, total_rounds, profile)
            proxy_input = discovery.proxy
            discovered_ip = discovery.ip
        else:
            discovered_ip = None

        round_results: List[RoundResult] = []
        for index in range(total_rounds):
            if _is_stopped(stop_event):
                break
            ip_hint = discovered_ip if index == 0 else None
            round_results.append(self.check_once(proxy_input, profile, stop_event, self.config.timeout, ip_hint))

        summary = ScoreAggregator(total_rounds, profile).summarize(round_results)
        protocol = proxy_input.split("://", 1)[0] if "://" in proxy_input else None
        return _build_public_result(proxy_input, original, protocol, profile, summary)

    async def check_proxy_full_async(
        self,
        proxy_input: str,
        session: cffi_requests.AsyncSession,
        stop_event: Optional[StopEvent] = None,
        rounds: Optional[int] = None,
        target_profile: Optional[str] = None,
    ) -> Optional[Dict[str, object]]:
        profile = self._get_profile(target_profile)
        total_rounds = rounds if rounds is not None else self.config.check_rounds
        proxy_input = proxy_input.strip()
        if not proxy_input or proxy_input.startswith("#"):
            return None
        if _is_stopped(stop_event):
            return None

        original = proxy_input
        if not self._has_protocol(proxy_input):
            discovery = await self._detect_protocol_async(proxy_input, profile, session, stop_event)
            if discovery is None:
                return self._protocol_failure(original, total_rounds, profile)
            proxy_input = discovery.proxy
            discovered_ip = discovery.ip
        else:
            discovered_ip = None

        round_results: List[RoundResult] = []
        for index in range(total_rounds):
            if _is_stopped(stop_event):
                break
            ip_hint = discovered_ip if index == 0 else None
            round_results.append(await self.check_once_async(proxy_input, profile, session, stop_event, self.config.timeout, ip_hint))

        summary = ScoreAggregator(total_rounds, profile).summarize(round_results)
        protocol = proxy_input.split("://", 1)[0] if "://" in proxy_input else None
        return _build_public_result(proxy_input, original, protocol, profile, summary)

    def check_once(
        self,
        proxy_str: str,
        profile: TargetProfile,
        stop_event: Optional[StopEvent] = None,
        timeout: Optional[int] = None,
        ip_hint: Optional[str] = None,
    ) -> RoundResult:
        if _is_stopped(stop_event):
            return RoundResult.stopped()

        result = RoundResult()
        proxy = {"http": proxy_str, "https": proxy_str}
        request_timeout = timeout if timeout is not None else self.config.timeout

        self._probe_service(result, profile, proxy, request_timeout)
        if profile.api_url:
            self._probe_api(result, profile, proxy, request_timeout)
        if ip_hint:
            result.ip = ip_hint
            self._probe_ip_info(result)
        else:
            self._probe_ip(result, proxy)
        return result

    async def check_once_async(
        self,
        proxy_str: str,
        profile: TargetProfile,
        session: cffi_requests.AsyncSession,
        stop_event: Optional[StopEvent] = None,
        timeout: Optional[int] = None,
        ip_hint: Optional[str] = None,
    ) -> RoundResult:
        if _is_stopped(stop_event):
            return RoundResult.stopped()

        result = RoundResult()
        proxy = {"http": proxy_str, "https": proxy_str}
        request_timeout = timeout if timeout is not None else self.config.timeout

        await self._probe_service_async(session, result, profile, proxy, request_timeout)
        checks = []
        if profile.api_url:
            checks.append(self._probe_api_async(session, result, profile, proxy, request_timeout))
        if ip_hint:
            result.ip = ip_hint
            checks.append(self._probe_ip_info_async(session, result))
        else:
            checks.append(self._probe_ip_async(session, result, proxy))
        await asyncio.gather(*checks)
        return result

    def _detect_protocol(
        self,
        bare_addr: str,
        profile: TargetProfile,
        stop_event: Optional[StopEvent],
    ) -> Optional[ProtocolDiscovery]:
        for prefix in self.config.protocol_prefixes:
            if _is_stopped(stop_event):
                return None
            candidate = prefix + bare_addr
            ip = self._probe_protocol(candidate, profile, stop_event)
            if ip is not None:
                return ProtocolDiscovery(candidate, ip)
        return None

    async def _detect_protocol_async(
        self,
        bare_addr: str,
        profile: TargetProfile,
        session: cffi_requests.AsyncSession,
        stop_event: Optional[StopEvent],
    ) -> Optional[ProtocolDiscovery]:
        for prefix in self.config.protocol_prefixes:
            if _is_stopped(stop_event):
                return None
            candidate = prefix + bare_addr
            ip = await self._probe_protocol_async(candidate, profile, session, stop_event)
            if ip is not None:
                return ProtocolDiscovery(candidate, ip)
        return None

    def _probe_protocol(self, proxy_str: str, profile: TargetProfile, stop_event: Optional[StopEvent]) -> Optional[str]:
        proxy = {"http": proxy_str, "https": proxy_str}
        for ip_endpoint in self.config.ip_targets:
            if _is_stopped(stop_event):
                return None
            try:
                response = cffi_requests.get(
                    ip_endpoint,
                    proxies=dict(proxy),
                    timeout=self.config.detect_timeout,
                    impersonate=self.config.impersonate,
                )
                if int(getattr(response, "status_code", 0) or 0) == 200:
                    return _extract_ip_from_response(response) or ""
            except Exception:
                continue
        try:
            response = cffi_requests.get(
                profile.api_url or profile.service_url,
                proxies=dict(proxy),
                timeout=self.config.detect_timeout,
                impersonate=self.config.impersonate,
            )
            if int(getattr(response, "status_code", 0) or 0) in PROTOCOL_FALLBACK_STATUS_CODES:
                return ""
        except Exception:
            pass
        return None

    async def _probe_protocol_async(
        self,
        proxy_str: str,
        profile: TargetProfile,
        session: cffi_requests.AsyncSession,
        stop_event: Optional[StopEvent],
    ) -> Optional[str]:
        proxy = {"http": proxy_str, "https": proxy_str}
        for ip_endpoint in self.config.ip_targets:
            if _is_stopped(stop_event):
                return None
            try:
                response = await session.get(
                    ip_endpoint,
                    proxies=dict(proxy),
                    timeout=self.config.detect_timeout,
                )
                if int(getattr(response, "status_code", 0) or 0) == 200:
                    return _extract_ip_from_response(response) or ""
            except Exception:
                continue
        try:
            response = await session.get(
                profile.api_url or profile.service_url,
                proxies=dict(proxy),
                timeout=self.config.detect_timeout,
            )
            if int(getattr(response, "status_code", 0) or 0) in PROTOCOL_FALLBACK_STATUS_CODES:
                return ""
        except Exception:
            pass
        return None

    def _probe_service(
        self,
        result: RoundResult,
        profile: TargetProfile,
        proxy: Mapping[str, str],
        timeout: int,
    ) -> bool:
        try:
            start = time.time()
            response = cffi_requests.get(
                profile.service_url,
                proxies=dict(proxy),
                timeout=timeout,
                impersonate=self.config.impersonate,
                allow_redirects=True,
            )
            result.latency = round((time.time() - start) * 1000)
            return _apply_service_response(result, profile, response)
        except Exception as exc:
            result.error = classify_error(str(exc))
            result.valid = False
            result.service_reachable = False
            result.checks_detail["service"] = {
                "status": None,
                "reachable": False,
                "target": profile.service_url,
                "error": result.error,
            }
            if profile.id == "openai":
                result.checks_detail["chat"] = result.checks_detail["service"]
            return False

    async def _probe_service_async(
        self,
        session: cffi_requests.AsyncSession,
        result: RoundResult,
        profile: TargetProfile,
        proxy: Mapping[str, str],
        timeout: int,
    ) -> bool:
        try:
            start = time.time()
            response = await session.get(
                profile.service_url,
                proxies=dict(proxy),
                timeout=timeout,
                allow_redirects=True,
            )
            result.latency = round((time.time() - start) * 1000)
            return _apply_service_response(result, profile, response)
        except Exception as exc:
            result.error = classify_error(str(exc))
            result.valid = False
            result.service_reachable = False
            result.checks_detail["service"] = {
                "status": None,
                "reachable": False,
                "target": profile.service_url,
                "error": result.error,
            }
            if profile.id == "openai":
                result.checks_detail["chat"] = result.checks_detail["service"]
            return False

    def _probe_api(
        self,
        result: RoundResult,
        profile: TargetProfile,
        proxy: Mapping[str, str],
        timeout: int,
    ) -> None:
        if profile.api_url is None:
            return
        try:
            response = cffi_requests.get(
                profile.api_url,
                proxies=dict(proxy),
                timeout=timeout,
                impersonate=self.config.impersonate,
            )
            _apply_api_response(result, profile, response)
        except Exception as exc:
            error = classify_error(str(exc))
            result.api_reachable = False
            result.checks_detail["api"] = {
                "status": None,
                "reachable": False,
                "target": profile.api_url,
                "error": error,
            }

    async def _probe_api_async(
        self,
        session: cffi_requests.AsyncSession,
        result: RoundResult,
        profile: TargetProfile,
        proxy: Mapping[str, str],
        timeout: int,
    ) -> None:
        if profile.api_url is None:
            return
        try:
            response = await session.get(
                profile.api_url,
                proxies=dict(proxy),
                timeout=timeout,
            )
            _apply_api_response(result, profile, response)
        except Exception as exc:
            error = classify_error(str(exc))
            result.api_reachable = False
            result.checks_detail["api"] = {
                "status": None,
                "reachable": False,
                "target": profile.api_url,
                "error": error,
            }

    def _probe_ip(self, result: RoundResult, proxy: Mapping[str, str]) -> None:
        for ip_endpoint in self.config.ip_targets:
            try:
                response = cffi_requests.get(
                    ip_endpoint,
                    proxies=dict(proxy),
                    timeout=6,
                    impersonate=self.config.impersonate,
                )
                if _apply_ip_response(result, response):
                    if result.ip:
                        self._probe_ip_info(result)
                    return
            except Exception as exc:
                result.checks_detail["ip"] = {
                    "endpoint": ip_endpoint,
                    "error": classify_error(str(exc)),
                }

    async def _probe_ip_async(
        self,
        session: cffi_requests.AsyncSession,
        result: RoundResult,
        proxy: Mapping[str, str],
    ) -> None:
        for ip_endpoint in self.config.ip_targets:
            try:
                response = await session.get(
                    ip_endpoint,
                    proxies=dict(proxy),
                    timeout=6,
                )
                if _apply_ip_response(result, response):
                    if result.ip:
                        await self._probe_ip_info_async(session, result)
                    return
            except Exception as exc:
                result.checks_detail["ip"] = {
                    "endpoint": ip_endpoint,
                    "error": classify_error(str(exc)),
                }

    def _probe_ip_info(self, result: RoundResult) -> None:
        if result.ip is None:
            return
        cached = self.ip_info_cache.get(result.ip)
        if cached is not None:
            _apply_ip_info_summary(result, cached, True)
            return
        for ip_info_target in self.config.ip_info_targets:
            try:
                response = cffi_requests.get(
                    ip_info_target.format(ip=result.ip),
                    timeout=5,
                    impersonate=self.config.impersonate,
                )
                summary = _apply_ip_info_response(result, response, ip_info_target)
                if summary is not None:
                    self.ip_info_cache.set(summary)
                    return
            except Exception as exc:
                result.ip_type = "unknown"
                result.checks_detail["ip_info"] = {
                    "ip": result.ip,
                    "type": result.ip_type,
                    "source": ip_info_target,
                    "error": classify_error(str(exc)),
                }

    async def _probe_ip_info_async(
        self,
        session: cffi_requests.AsyncSession,
        result: RoundResult,
    ) -> None:
        if result.ip is None:
            return
        cached = self.ip_info_cache.get(result.ip)
        if cached is not None:
            _apply_ip_info_summary(result, cached, True)
            return
        for ip_info_target in self.config.ip_info_targets:
            try:
                response = await session.get(
                    ip_info_target.format(ip=result.ip),
                    timeout=5,
                )
                summary = _apply_ip_info_response(result, response, ip_info_target)
                if summary is not None:
                    self.ip_info_cache.set(summary)
                    return
            except Exception as exc:
                result.ip_type = "unknown"
                result.checks_detail["ip_info"] = {
                    "ip": result.ip,
                    "type": result.ip_type,
                    "source": ip_info_target,
                    "error": classify_error(str(exc)),
                }

    def _has_protocol(self, proxy_input: str) -> bool:
        return proxy_input.startswith(self.config.protocol_prefixes)

    def _get_profile(self, target_profile: Optional[str]) -> TargetProfile:
        profile_id = target_profile or self.config.default_target_profile
        if profile_id == DEFAULT_TARGET_PROFILE:
            base_profile = TARGET_PROFILES[DEFAULT_TARGET_PROFILE]
            return TargetProfile(
                id=base_profile.id,
                name=base_profile.name,
                service_url=self.config.generic_target_url or DEFAULT_GENERIC_TARGET,
                service_indicators=(),
                service_ok_statuses=GENERIC_SERVICE_OK_STATUS_CODES,
            )
        return TARGET_PROFILES.get(profile_id, TARGET_PROFILES[DEFAULT_TARGET_PROFILE])

    def _protocol_failure(self, original: str, rounds: int, profile: TargetProfile) -> Dict[str, object]:
        return {
            "proxy": original,
            "original": original,
            "valid": False,
            "http_valid": False,
            "unstable": False,
            "grade": "F",
            "checks_passed": 0,
            "checks_total": rounds,
            "error": "所有协议均不可用(HTTP/HTTPS/SOCKS4/SOCKS5/SOCKS5H)",
            "latency": None,
            "status_code": None,
            "ip": None,
            "country": None,
            "ip_type": None,
            "base_reachable": False,
            "service_reachable": False,
            "api_reachable": None,
            "cf_bypass": False,
            "cf_challenge": False,
            "cf_challenge_type": None,
            "cf_indicators": [],
            "registration_ready": False,
            "registration_detail": None,
            "browser_checked": False,
            "browser_ready": None,
            "usable_for_browser": False,
            "recommended_use": "invalid",
            "detected_protocol": None,
            "target_profile": profile.id,
            "target_name": profile.name,
            "timestamp": time.time(),
            "checks_detail": {},
        }


def _apply_service_response(result: RoundResult, profile: TargetProfile, response: object) -> bool:
    status_code = int(getattr(response, "status_code", 0) or 0)
    result.status_code = status_code
    is_cf, cf_details = detect_cf_challenge(response)
    has_content = _has_service_content(profile, response, cf_details)
    result.checks_detail["service"] = {
        "status": status_code,
        "reachable": status_code in profile.service_ok_statuses,
        "target": profile.service_url,
        "cf_detected": is_cf,
        "cf_type": cf_details.get("cf_challenge_type"),
        "has_content": has_content,
        "size": cf_details.get("response_size", 0),
    }
    if profile.id == "openai":
        result.checks_detail["chat"] = result.checks_detail["service"]

    if status_code not in profile.service_ok_statuses:
        result.service_reachable = False
        result.valid = False
        result.error = f"HTTP {status_code}"
        return False

    if profile.use_cf_detection and is_cf and not has_content:
        result.service_reachable = False
        result.cf_challenge = True
        result.cf_challenge_type = _optional_str(cf_details.get("cf_challenge_type"))
        result.cf_indicators = _string_list(cf_details.get("cf_indicators"))
        result.valid = False
        challenge = result.cf_challenge_type or "unknown"
        result.error = f"CF拦截({challenge})"
        return False

    result.service_reachable = True
    result.cf_bypass = True
    result.valid = True
    if profile.use_cf_detection and is_cf:
        result.cf_challenge = True
        result.cf_challenge_type = "soft_challenge"
    return True


def _apply_api_response(result: RoundResult, profile: TargetProfile, response: object) -> None:
    status_code = int(getattr(response, "status_code", 0) or 0)
    result.api_reachable = status_code in profile.api_ok_statuses
    result.checks_detail["api"] = {
        "status": status_code,
        "reachable": result.api_reachable,
        "target": profile.api_url,
    }


def _apply_ip_response(result: RoundResult, response: object) -> bool:
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        return False
    ip = _extract_ip_from_response(response)
    if ip is None:
        return False
    result.ip = ip
    return True


def _apply_ip_info_response(result: RoundResult, response: object, source: str) -> Optional[IpInfoSummary]:
    if result.ip is None:
        return None
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code != 200:
        result.ip_type = "unknown"
        result.checks_detail["ip_info"] = {
            "ip": result.ip,
            "type": result.ip_type,
            "status": status_code,
            "source": source,
        }
        return None
    ip_info = getattr(response, "json")()
    if not isinstance(ip_info, Mapping):
        result.ip_type = "unknown"
        result.checks_detail["ip_info"] = {
            "ip": result.ip,
            "type": result.ip_type,
            "source": source,
            "error": "IP信息格式错误",
        }
        return None
    if ip_info.get("success") is False:
        result.ip_type = "unknown"
        result.checks_detail["ip_info"] = {
            "ip": result.ip,
            "type": result.ip_type,
            "source": source,
            "error": _string_value(ip_info.get("message")) or "IP信息查询失败",
        }
        return None
    org = _ip_info_org(ip_info)
    country = _ip_info_country(ip_info)
    summary = IpInfoSummary(
        ip=result.ip,
        org=org,
        country=country,
        ip_type=classify_ip_type(ip_info),
    )
    _apply_ip_info_summary(result, summary, False)
    result.checks_detail["ip_info"]["source"] = source
    return summary


def _apply_ip_info_summary(result: RoundResult, summary: IpInfoSummary, cached: bool) -> None:
    result.country = summary.country
    result.ip_type = summary.ip_type
    result.checks_detail["ip_info"] = {
        "ip": summary.ip,
        "org": summary.org,
        "country": summary.country,
        "type": result.ip_type,
        "cached": cached,
    }


class ScoreAggregator:
    def __init__(self, rounds: int, profile: TargetProfile):
        self.rounds = rounds
        self.profile = profile

    def summarize(self, results: Sequence[RoundResult]) -> ScoreSummary:
        representative = self._representative(results)
        service_passed = sum(1 for result in results if result.service_reachable is True)
        api_passed = sum(1 for result in results if result.api_reachable is True)
        base_passed = sum(1 for result in results if result.ip)
        cf_passed = sum(1 for result in results if result.cf_bypass)

        service_ok = service_passed == self.rounds
        api_ok = self.profile.api_url is not None and api_passed == self.rounds
        base_ok = base_passed == self.rounds
        cf_ok = not self.profile.use_cf_detection or cf_passed == self.rounds

        if self.profile.id == "generic":
            valid = service_ok and base_ok
            if valid:
                grade = "A"
            elif service_ok or base_ok:
                grade = "C"
            elif service_passed > 0 or base_passed > 0:
                grade = "D"
            else:
                grade = "F"
        elif service_ok and api_ok and cf_ok:
            grade = "A"
            valid = True
        elif service_ok or api_ok:
            grade = "B"
            valid = True
        elif base_ok:
            grade = "C"
            valid = True
        elif service_passed > 0 or api_passed > 0 or base_passed > 0:
            grade = "D"
            valid = False
        else:
            grade = "F"
            valid = False

        best_passed = max(service_passed, api_passed, base_passed)
        unstable = best_passed > 0 and not valid
        latencies = [result.latency for result in results if result.latency is not None]
        latency = round(statistics.median(latencies)) if latencies else representative.latency
        detail = {
            "rounds_completed": len(results),
            "service_passed": service_passed,
            "chat_passed": service_passed,
            "api_passed": api_passed,
            "base_passed": base_passed,
            "registration_passed": 0,
            "cf_bypass_passed": cf_passed,
            "service_ok": service_ok,
            "api_ok": api_ok,
            "base_ok": base_ok,
            "target_profile": self.profile.id,
            "target_name": self.profile.name,
            "recommended_use": _recommended_use(self.profile, service_ok, api_ok, base_ok, unstable),
        }
        return ScoreSummary(
            grade=grade,
            valid=valid,
            unstable=unstable,
            checks_passed=best_passed,
            checks_total=self.rounds,
            latency=latency,
            representative=representative,
            detail=detail,
        )

    def _representative(self, results: Sequence[RoundResult]) -> RoundResult:
        if not results:
            return RoundResult(error="未完成检测")
        return max(results, key=_result_score)


def classify_error(err: str) -> str:
    text = err.lower()
    if "timeout" in text or "timed out" in text:
        return "连接超时"
    if "refused" in text:
        return "连接被拒绝"
    if "resolve" in text or "dns" in text:
        return "DNS解析失败"
    if "socks" in text:
        return "SOCKS握手失败"
    if "ssl" in text or "certificate" in text:
        return "SSL/TLS错误"
    if "auth" in text or "407" in text:
        return "代理需要认证"
    if "connection reset" in text:
        return "连接被重置"
    if "eof" in text:
        return "连接异常断开"
    return err[:100]


def detect_cf_challenge(resp: object) -> Tuple[bool, Dict[str, object]]:
    text = getattr(resp, "text", "") or ""
    details: Dict[str, object] = {
        "cf_detected": False,
        "cf_challenge_type": None,
        "cf_indicators": [],
        "response_size": len(text),
        "has_real_content": False,
    }
    indicators: List[str] = []
    headers = getattr(resp, "headers", {}) or {}
    headers_lower = {str(key).lower(): str(value) for key, value in headers.items()}
    for indicator in CF_HEADER_INDICATORS:
        if any(indicator in key for key in headers_lower):
            indicators.append(f"header:{indicator}")

    body_lower = text.lower()
    for indicator in CF_BODY_INDICATORS:
        if indicator.lower() in body_lower:
            indicators.append(f"body:{indicator}")

    if indicators:
        details["cf_detected"] = True
        details["cf_indicators"] = indicators
        if "turnstile" in body_lower or "cf-turnstile" in body_lower:
            details["cf_challenge_type"] = "turnstile"
        elif "managed-challenge" in body_lower or "challenge-platform" in body_lower:
            details["cf_challenge_type"] = "managed"
        elif "just a moment" in body_lower or "checking your browser" in body_lower:
            details["cf_challenge_type"] = "js"
        elif getattr(resp, "status_code", None) == 403:
            details["cf_challenge_type"] = "block"
        else:
            details["cf_challenge_type"] = "unknown"

    has_real_content = any(indicator.lower() in body_lower for indicator in OPENAI_REAL_PAGE_INDICATORS)
    details["has_real_content"] = has_real_content
    if details["cf_detected"] and has_real_content:
        details["cf_challenge_type"] = "soft_challenge"
    return bool(details["cf_detected"]), details


def _recommended_use(
    profile: TargetProfile,
    service_ok: bool,
    api_ok: bool,
    base_ok: bool,
    unstable: bool,
) -> str:
    if profile.id == "generic":
        if service_ok and base_ok:
            return "generic"
        return "unstable" if unstable else "invalid"
    if service_ok and api_ok:
        return "web_api"
    if service_ok:
        return "web"
    if api_ok:
        return "api"
    if base_ok:
        return "generic"
    return "unstable" if unstable else "invalid"


def _has_service_content(profile: TargetProfile, response: object, cf_details: Mapping[str, object]) -> bool:
    text = (getattr(response, "text", "") or "").lower()
    if any(indicator.lower() in text for indicator in profile.service_indicators):
        return True
    if profile.id == "openai":
        return bool(cf_details.get("has_real_content", False))
    return False


def classify_ip_type(ip_info: Mapping[str, object]) -> str:
    org = _ip_info_org(ip_info).lower()
    if not org:
        return "unknown"
    datacenter_keywords = (
        "amazon",
        "aws",
        "google",
        "cloudflare",
        "azure",
        "microsoft",
        "digitalocean",
        "linode",
        "vultr",
        "hetzner",
        "ovh",
        "oracle",
        "alibaba",
        "tencent",
        "datacenter",
        "hosting",
        "server",
        "cloud",
    )
    if any(keyword in org for keyword in datacenter_keywords):
        return "datacenter"
    residential_keywords = (
        "broadband",
        "cable",
        "communications",
        "fiber",
        "isp",
        "mobile",
        "telecom",
        "telecommunications",
        "wireless",
    )
    if any(keyword in org for keyword in residential_keywords):
        return "residential"
    return "unknown"


def _ip_info_org(ip_info: Mapping[str, object]) -> str:
    connection = ip_info.get("connection")
    if isinstance(connection, Mapping):
        nested_org = _string_value(connection.get("org")) or _string_value(connection.get("isp"))
        if nested_org:
            return nested_org
    return _string_value(ip_info.get("org")) or _string_value(ip_info.get("isp"))


def _ip_info_country(ip_info: Mapping[str, object]) -> str:
    return _string_value(ip_info.get("country_code")) or _string_value(ip_info.get("country"))


def _build_public_result(
    proxy: str,
    original: str,
    protocol: Optional[str],
    profile: TargetProfile,
    summary: ScoreSummary,
) -> Dict[str, object]:
    result = summary.representative
    checks_detail = dict(result.checks_detail)
    checks_detail["summary"] = summary.detail
    checks_detail["targets"] = {
        "profile": profile.id,
        "name": profile.name,
        "service": profile.service_url,
        "api": profile.api_url,
    }
    return {
        "proxy": proxy,
        "original": original,
        "valid": summary.valid,
        "http_valid": summary.valid,
        "unstable": summary.unstable,
        "grade": summary.grade,
        "checks_passed": summary.checks_passed,
        "checks_total": summary.checks_total,
        "error": _summary_error(summary, result),
        "latency": summary.latency,
        "status_code": result.status_code,
        "ip": result.ip,
        "country": result.country,
        "ip_type": result.ip_type,
        "base_reachable": result.ip is not None,
        "service_reachable": result.service_reachable,
        "api_reachable": result.api_reachable,
        "cf_bypass": result.cf_bypass,
        "cf_challenge": result.cf_challenge,
        "cf_challenge_type": result.cf_challenge_type,
        "cf_indicators": result.cf_indicators,
        "registration_ready": result.registration_ready,
        "registration_detail": result.registration_detail,
        "browser_checked": False,
        "browser_ready": None,
        "usable_for_browser": summary.valid,
        "recommended_use": summary.detail.get("recommended_use", "invalid"),
        "detected_protocol": protocol,
        "target_profile": profile.id,
        "target_name": profile.name,
        "timestamp": time.time(),
        "checks_detail": checks_detail,
    }


def _result_score(result: RoundResult) -> Tuple[int, int, int, int, int]:
    latency = result.latency if result.latency is not None else 999999
    return (
        1 if result.service_reachable is True else 0,
        1 if result.api_reachable is True else 0,
        1 if result.ip else 0,
        1 if result.cf_bypass else 0,
        -latency,
    )


def _summary_error(summary: ScoreSummary, result: RoundResult) -> Optional[str]:
    if summary.valid:
        return None
    if result.error:
        return result.error
    detail = summary.detail
    return (
        "稳定性不足("
        f"服务 {detail.get('service_passed', 0)}/{summary.checks_total}, "
        f"API {detail.get('api_passed', 0)}/{summary.checks_total}, "
        f"出口IP {detail.get('base_passed', 0)}/{summary.checks_total})"
    )


def _is_stopped(stop_event: Optional[StopEvent]) -> bool:
    return bool(stop_event and stop_event.is_set())


def _extract_ip(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    first = value.split(",", 1)[0].strip()
    return first or None


def _extract_ip_from_response(response: object) -> Optional[str]:
    try:
        ip_data = getattr(response, "json")()
    except Exception:
        return None
    if not isinstance(ip_data, Mapping):
        return None
    return _extract_ip(ip_data.get("origin") or ip_data.get("ip"))


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _optional_str(value: object) -> Optional[str]:
    return value if isinstance(value, str) else None


def _string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
