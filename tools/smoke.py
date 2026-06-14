from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from typing import Any, Dict


EXPECTED_PROFILES = {"generic", "openai", "grok", "gemini", "claude"}
EXPECTED_PROXY_SOURCES = {
    "proxifly",
    "proxynova",
    "hidemn",
    "freeproxy",
    "checkerproxy",
    "spysme_http",
    "spysme_socks",
    "proxyscrape_http",
    "proxyscrape_socks5",
    "geonode",
    "my_proxy",
    "roosterkid_https",
    "roosterkid_socks4",
    "roosterkid_socks5",
    "thespeedx_http",
    "thespeedx_socks4",
    "thespeedx_socks5",
    "databay_http",
    "databay_socks4",
    "databay_socks5",
    "iplocate_all",
    "iplocate_http",
    "iplocate_socks4",
    "iplocate_socks5",
    "vpslab_all_proxies",
    "vpslab_all_elite",
    "vpslab_http_all",
    "vpslab_http_ssl",
    "vpslab_http_elite",
    "vpslab_http_anonymous",
    "vpslab_socks4_all",
    "vpslab_socks5_all",
    "hookzof_socks5",
}
SMOKE_PROXY = "http://127.0.0.1:9"


def post_json(base_url: str, path: str, payload: Dict[str, Any], timeout: int = 15, token: str = "") -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(base_url: str, path: str, timeout: int = 15, token: str = "") -> str:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base_url.rstrip("/") + path, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def login(base_url: str, password: str) -> str:
    status = post_json(base_url, "/api/auth/status", {})
    if not status.get("auth_required") or status.get("authenticated"):
        return ""
    result = post_json(base_url, "/api/auth/login", {"password": password})
    token = str(result.get("token") or "")
    if not token:
        raise AssertionError(f"login did not return a token: {result}")
    return token


def wait_for_result(base_url: str, session_id: str, token: str) -> Dict[str, Any]:
    for _ in range(30):
        status = post_json(base_url, "/api/status", {"session_id": session_id, "since": 0}, token=token)
        if status.get("finished"):
            return status
        time.sleep(0.5)
    raise RuntimeError(f"session {session_id} did not finish")


def check_profile(base_url: str, profile_id: str, token: str) -> None:
    started = post_json(
        base_url,
        "/api/start",
        {"proxies": [SMOKE_PROXY], "rounds": 1, "target_profile": profile_id},
        token=token,
    )
    if started.get("target_profile") != profile_id:
        raise AssertionError(f"profile mismatch: {started}")
    status = wait_for_result(base_url, started["session_id"], token)
    if status.get("total") != 1 or status.get("total_done") != 1:
        raise AssertionError(f"unexpected status for {profile_id}: {status}")
    result = status["new"][0]
    for key in ("target_profile", "target_name", "base_reachable", "service_reachable", "recommended_use", "country", "checks_detail"):
        if key not in result:
            raise AssertionError(f"{profile_id} missing {key}: {result}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", default=os.environ.get("AUTH_PASSWORD", "linux.do"))
    args = parser.parse_args()

    capabilities = post_json(args.base_url, "/api/capabilities", {})
    if "auto_mode" not in capabilities:
        raise AssertionError(f"capabilities missing auto_mode: {capabilities}")
    if "auto_mode_hint" not in capabilities:
        raise AssertionError(f"capabilities missing auto_mode_hint: {capabilities}")
    if "log_file" in (capabilities.get("settings") or {}):
        raise AssertionError(f"capabilities should not expose log_file: {capabilities}")
    profile_ids = {item["id"] for item in capabilities.get("target_profiles", [])}
    if profile_ids != EXPECTED_PROFILES:
        raise AssertionError(f"unexpected target profiles: {profile_ids}")
    profiles_with_signup = [item["id"] for item in capabilities.get("target_profiles", []) if item.get("has_signup")]
    if profiles_with_signup:
        raise AssertionError(f"signup detection should be disabled: {profiles_with_signup}")
    source_ids = {item["id"] for item in capabilities.get("proxy_sources", [])}
    if not EXPECTED_PROXY_SOURCES.issubset(source_ids):
        missing = EXPECTED_PROXY_SOURCES - source_ids
        raise AssertionError(f"missing proxy sources: {missing}")

    auth_required = bool(capabilities.get("auth_required"))
    login_html = get_text(args.base_url, "/index.html")
    if auth_required and 'id="password"' not in login_html and 'id="authPassword"' not in login_html:
        raise AssertionError("unauthenticated index.html should return login page")
    if auth_required and "app.js" in login_html:
        raise AssertionError("unauthenticated index.html should not return the main app shell")

    token = login(args.base_url, args.password)

    app_js = get_text(args.base_url, "/app.js", token=token)
    index_html = get_text(args.base_url, "/index.html", token=token)
    for expected in (
        "function restoreActiveSession()",
        "function recheckRepo()",
        "function openAutoSettings()",
        "function renderAutoStatus(",
        "function processAutoRealtimeResults(",
        "function maybePromptAutoStoppedRepo(",
        "function openAppSettings()",
        "function openRunLogs()",
        "target_profile",
    ):
        if expected not in app_js:
            raise AssertionError(f"app.js missing {expected}")
    if 'id="targetProfileDropdown"' not in index_html:
        raise AssertionError("index.html missing target profile dropdown")
    if 'id="autoModeBtn"' not in index_html:
        raise AssertionError("index.html missing auto mode button")
    if 'id="autoStatusBadge"' not in index_html:
        raise AssertionError("index.html missing auto status badge")
    if 'openAppSettings()' not in index_html:
        raise AssertionError("index.html missing settings button")
    if 'openRunLogs()' not in index_html:
        raise AssertionError("index.html missing run logs button")
    if 'id="authOverlay"' not in index_html:
        raise AssertionError("index.html missing auth overlay")

    settings = post_json(args.base_url, "/api/settings/get", {}, token=token)
    settings_data = settings.get("settings") or {}
    for key in ("check_rounds", "max_check_rounds", "max_concurrent", "max_concurrent_limit", "timezone", "timezone_options"):
        if key not in settings_data:
            raise AssertionError(f"settings missing {key}: {settings}")
    if "log_file" in settings_data:
        raise AssertionError(f"settings should not expose log_file: {settings_data}")
    if int(settings_data.get("max_check_rounds", 0)) != 3:
        raise AssertionError(f"max_check_rounds should be 3: {settings_data}")

    logs = post_json(args.base_url, "/api/logs/list", {"token": "smoke_auto"}, token=token)
    if "logs" not in logs:
        raise AssertionError(f"logs response missing logs: {logs}")

    auto_status = post_json(args.base_url, "/api/auto/status", {"token": "smoke_auto"}, token=token)
    if "new" not in auto_status or "results_index" not in auto_status:
        raise AssertionError(f"auto status missing realtime result fields: {auto_status}")
    if capabilities.get("auto_mode"):
        if not auto_status.get("auto_mode") or "config" not in auto_status or "state" not in auto_status:
            raise AssertionError(f"unexpected auto status: {auto_status}")
    elif auto_status.get("auto_mode") is not False:
        raise AssertionError(f"serverless auto status should be unsupported: {auto_status}")

    default_started = post_json(args.base_url, "/api/start", {"proxies": [SMOKE_PROXY], "rounds": 1}, token=token)
    if default_started.get("target_profile") != "generic":
        raise AssertionError(f"default profile is not generic: {default_started}")
    wait_for_result(args.base_url, default_started["session_id"], token)

    for profile_id in sorted(EXPECTED_PROFILES):
        check_profile(args.base_url, profile_id, token)

    print("smoke ok")


if __name__ == "__main__":
    main()
