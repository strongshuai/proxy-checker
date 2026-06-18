"""
Proxy Checker - Vercel Serverless Version
"""
import json
import time
import os
import sys
import threading
import asyncio
import hashlib
import hmac
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_from_directory, abort, make_response

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from proxy_check import CheckConfig, DEFAULT_GENERIC_TARGET, ProxyCheckEngine, TARGET_PROFILE_OPTIONS

app = Flask(__name__, static_folder=None)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Proxy-Auth"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def load_config():
    config = {}
    for name in ("config.json", "config.local.json"):
        path = os.path.join(ROOT_DIR, name)
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            config.update(loaded)
    return config


CONFIG = load_config()


def get_config_value(key, env_name, default):
    if env_name in os.environ:
        return os.environ[env_name]
    return CONFIG.get(key, default)


def get_config_int(key, env_name, default):
    try:
        return int(get_config_value(key, env_name, default))
    except (TypeError, ValueError):
        return default

def normalize_target_url(value):
    """规范化常规检测目标 URL，仅允许 HTTP/HTTPS。"""
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    # Serverless 不保存设置，但仍保持返回值和自托管入口一致。
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return DEFAULT_GENERIC_TARGET
    return raw

# ============================================================
# Configuration
# ============================================================
TIMEOUT = 10
DETECT_TIMEOUT = 6
MAX_CONCURRENT = get_config_int("max_concurrent", "MAX_CONCURRENT", 20)
MAX_CONCURRENT_LIMIT = get_config_int("max_concurrent_limit", "MAX_CONCURRENT_LIMIT", 200)
CHECK_ROUNDS = get_config_int("check_rounds", "CHECK_ROUNDS", 2)
MAX_CHECK_ROUNDS = max(1, min(3, get_config_int("max_check_rounds", "MAX_CHECK_ROUNDS", 3)))
CHECK_ROUNDS = max(1, min(MAX_CHECK_ROUNDS, CHECK_ROUNDS))
RUN_LOG_LIMIT = get_config_int("run_log_limit", "RUN_LOG_LIMIT", 100)
APP_TIMEZONE = str(get_config_value("timezone", "APP_TIMEZONE", "UTC"))
GENERIC_TARGET_URL = normalize_target_url(get_config_value("generic_target_url", "GENERIC_TARGET_URL", DEFAULT_GENERIC_TARGET))
TIMEZONE_OPTIONS = (
    {"id": "UTC", "name": "UTC"},
    {"id": "Asia/Shanghai", "name": "中国/新加坡/马来西亚 UTC+8"},
    {"id": "Asia/Tokyo", "name": "日本/韩国 UTC+9"},
    {"id": "Europe/London", "name": "伦敦"},
    {"id": "America/New_York", "name": "美国东部"},
    {"id": "America/Los_Angeles", "name": "美国西部"},
)
AUTH_PASSWORD = str(get_config_value("auth_password", "AUTH_PASSWORD", "linux.do"))
AUTH_SESSION_DAYS = get_config_int("auth_session_days", "AUTH_SESSION_DAYS", 7)
AUTH_COOKIE_NAME = "proxy_checker_auth"
AUTH_SESSION_SECONDS = max(1, AUTH_SESSION_DAYS) * 86400
AUTH_SESSION_SECRET = str(get_config_value("auth_session_secret", "AUTH_SESSION_SECRET", AUTH_PASSWORD))

check_engine = ProxyCheckEngine(
    CheckConfig(
        timeout=TIMEOUT,
        detect_timeout=DETECT_TIMEOUT,
        check_rounds=CHECK_ROUNDS,
        generic_target_url=GENERIC_TARGET_URL,
    )
)

sessions = {}
sessions_lock = threading.Lock()
TARGET_PROFILE_IDS = {str(item["id"]) for item in TARGET_PROFILE_OPTIONS}


def normalize_target_profile(value):
    profile_id = str(value or "generic")
    return profile_id if profile_id in TARGET_PROFILE_IDS else "generic"

def normalize_max_concurrent(value):
    try:
        concurrent = int(value)
    except (TypeError, ValueError):
        concurrent = MAX_CONCURRENT
    return max(1, min(MAX_CONCURRENT_LIMIT, concurrent))

def normalize_rounds(value):
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        rounds = CHECK_ROUNDS
    return max(1, min(MAX_CHECK_ROUNDS, rounds))

def public_settings_payload():
    return {
        "check_rounds": CHECK_ROUNDS,
        "max_check_rounds": MAX_CHECK_ROUNDS,
        "max_concurrent": MAX_CONCURRENT,
        "max_concurrent_limit": MAX_CONCURRENT_LIMIT,
        "timeout": TIMEOUT,
        "detect_timeout": DETECT_TIMEOUT,
        "auth_session_days": AUTH_SESSION_DAYS,
        "run_log_limit": RUN_LOG_LIMIT,
        "timezone": APP_TIMEZONE,
        "generic_target_url": GENERIC_TARGET_URL,
        "timezone_options": list(TIMEZONE_OPTIONS),
        "password_configurable": False,
    }

def is_auth_enabled():
    return bool(AUTH_PASSWORD)

def make_auth_token():
    issued_at = str(int(time.time()))
    signature = hmac.new(
        AUTH_SESSION_SECRET.encode("utf-8"),
        issued_at.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{issued_at}:{signature}"

def verify_auth_token(token):
    if not is_auth_enabled():
        return True
    try:
        issued_at, signature = str(token or "").split(":", 1)
        issued_at_int = int(issued_at)
    except (TypeError, ValueError):
        return False
    if time.time() - issued_at_int > AUTH_SESSION_SECONDS:
        return False
    expected = hmac.new(
        AUTH_SESSION_SECRET.encode("utf-8"),
        issued_at.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

def get_bearer_token():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.headers.get("X-Proxy-Auth", "").strip()

def is_request_authenticated():
    return verify_auth_token(get_bearer_token() or request.cookies.get(AUTH_COOKIE_NAME, ""))

def unauthorized_response():
    return jsonify({"error": "请先输入登录密码", "auth_required": True}), 401

def run_check(session_id, proxies, rounds=None, target_profile=None, max_concurrent=None):
    if rounds is None: rounds = CHECK_ROUNDS
    max_concurrent = normalize_max_concurrent(max_concurrent)
    with sessions_lock: sessions[session_id]["stop"] = threading.Event()
    stop_event = sessions[session_id]["stop"]
    def publish_result(result):
        if result:
            with sessions_lock:
                s = sessions.get(session_id)
                if s: s["results"].append(result); s["done"] += 1
    async def run_async():
        await check_engine.check_many_async(
            proxies=proxies,
            stop_event=stop_event,
            rounds=rounds,
            max_concurrent=max_concurrent,
            on_result=publish_result,
            target_profile=target_profile,
        )
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_async())
    finally: loop.close()
    with sessions_lock:
        s = sessions.get(session_id)
        if s: s["finished"] = True

# ============================================================
# Session cleanup
# ============================================================
def cleanup_sessions():
    while True:
        time.sleep(120)
        now = time.time()
        with sessions_lock:
            to_del = [k for k, v in sessions.items() if v.get("finished") and now - v.get("created", now) > 600]
            for k in to_del: del sessions[k]

threading.Thread(target=cleanup_sessions, daemon=True).start()

# ============================================================
# Flask Routes
# ============================================================
@app.route('/')
def index():
    if is_auth_enabled() and not is_request_authenticated():
        return send_from_directory(ROOT_DIR, 'login.html')
    return send_from_directory(ROOT_DIR, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    if path == "login.html":
        return send_from_directory(ROOT_DIR, path)
    if path == "index.html" and is_auth_enabled() and not is_request_authenticated():
        return send_from_directory(ROOT_DIR, 'login.html')
    if path == "app.js" and is_auth_enabled() and not is_request_authenticated():
        return unauthorized_response()
    if path in ("index.html", "app.js"):
        return send_from_directory(ROOT_DIR, path)
    abort(404)

@app.route('/api/auth/status', methods=['POST'])
def api_auth_status():
    return jsonify({"authenticated": is_request_authenticated(), "auth_required": is_auth_enabled()})

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    data = request.get_json(force=True) or {}
    password = str(data.get("password", ""))
    if not hmac.compare_digest(password, AUTH_PASSWORD):
        return jsonify({"error": "密码不正确", "auth_required": True}), 401
    token = make_auth_token()
    response = make_response(jsonify({"ok": True, "token": token, "expires_in": AUTH_SESSION_SECONDS, "auth_required": is_auth_enabled()}))
    response.set_cookie(AUTH_COOKIE_NAME, token, max_age=AUTH_SESSION_SECONDS, httponly=True, samesite="Lax", path="/")
    return response

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    response = make_response(jsonify({"ok": True}))
    response.set_cookie(AUTH_COOKIE_NAME, "", max_age=0, httponly=True, samesite="Lax", path="/")
    return response

@app.route('/api/start', methods=['POST'])
def api_start():
    if not is_request_authenticated():
        return unauthorized_response()
    data = request.get_json(force=True) or {}
    proxies = data.get("proxies", [])
    rounds = normalize_rounds(data.get("rounds", CHECK_ROUNDS))
    target_profile = normalize_target_profile(data.get("target_profile", "generic"))
    max_concurrent = normalize_max_concurrent(data.get("max_concurrent", MAX_CONCURRENT))
    sid = str(time.time()) + str(id(proxies))
    with sessions_lock:
        sessions[sid] = {"results": [], "done": 0, "finished": False, "stop": None, "total": len(proxies), "created": time.time(), "rounds": rounds, "target_profile": target_profile, "max_concurrent": max_concurrent}
    threading.Thread(target=run_check, args=(sid, proxies, rounds, target_profile, max_concurrent), daemon=True).start()
    return jsonify({"session_id": sid, "total": len(proxies), "rounds": rounds, "target_profile": target_profile, "max_concurrent": max_concurrent})

@app.route('/api/status', methods=['POST'])
def api_status():
    if not is_request_authenticated():
        return unauthorized_response()
    data = request.get_json(force=True) or {}
    sid = data.get("session_id", ""); since = data.get("since", 0)
    with sessions_lock:
        s = sessions.get(sid)
        if not s: return jsonify({"error": "not found"})
        all_r = s["results"]; new_r = all_r[since:]
        return jsonify({"new": new_r, "total_done": s["done"], "total": s["total"], "finished": s["finished"],
                        "target_profile": s.get("target_profile", "generic"),
                        "max_concurrent": s.get("max_concurrent", MAX_CONCURRENT),
                        "valid_count": sum(1 for r in all_r if r.get("valid")),
                        "unstable_count": sum(1 for r in all_r if r.get("unstable")),
                        "invalid_count": sum(1 for r in all_r if not r.get("valid") and not r.get("unstable")),
                        "cf_bypass_count": sum(1 for r in all_r if r.get("cf_bypass"))})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    if not is_request_authenticated():
        return unauthorized_response()
    data = request.get_json(force=True) or {}
    sid = data.get("session_id", "")
    with sessions_lock:
        s = sessions.get(sid)
        if s and s.get("stop"): s["stop"].set()
    return jsonify({"ok": True})

@app.route('/api/capabilities', methods=['POST'])
def api_capabilities():
    try:
        from fetch_proxies import PROXY_SOURCES
        sources = [{"id": s["id"], "name": s["name"]} for s in PROXY_SOURCES]
        return jsonify({"nodriver": False, "xvfb": False, "deep_check": False, "fetch_proxies": True, "target_profiles": list(TARGET_PROFILE_OPTIONS), "max_concurrent": MAX_CONCURRENT, "max_concurrent_limit": MAX_CONCURRENT_LIMIT, "auth_required": is_auth_enabled(), "authenticated": is_request_authenticated(), "auto_mode": False, "auto_mode_hint": "Vercel / Serverless 不支持后台自动任务，请使用自托管 Python 服务", "settings": public_settings_payload(), "proxy_sources": sources, "hosted": "vercel"})
    except ImportError:
        return jsonify({"nodriver": False, "xvfb": False, "deep_check": False, "fetch_proxies": False, "target_profiles": list(TARGET_PROFILE_OPTIONS), "max_concurrent": MAX_CONCURRENT, "max_concurrent_limit": MAX_CONCURRENT_LIMIT, "auth_required": is_auth_enabled(), "authenticated": is_request_authenticated(), "auto_mode": False, "auto_mode_hint": "Vercel / Serverless 不支持后台自动任务，请使用自托管 Python 服务", "settings": public_settings_payload(), "proxy_sources": [], "hosted": "vercel"})

@app.route('/api/settings/get', methods=['POST'])
def api_settings_get():
    if not is_request_authenticated():
        return unauthorized_response()
    return jsonify({"settings": public_settings_payload(), "server_time": {"timestamp": int(time.time()), "text": time.strftime("%Y-%m-%d %H:%M:%S"), "timezone": APP_TIMEZONE}})

@app.route('/api/settings/save', methods=['POST'])
def api_settings_save():
    if not is_request_authenticated():
        return unauthorized_response()
    return jsonify({"error": "Vercel / Serverless 不支持保存运行设置，请使用自托管 Python 服务", "settings": public_settings_payload()})

@app.route('/api/logs/list', methods=['POST'])
def api_logs_list():
    if not is_request_authenticated():
        return unauthorized_response()
    return jsonify({"logs": [], "count": 0, "server_time": {"timestamp": int(time.time()), "text": time.strftime("%Y-%m-%d %H:%M:%S"), "timezone": APP_TIMEZONE}})

@app.route('/api/logs/clear', methods=['POST'])
def api_logs_clear():
    if not is_request_authenticated():
        return unauthorized_response()
    return jsonify({"ok": True, "logs": [], "count": 0})

@app.route('/api/auto/get', methods=['POST'])
@app.route('/api/auto/save', methods=['POST'])
@app.route('/api/auto/run-now', methods=['POST'])
@app.route('/api/auto/stop', methods=['POST'])
@app.route('/api/auto/status', methods=['POST'])
def api_auto_unsupported():
    if not is_request_authenticated():
        return unauthorized_response()
    return jsonify({
        "auto_mode": False,
        "error": "Vercel / Serverless 不支持后台自动任务，请使用自托管 Python 服务",
        "server_time": {"timestamp": int(time.time()), "text": time.strftime("%Y-%m-%d %H:%M:%S")},
    })

@app.route('/api/fetch-proxies', methods=['POST'])
def api_fetch_proxies():
    if not is_request_authenticated():
        return unauthorized_response()
    try:
        from fetch_proxies import fetch_proxies
    except ImportError:
        return jsonify({"error": "fetch_proxies 模块不可用"})
    data = request.get_json(force=True) or {}
    source_id = data.get("source", "proxifly")
    limit = min(int(data.get("limit", 500)), 2000)
    proxies, source_name, err = fetch_proxies(source_id, limit)
    if err:
        return jsonify({"error": err, "source": source_name})
    return jsonify({"proxies": proxies, "count": len(proxies), "source": source_name, "source_id": source_id})

# Vercel WSGI handler
app = app
