import json
import time
import os
import sys
import threading
import asyncio
import logging
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from http import cookies
from http.server import HTTPServer
from socketserver import ThreadingMixIn

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from proxy_check import CheckConfig, DEFAULT_TARGET_CHAT, ProxyCheckEngine, TARGET_PROFILE_OPTIONS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_LOCAL_PATH = os.path.join(BASE_DIR, "config.local.json")


def load_config():
    config = {}
    for name in ("config.json", "config.local.json"):
        path = os.path.join(BASE_DIR, name)
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

# ============================================================
# My Repository — save/retrieve repo proxies as txt
# ============================================================
REPO_DIR = os.path.join(BASE_DIR, 'repo_data')
os.makedirs(REPO_DIR, exist_ok=True)

# Checked proxies persistence — per-token checked history
CHECKED_DIR = os.path.join(BASE_DIR, 'checked_data')
os.makedirs(CHECKED_DIR, exist_ok=True)

# Auto mode persistence — per-token schedule and run state
AUTO_DIR = os.path.join(BASE_DIR, 'auto_data')
os.makedirs(AUTO_DIR, exist_ok=True)

# Run log persistence — per-token manual and auto task summaries
RUN_LOG_DIR = os.path.join(BASE_DIR, 'run_logs')
os.makedirs(RUN_LOG_DIR, exist_ok=True)

# === Fetch free proxies from external sources ===
try:
    from fetch_proxies import fetch_proxies, PROXY_SOURCES
    FETCH_PROXIES_AVAILABLE = True
except ImportError:
    FETCH_PROXIES_AVAILABLE = False

# === Try to import nodriver for deep check ===
NODRIVER_AVAILABLE = False
try:
    import nodriver
    NODRIVER_AVAILABLE = True
except ImportError:
    pass

# === Try to install Xvfb for headless Chrome ===
XVFB_AVAILABLE = False
try:
    import subprocess
    _xvfb_check = subprocess.run(["which", "Xvfb"], capture_output=True, timeout=3)
    XVFB_AVAILABLE = _xvfb_check.returncode == 0
except Exception:
    pass

LOG_FILE_PATH = str(get_config_value("log_file", "LOG_FILE", os.path.join(BASE_DIR, "server.log")))
if not os.path.isabs(LOG_FILE_PATH):
    LOG_FILE_PATH = os.path.join(BASE_DIR, LOG_FILE_PATH)

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE_PATH, encoding='utf-8')
    ]
)
log = logging.getLogger('vpntest')

# ============================================================
# Configuration
# ============================================================
TIMEZONE_OPTIONS = (
    {"id": "UTC", "name": "UTC"},
    {"id": "Asia/Shanghai", "name": "中国/新加坡/马来西亚 UTC+8"},
    {"id": "Asia/Tokyo", "name": "日本/韩国 UTC+9"},
    {"id": "Asia/Bangkok", "name": "泰国/越南 UTC+7"},
    {"id": "Asia/Dubai", "name": "迪拜 UTC+4"},
    {"id": "Europe/London", "name": "伦敦"},
    {"id": "Europe/Berlin", "name": "欧洲中部"},
    {"id": "America/New_York", "name": "美国东部"},
    {"id": "America/Chicago", "name": "美国中部"},
    {"id": "America/Denver", "name": "美国山地"},
    {"id": "America/Los_Angeles", "name": "美国西部"},
    {"id": "Australia/Sydney", "name": "悉尼"},
)
TIMEZONE_IDS = {item["id"] for item in TIMEZONE_OPTIONS}
TIMEOUT = get_config_int("timeout", "TIMEOUT", 12)
DETECT_TIMEOUT = get_config_int("detect_timeout", "DETECT_TIMEOUT", 8)
MAX_CONCURRENT = get_config_int("max_concurrent", "MAX_CONCURRENT", 30)
MAX_CONCURRENT_LIMIT = get_config_int("max_concurrent_limit", "MAX_CONCURRENT_LIMIT", 200)
CHECK_ROUNDS = get_config_int("check_rounds", "CHECK_ROUNDS", 2)
MAX_CHECK_ROUNDS = get_config_int("max_check_rounds", "MAX_CHECK_ROUNDS", 3)
RUN_LOG_LIMIT = get_config_int("run_log_limit", "RUN_LOG_LIMIT", 100)
PORT = get_config_int("port", "PORT", 8888)
AUTH_PASSWORD = str(get_config_value("auth_password", "AUTH_PASSWORD", "linux.do"))
AUTH_SESSION_DAYS = get_config_int("auth_session_days", "AUTH_SESSION_DAYS", 7)
AUTH_COOKIE_NAME = "proxy_checker_auth"
AUTH_SESSION_SECONDS = max(1, AUTH_SESSION_DAYS) * 86400
AUTH_SESSION_SECRET = str(get_config_value("auth_session_secret", "AUTH_SESSION_SECRET", AUTH_PASSWORD))
APP_TIMEZONE = str(get_config_value("timezone", "APP_TIMEZONE", "UTC"))
MAX_CHECK_ROUNDS = max(1, min(10, MAX_CHECK_ROUNDS))
CHECK_ROUNDS = max(1, min(MAX_CHECK_ROUNDS, CHECK_ROUNDS))
RUN_LOG_LIMIT = max(20, min(1000, RUN_LOG_LIMIT))
if APP_TIMEZONE not in TIMEZONE_IDS:
    APP_TIMEZONE = "UTC"

TARGET_CHAT = DEFAULT_TARGET_CHAT
check_engine = ProxyCheckEngine(
    CheckConfig(
        timeout=TIMEOUT,
        detect_timeout=DETECT_TIMEOUT,
        check_rounds=CHECK_ROUNDS,
    )
)

sessions = {}
sessions_lock = threading.Lock()
auto_runtime = {}
auto_stopped_results = {}
auto_lock = threading.Lock()
TARGET_PROFILE_IDS = {str(item["id"]) for item in TARGET_PROFILE_OPTIONS}


def normalize_target_profile(value):
    profile_id = str(value or "generic")
    return profile_id if profile_id in TARGET_PROFILE_IDS else "generic"


def get_target_profile_name(value):
    profile_id = normalize_target_profile(value)
    for item in TARGET_PROFILE_OPTIONS:
        if item["id"] == profile_id:
            return item["name"]
    return profile_id


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


def normalize_interval_hours(value):
    try:
        interval_hours = float(value)
    except (TypeError, ValueError):
        interval_hours = 6
    return max(0.01, min(720, interval_hours))


def normalize_timeout(value, default):
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = default
    return max(3, min(120, timeout))


def normalize_timezone(value):
    timezone_id = str(value or APP_TIMEZONE or "UTC").strip()
    return timezone_id if timezone_id in TIMEZONE_IDS else "UTC"


def get_timezone(timezone_id):
    timezone_id = normalize_timezone(timezone_id)
    if ZoneInfo is not None:
        try:
            return ZoneInfo(timezone_id)
        except Exception:
            pass
    if timezone_id == "Asia/Shanghai":
        return timezone(timedelta(hours=8))
    if timezone_id == "Asia/Tokyo":
        return timezone(timedelta(hours=9))
    if timezone_id == "Asia/Bangkok":
        return timezone(timedelta(hours=7))
    if timezone_id == "Asia/Dubai":
        return timezone(timedelta(hours=4))
    if timezone_id == "Europe/Berlin":
        return timezone(timedelta(hours=1))
    if timezone_id == "Europe/London":
        return timezone.utc
    if timezone_id == "America/New_York":
        return timezone(timedelta(hours=-5))
    if timezone_id == "America/Chicago":
        return timezone(timedelta(hours=-6))
    if timezone_id == "America/Denver":
        return timezone(timedelta(hours=-7))
    if timezone_id == "America/Los_Angeles":
        return timezone(timedelta(hours=-8))
    if timezone_id == "Australia/Sydney":
        return timezone(timedelta(hours=10))
    return timezone.utc


def format_timestamp(timestamp, timezone_id=None):
    if not timestamp:
        return None
    tz_id = normalize_timezone(timezone_id or APP_TIMEZONE)
    dt = datetime.fromtimestamp(float(timestamp), get_timezone(tz_id))
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def sanitize_token(value):
    token = str(value or "default").strip()
    if token.replace("_", "").isalnum():
        return token
    return "default"


def atomic_write_json(path, data):
    tmp_path = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def atomic_write_text(path, text):
    tmp_path = f"{path}.tmp.{os.getpid()}.{threading.get_ident()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp_path, path)


def read_json_file(path, fallback):
    if not os.path.isfile(path):
        return fallback
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data is not None else fallback
    except Exception as exc:
        log.warning("Failed to read json file", extra={"path": path, "error": str(exc)})
        return fallback


def proxy_key(value):
    return str(value or "").strip().lower()


def normalize_proxy_list(items):
    out = []
    seen = set()
    for item in items or []:
        if isinstance(item, dict):
            proxy = str(item.get("proxy", "")).strip()
        else:
            proxy = str(item or "").strip()
        if not proxy:
            continue
        key = proxy_key(proxy)
        if key in seen:
            continue
        seen.add(key)
        out.append(proxy)
    return out


def repo_json_path(token):
    return os.path.join(REPO_DIR, f"{sanitize_token(token)}.json")


def repo_txt_path(token):
    return os.path.join(REPO_DIR, f"{sanitize_token(token)}.txt")


def checked_txt_path(token):
    return os.path.join(CHECKED_DIR, f"{sanitize_token(token)}.txt")


def auto_json_path(token):
    return os.path.join(AUTO_DIR, f"{sanitize_token(token)}.json")


def run_log_json_path(token):
    return os.path.join(RUN_LOG_DIR, f"{sanitize_token(token)}.json")


def compact_repo_item(item):
    if not isinstance(item, dict):
        item = {"proxy": str(item or "")}
    proxy = str(item.get("proxy", "")).strip()
    if not proxy:
        return None
    now = int(time.time() * 1000)
    compact = {"proxy": proxy, "grade": str(item.get("grade") or "?")}
    for key in ("latency", "ip", "country", "ip_type", "recommended_use", "target_profile", "target_name"):
        value = item.get(key)
        if value is not None and value != "":
            compact[key] = value
    for key in ("service_reachable", "api_reachable", "cf_bypass"):
        if item.get(key) is True:
            compact[key] = True
    compact["added"] = item.get("added") or now
    compact["updated"] = item.get("updated") or compact["added"]
    return compact


def compact_repo(repo):
    out = []
    seen = set()
    for item in repo or []:
        compact = compact_repo_item(item)
        if not compact:
            continue
        key = proxy_key(compact["proxy"])
        if key in seen:
            continue
        seen.add(key)
        out.append(compact)
    return out


def read_repo_data(token):
    token = sanitize_token(token)
    json_file = repo_json_path(token)
    if os.path.isfile(json_file):
        data = read_json_file(json_file, [])
        if isinstance(data, list):
            return compact_repo(data)
    txt_file = repo_txt_path(token)
    if not os.path.isfile(txt_file):
        return []
    with open(txt_file, "r", encoding="utf-8") as f:
        return compact_repo({"proxy": line.strip()} for line in f if line.strip())


def write_repo_data(token, repo):
    token = sanitize_token(token)
    repo = compact_repo(repo)
    atomic_write_json(repo_json_path(token), repo)
    atomic_write_text(repo_txt_path(token), "\n".join(item["proxy"] for item in repo))
    return repo


def read_checked_list(token):
    path = checked_txt_path(token)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def write_checked_list(token, proxies):
    proxies = normalize_proxy_list(proxies)
    atomic_write_text(checked_txt_path(token), "\n".join(proxies))
    return proxies


def append_checked_list(token, proxies):
    existing = read_checked_list(token)
    seen = {proxy_key(proxy) for proxy in existing}
    merged = list(existing)
    for proxy in normalize_proxy_list(proxies):
        key = proxy_key(proxy)
        if key not in seen:
            seen.add(key)
            merged.append(proxy)
    return write_checked_list(token, merged)


def compact_run_log(entry):
    if not isinstance(entry, dict):
        return None
    log_id = str(entry.get("id") or "").strip()
    if not log_id:
        return None
    out = {
        "id": log_id,
        "type": str(entry.get("type") or "manual"),
        "status": str(entry.get("status") or "running"),
        "started_at": int(entry.get("started_at") or time.time()),
    }
    for key in (
        "finished_at", "duration_seconds", "session_id", "reason", "target_profile",
        "target_name", "rounds", "max_concurrent", "detect_mode", "repo_update_policy",
        "schedule_type", "interval_hours", "daily_time", "timezone", "source_count",
        "repo_input_count", "repo_count", "input_count", "skipped", "total", "done",
        "valid_count", "unstable_count", "invalid_count", "repo_added", "repo_updated",
        "repo_removed", "error",
    ):
        value = entry.get(key)
        if value is not None and value != "":
            out[key] = value
    return out


def read_run_logs(token):
    data = read_json_file(run_log_json_path(token), [])
    if not isinstance(data, list):
        return []
    logs = [compact_run_log(item) for item in data]
    return [item for item in logs if item]


def write_run_logs(token, logs):
    cleaned = [compact_run_log(item) for item in logs]
    cleaned = [item for item in cleaned if item]
    cleaned.sort(key=lambda item: int(item.get("started_at") or 0), reverse=True)
    atomic_write_json(run_log_json_path(token), cleaned[:RUN_LOG_LIMIT])
    return cleaned[:RUN_LOG_LIMIT]


def start_run_log(token, entry):
    token = sanitize_token(token)
    now = int(time.time())
    entry = dict(entry or {})
    entry.setdefault("id", f"log_{now}_{threading.get_ident()}")
    entry.setdefault("started_at", now)
    entry.setdefault("status", "running")
    logs = read_run_logs(token)
    logs.insert(0, entry)
    write_run_logs(token, logs)
    return entry["id"]


def finish_run_log(token, log_id, updates):
    token = sanitize_token(token)
    logs = read_run_logs(token)
    now = int(time.time())
    found = False
    for item in logs:
        if item.get("id") != log_id:
            continue
        item.update(updates or {})
        item.setdefault("finished_at", now)
        item["duration_seconds"] = max(0, int(item.get("finished_at") or now) - int(item.get("started_at") or now))
        found = True
        break
    if not found:
        entry = dict(updates or {})
        entry["id"] = log_id
        entry.setdefault("started_at", now)
        entry.setdefault("finished_at", now)
        entry["duration_seconds"] = 0
        logs.insert(0, entry)
    return write_run_logs(token, logs)


def clear_run_logs(token):
    atomic_write_json(run_log_json_path(token), [])


def run_logs_payload(token):
    timezone_id = APP_TIMEZONE
    logs = read_run_logs(token)
    for item in logs:
        timezone_id = normalize_timezone(item.get("timezone", APP_TIMEZONE))
        item["started_text"] = format_timestamp(item.get("started_at"), timezone_id)
        item["finished_text"] = format_timestamp(item.get("finished_at"), timezone_id)
    return {
        "logs": logs,
        "count": len(logs),
        "server_time": server_time_payload(timezone_id),
    }


def default_auto_config():
    return {
        "enabled": False,
        "schedule_type": "interval",
        "interval_hours": 6,
        "daily_time": "03:00",
        "timezone": APP_TIMEZONE,
        "target_profile": "generic",
        "rounds": CHECK_ROUNDS,
        "max_concurrent": MAX_CONCURRENT,
        "detect_mode": "skip",
        "repo_update_policy": "stable_only",
    }


def default_auto_state(config=None):
    config = config or default_auto_config()
    return {
        "running": False,
        "status": "disabled" if not config.get("enabled") else "idle",
        "session_id": None,
        "stage": "idle",
        "started_at": None,
        "finished_at": None,
        "last_run_at": None,
        "next_run_at": None,
        "last_summary": None,
        "history": [],
    }


def normalize_daily_time(value):
    raw = str(value or "03:00").strip()
    parts = raw.split(":", 1)
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        hour, minute = 3, 0
    hour = max(0, min(23, hour))
    minute = max(0, min(59, minute))
    return f"{hour:02d}:{minute:02d}"


def normalize_auto_config(config):
    config = config if isinstance(config, dict) else {}
    defaults = default_auto_config()
    merged = {**defaults, **config}
    schedule_type = str(merged.get("schedule_type") or "interval")
    if schedule_type not in ("interval", "daily"):
        schedule_type = "interval"
    interval_hours = normalize_interval_hours(merged.get("interval_hours", defaults["interval_hours"]))
    detect_mode = str(merged.get("detect_mode") or "skip")
    if detect_mode not in ("skip", "force"):
        detect_mode = "skip"
    repo_update_policy = str(merged.get("repo_update_policy") or "stable_only")
    if repo_update_policy not in ("stable_only", "include_unstable", "archive_all"):
        repo_update_policy = "stable_only"
    return {
        "enabled": bool(merged.get("enabled")),
        "schedule_type": schedule_type,
        "interval_hours": interval_hours,
        "daily_time": normalize_daily_time(merged.get("daily_time")),
        "timezone": normalize_timezone(merged.get("timezone", APP_TIMEZONE)),
        "target_profile": normalize_target_profile(merged.get("target_profile")),
        "rounds": CHECK_ROUNDS,
        "max_concurrent": normalize_max_concurrent(MAX_CONCURRENT),
        "detect_mode": detect_mode,
        "repo_update_policy": repo_update_policy,
    }


def compute_next_run(config, now=None):
    config = normalize_auto_config(config)
    if not config.get("enabled"):
        return None
    now = time.time() if now is None else float(now)
    if config["schedule_type"] == "daily":
        hour, minute = [int(part) for part in config["daily_time"].split(":", 1)]
        tz = get_timezone(config.get("timezone"))
        current = datetime.fromtimestamp(now, tz)
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target.timestamp() <= now:
            target = target + timedelta(days=1)
        return int(target.timestamp())
    return int(now + config["interval_hours"] * 3600)


def server_time_payload(timezone_id=None):
    now = time.time()
    tz_id = normalize_timezone(timezone_id or APP_TIMEZONE)
    return {
        "timestamp": int(now),
        "text": format_timestamp(now, tz_id),
        "timezone": tz_id,
        "server_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "server_timezone": time.strftime("%Z", time.localtime(now)),
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


def get_bearer_token(headers):
    auth_header = headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return headers.get("X-Proxy-Auth", "").strip()


def get_cookie_token(cookie_header):
    parsed = cookies.SimpleCookie()
    try:
        parsed.load(cookie_header or "")
    except cookies.CookieError:
        return ""
    morsel = parsed.get(AUTH_COOKIE_NAME)
    return morsel.value if morsel else ""


def is_request_authenticated(headers):
    return verify_auth_token(get_bearer_token(headers) or get_cookie_token(headers.get("Cookie", "")))


def make_auth_cookie(token, max_age=AUTH_SESSION_SECONDS):
    return f"{AUTH_COOKIE_NAME}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"


def read_local_config():
    if not os.path.isfile(CONFIG_LOCAL_PATH):
        return {}
    data = read_json_file(CONFIG_LOCAL_PATH, {})
    return data if isinstance(data, dict) else {}


def write_local_config(data):
    cleaned = data if isinstance(data, dict) else {}
    atomic_write_json(CONFIG_LOCAL_PATH, cleaned)
    return cleaned


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
        "port": PORT,
        "timezone_options": list(TIMEZONE_OPTIONS),
        "password_configurable": "AUTH_PASSWORD" not in os.environ,
    }


def apply_runtime_settings(settings):
    global TIMEOUT, DETECT_TIMEOUT, MAX_CONCURRENT, MAX_CONCURRENT_LIMIT
    global CHECK_ROUNDS, MAX_CHECK_ROUNDS, RUN_LOG_LIMIT, AUTH_PASSWORD
    global AUTH_SESSION_DAYS, AUTH_SESSION_SECONDS, AUTH_SESSION_SECRET
    global APP_TIMEZONE, check_engine

    if not isinstance(settings, dict):
        settings = {}
    MAX_CHECK_ROUNDS = max(1, min(10, get_int_from(settings, "max_check_rounds", MAX_CHECK_ROUNDS)))
    CHECK_ROUNDS = max(1, min(MAX_CHECK_ROUNDS, get_int_from(settings, "check_rounds", CHECK_ROUNDS)))
    MAX_CONCURRENT_LIMIT = max(1, min(1000, get_int_from(settings, "max_concurrent_limit", MAX_CONCURRENT_LIMIT)))
    MAX_CONCURRENT = max(1, min(MAX_CONCURRENT_LIMIT, get_int_from(settings, "max_concurrent", MAX_CONCURRENT)))
    TIMEOUT = normalize_timeout(settings.get("timeout"), TIMEOUT)
    DETECT_TIMEOUT = normalize_timeout(settings.get("detect_timeout"), DETECT_TIMEOUT)
    AUTH_SESSION_DAYS = max(1, min(365, get_int_from(settings, "auth_session_days", AUTH_SESSION_DAYS)))
    AUTH_SESSION_SECONDS = AUTH_SESSION_DAYS * 86400
    RUN_LOG_LIMIT = max(20, min(1000, get_int_from(settings, "run_log_limit", RUN_LOG_LIMIT)))
    APP_TIMEZONE = normalize_timezone(settings.get("timezone", APP_TIMEZONE))
    new_password = str(settings.get("auth_password") or "").strip()
    password_changed = False
    if new_password and "AUTH_PASSWORD" not in os.environ and new_password != AUTH_PASSWORD:
        AUTH_PASSWORD = new_password
        if "AUTH_SESSION_SECRET" not in os.environ:
            AUTH_SESSION_SECRET = AUTH_PASSWORD
        password_changed = True
    check_engine = ProxyCheckEngine(
        CheckConfig(
            timeout=TIMEOUT,
            detect_timeout=DETECT_TIMEOUT,
            check_rounds=CHECK_ROUNDS,
        )
    )
    return password_changed


def get_int_from(data, key, default):
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError, AttributeError):
        return default


def save_runtime_settings(settings):
    local_config = read_local_config()
    password_changed = apply_runtime_settings(settings)
    local_config.update({
        "check_rounds": CHECK_ROUNDS,
        "max_check_rounds": MAX_CHECK_ROUNDS,
        "max_concurrent": MAX_CONCURRENT,
        "max_concurrent_limit": MAX_CONCURRENT_LIMIT,
        "timeout": TIMEOUT,
        "detect_timeout": DETECT_TIMEOUT,
        "auth_session_days": AUTH_SESSION_DAYS,
        "run_log_limit": RUN_LOG_LIMIT,
        "timezone": APP_TIMEZONE,
    })
    if password_changed:
        local_config["auth_password"] = AUTH_PASSWORD
    write_local_config(local_config)
    return password_changed

# ============================================================
# Session cleanup
# ============================================================
def cleanup_sessions():
    while True:
        time.sleep(120)
        now = time.time()
        with sessions_lock:
            to_del = [k for k, v in sessions.items()
                      if v.get("finished") and now - v.get("created", now) > 600]
            for k in to_del:
                del sessions[k]
            if to_del:
                log.info(f"Cleaned up {len(to_del)} stale sessions, {len(sessions)} remaining")

threading.Thread(target=cleanup_sessions, daemon=True).start()

# ============================================================
# Auto Mode Scheduler
# ============================================================
def list_auto_tokens():
    tokens = []
    if not os.path.isdir(AUTO_DIR):
        return tokens
    for name in os.listdir(AUTO_DIR):
        if name.endswith(".json"):
            tokens.append(sanitize_token(name[:-5]))
    return tokens


def load_auto_record(token):
    token = sanitize_token(token)
    data = read_json_file(auto_json_path(token), {})
    config = normalize_auto_config(data.get("config") if isinstance(data, dict) else {})
    state = default_auto_state(config)
    if isinstance(data, dict) and isinstance(data.get("state"), dict):
        state.update(data["state"])
    history = state.get("history")
    state["history"] = history[-20:] if isinstance(history, list) else []
    if not config.get("enabled"):
        state["status"] = "disabled"
        state["next_run_at"] = None
    elif state.get("next_run_at") is None and not state.get("running"):
        state["next_run_at"] = compute_next_run(config)
    return {"config": config, "state": state}


def save_auto_record(token, record):
    token = sanitize_token(token)
    config = normalize_auto_config(record.get("config", {}))
    state = record.get("state") if isinstance(record.get("state"), dict) else default_auto_state(config)
    history = state.get("history")
    state["history"] = history[-20:] if isinstance(history, list) else []
    atomic_write_json(auto_json_path(token), {"config": config, "state": state})
    return {"config": config, "state": state}


def append_auto_history(state, summary):
    history = state.get("history")
    if not isinstance(history, list):
        history = []
    history.append(summary)
    state["history"] = history[-20:]
    state["last_summary"] = summary


def runtime_counts(results):
    valid = sum(1 for r in results if r.get("valid"))
    unstable = sum(1 for r in results if r.get("unstable"))
    invalid = sum(1 for r in results if not r.get("valid") and not r.get("unstable"))
    return valid, unstable, invalid


def get_auto_status(token, since=0, client_session_id=""):
    token = sanitize_token(token)
    with auto_lock:
        record = load_auto_record(token)
        config = normalize_auto_config(record.get("config", {}))
        runtime = auto_runtime.get(token)
        new_results = []
        results_index = 0
        if runtime:
            results = runtime.get("results", [])
            try:
                since = int(since)
            except (TypeError, ValueError):
                since = 0
            if client_session_id and client_session_id != runtime.get("run_id"):
                since = 0
            since = max(0, min(len(results), since))
            new_results = results[since:]
            results_index = len(results)
            valid, unstable, invalid = runtime_counts(results)
            record["state"].update({
                "running": True,
                "status": runtime.get("status", "running"),
                "session_id": runtime.get("run_id"),
                "stage": runtime.get("stage", "running"),
                "started_at": runtime.get("started_at"),
                "total": runtime.get("total", 0),
                "done": runtime.get("done", 0),
                "valid_count": valid,
                "unstable_count": unstable,
                "invalid_count": invalid,
                "source_count": runtime.get("source_count", 0),
                "repo_count": runtime.get("repo_count", 0),
                "input_count": runtime.get("input_count", 0),
                "skipped": runtime.get("skipped", 0),
                "error": runtime.get("error"),
            })
        else:
            stopped = auto_stopped_results.get(token)
            if stopped and stopped.get("expires", 0) < time.time():
                del auto_stopped_results[token]
                stopped = None
            if stopped:
                results = stopped.get("results", [])
                try:
                    since = int(since)
                except (TypeError, ValueError):
                    since = 0
                if client_session_id and client_session_id != stopped.get("run_id"):
                    since = 0
                since = max(0, min(len(results), since))
                new_results = results[since:]
                results_index = len(results)
        state = record["state"]
        state["next_run_text"] = format_timestamp(state.get("next_run_at"), config.get("timezone"))
        state["started_text"] = format_timestamp(state.get("started_at"), config.get("timezone"))
        state["finished_text"] = format_timestamp(state.get("finished_at"), config.get("timezone"))
        record["config"] = config
        record["server_time"] = server_time_payload(config.get("timezone"))
        record["auto_mode"] = True
        record["new"] = new_results
        record["results_index"] = results_index
        return record


def is_auto_running(token):
    token = sanitize_token(token)
    with auto_lock:
        runtime = auto_runtime.get(token)
        return bool(runtime and not runtime.get("finished"))


def update_auto_runtime(token, **fields):
    token = sanitize_token(token)
    with auto_lock:
        runtime = auto_runtime.get(token)
        if runtime:
            runtime.update(fields)
        record = load_auto_record(token)
        state = record["state"]
        if "stage" in fields:
            state["stage"] = fields["stage"]
        if "status" in fields:
            state["status"] = fields["status"]
        for key in ("total", "done", "source_count", "repo_count", "input_count", "skipped", "error"):
            if key in fields:
                state[key] = fields[key]
        save_auto_record(token, record)


def result_repo_key(result):
    return proxy_key(result.get("original") or result.get("proxy"))


def result_to_repo_item(result, existing=None):
    now = int(time.time() * 1000)
    existing = existing or {}
    country = result.get("country")
    checks_detail = result.get("checks_detail")
    if not country and isinstance(checks_detail, dict):
        ip_info = checks_detail.get("ip_info")
        if isinstance(ip_info, dict):
            country = ip_info.get("country")
    item = {
        "proxy": result.get("proxy") or result.get("original"),
        "grade": result.get("grade") or "F",
        "latency": result.get("latency"),
        "ip": result.get("ip"),
        "country": str(country).upper() if country else None,
        "ip_type": result.get("ip_type"),
        "service_reachable": result.get("service_reachable") is True,
        "api_reachable": result.get("api_reachable") is True,
        "cf_bypass": result.get("cf_bypass") is True,
        "recommended_use": result.get("recommended_use"),
        "target_profile": result.get("target_profile"),
        "target_name": result.get("target_name"),
        "added": existing.get("added") or now,
        "updated": now,
    }
    return compact_repo_item(item)


def result_matches_policy(result, policy):
    grade = str(result.get("grade") or "F")
    if policy == "archive_all":
        return True
    if policy == "include_unstable":
        return grade in ("A", "B", "C", "D") or result.get("valid") or result.get("unstable")
    return grade in ("A", "B", "C") or result.get("valid")


def merge_repo_results(token, repo, results, checked_inputs, policy):
    policy = policy if policy in ("stable_only", "include_unstable", "archive_all") else "stable_only"
    participating = {proxy_key(proxy) for proxy in checked_inputs}
    result_by_key = {}
    for result in results:
        for value in (result.get("original"), result.get("proxy")):
            key = proxy_key(value)
            if key:
                result_by_key[key] = result

    existing_by_key = {}
    for item in compact_repo(repo):
        existing_by_key[proxy_key(item["proxy"])] = item

    removed = 0
    next_repo = []
    used_old_keys = set()
    for item in compact_repo(repo):
        key = proxy_key(item["proxy"])
        result = result_by_key.get(key)
        if policy != "archive_all" and key in participating and result and not result_matches_policy(result, policy):
            removed += 1
            used_old_keys.add(key)
            continue
        next_repo.append(item)

    index_by_key = {proxy_key(item["proxy"]): i for i, item in enumerate(next_repo)}
    added = 0
    updated = 0
    for result in results:
        if not result_matches_policy(result, policy):
            continue
        candidate_keys = [proxy_key(result.get("original")), proxy_key(result.get("proxy"))]
        existing = None
        existing_index = None
        for key in candidate_keys:
            if key in index_by_key:
                existing_index = index_by_key[key]
                existing = next_repo[existing_index]
                break
            if key in existing_by_key:
                existing = existing_by_key[key]
        item = result_to_repo_item(result, existing)
        if not item:
            continue
        if existing_index is None:
            next_repo.append(item)
            index_by_key[proxy_key(item["proxy"])] = len(next_repo) - 1
            added += 1
        else:
            next_repo[existing_index] = item
            index_by_key[proxy_key(item["proxy"])] = existing_index
            updated += 1

    saved = write_repo_data(token, next_repo)
    return {
        "repo_count": len(saved),
        "repo_added": added,
        "repo_updated": updated,
        "repo_removed": removed,
    }


def build_auto_summary(runtime, status, error=None, repo_summary=None):
    results = runtime.get("results", [])
    valid, unstable, invalid = runtime_counts(results)
    started_at = runtime.get("started_at") or time.time()
    finished_at = time.time()
    summary = {
        "status": status,
        "reason": runtime.get("reason", "schedule"),
        "started_at": int(started_at),
        "finished_at": int(finished_at),
        "duration_seconds": max(0, int(finished_at - started_at)),
        "target_profile": runtime.get("target_profile", "generic"),
        "rounds": runtime.get("rounds", CHECK_ROUNDS),
        "max_concurrent": runtime.get("max_concurrent", MAX_CONCURRENT),
        "detect_mode": runtime.get("detect_mode", "skip"),
        "repo_update_policy": runtime.get("repo_update_policy", "stable_only"),
        "schedule_type": runtime.get("schedule_type"),
        "interval_hours": runtime.get("interval_hours"),
        "daily_time": runtime.get("daily_time"),
        "timezone": runtime.get("timezone", APP_TIMEZONE),
        "source_count": runtime.get("source_count", 0),
        "repo_input_count": runtime.get("repo_count", 0),
        "input_count": runtime.get("input_count", 0),
        "skipped": runtime.get("skipped", 0),
        "total": runtime.get("total", 0),
        "done": runtime.get("done", 0),
        "valid_count": valid,
        "unstable_count": unstable,
        "invalid_count": invalid,
    }
    if error:
        summary["error"] = str(error)[:300]
    if repo_summary:
        summary.update(repo_summary)
    return summary


def finalize_auto_run(token, runtime, status, error=None, repo_summary=None):
    token = sanitize_token(token)
    summary = build_auto_summary(runtime, status, error, repo_summary)
    with auto_lock:
        record = load_auto_record(token)
        config = normalize_auto_config(record.get("config", {}))
        state = record["state"]
        state.update({
            "running": False,
            "status": status,
            "session_id": None,
            "stage": status,
            "finished_at": summary["finished_at"],
            "last_run_at": summary["finished_at"],
            "next_run_at": compute_next_run(config) if config.get("enabled") else None,
            "error": summary.get("error"),
        })
        append_auto_history(state, summary)
        save_auto_record(token, {"config": config, "state": state})
        if status == "stopped":
            auto_stopped_results[token] = {
                "run_id": runtime.get("run_id"),
                "results": list(runtime.get("results", [])),
                "expires": time.time() + 900,
            }
        else:
            auto_stopped_results.pop(token, None)
        stored = auto_runtime.get(token)
        if stored and stored.get("run_id") == runtime.get("run_id"):
            stored["finished"] = True
            del auto_runtime[token]
    finish_run_log(token, runtime.get("log_id") or runtime.get("run_id"), {
        **summary,
        "type": "auto",
        "status": status,
        "session_id": runtime.get("run_id"),
        "target_name": get_target_profile_name(summary.get("target_profile")),
    })
    log.info("Auto run finished", extra={"token": token, "status": status, "summary": summary})


def execute_auto_run(token, config, run_id, reason):
    token = sanitize_token(token)
    runtime = None
    try:
        with auto_lock:
            runtime = auto_runtime[token]
        update_auto_runtime(token, stage="fetching", status="running")
        if not FETCH_PROXIES_AVAILABLE:
            raise RuntimeError("fetch_proxies 模块不可用")
        fetched, _source_name, err = fetch_proxies("all", 50000)
        if err:
            raise RuntimeError(err)
        source_proxies = normalize_proxy_list(fetched)

        update_auto_runtime(token, stage="loading_repo", source_count=len(source_proxies))
        repo = read_repo_data(token)
        repo_proxies = normalize_proxy_list(item.get("proxy") for item in repo)
        combined = normalize_proxy_list(source_proxies + repo_proxies)

        checked = read_checked_list(token)
        checked_keys = {proxy_key(proxy) for proxy in checked}
        if config["detect_mode"] == "skip":
            to_check = [proxy for proxy in combined if proxy_key(proxy) not in checked_keys]
        else:
            to_check = combined
        skipped = len(combined) - len(to_check)
        with auto_lock:
            runtime.update({
                "target_profile": config["target_profile"],
                "rounds": config["rounds"],
                "max_concurrent": config["max_concurrent"],
                "detect_mode": config["detect_mode"],
                "repo_update_policy": config["repo_update_policy"],
                "repo_count": len(repo),
                "input_count": len(combined),
                "total": len(to_check),
                "skipped": skipped,
            })
        update_auto_runtime(token, stage="detecting", repo_count=len(repo), total=len(to_check), skipped=skipped)

        if to_check:
            async def run_async():
                await check_engine.check_many_async(
                    proxies=to_check,
                    stop_event=runtime["stop"],
                    rounds=config["rounds"],
                    max_concurrent=config["max_concurrent"],
                    on_result=lambda result: publish_auto_result(token, result),
                    target_profile=config["target_profile"],
                )

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(run_async())
            finally:
                loop.close()

        if runtime["stop"].is_set():
            finalize_auto_run(token, runtime, "stopped")
            return

        update_auto_runtime(token, stage="updating_repo")
        detected = [result.get("original") or result.get("proxy") for result in runtime.get("results", [])]
        append_checked_list(token, detected)
        repo_summary = merge_repo_results(
            token=token,
            repo=repo,
            results=runtime.get("results", []),
            checked_inputs=to_check,
            policy=config["repo_update_policy"],
        )
        finalize_auto_run(token, runtime, "completed", repo_summary=repo_summary)
    except Exception as exc:
        if runtime is None:
            runtime = {
                "run_id": run_id,
                "reason": reason,
                "started_at": time.time(),
                "results": [],
                "done": 0,
                "total": 0,
                "target_profile": config.get("target_profile", "generic"),
                "rounds": config.get("rounds", CHECK_ROUNDS),
                "max_concurrent": config.get("max_concurrent", MAX_CONCURRENT),
                "detect_mode": config.get("detect_mode", "skip"),
                "repo_update_policy": config.get("repo_update_policy", "stable_only"),
            }
        log.error("Auto run failed", extra={"token": token, "error": str(exc)}, exc_info=True)
        finalize_auto_run(token, runtime, "failed", error=exc)


def publish_auto_result(token, result):
    if not result:
        return
    token = sanitize_token(token)
    with auto_lock:
        runtime = auto_runtime.get(token)
        if not runtime:
            return
        runtime["results"].append(result)
        runtime["done"] = runtime.get("done", 0) + 1


def start_auto_run(token, reason="schedule"):
    token = sanitize_token(token)
    with auto_lock:
        if token in auto_runtime:
            return False, "自动任务正在执行"
        record = load_auto_record(token)
        config = normalize_auto_config(record.get("config", {}))
        if reason == "schedule" and not config.get("enabled"):
            return False, "自动模式未启用"
        run_id = f"auto_{int(time.time())}_{id(config)}"
        started_at = time.time()
        log_id = start_run_log(token, {
            "id": run_id,
            "type": "auto",
            "status": "running",
            "session_id": run_id,
            "reason": reason,
            "started_at": int(started_at),
            "target_profile": config["target_profile"],
            "target_name": get_target_profile_name(config["target_profile"]),
            "rounds": config["rounds"],
            "max_concurrent": config["max_concurrent"],
            "detect_mode": config["detect_mode"],
            "repo_update_policy": config["repo_update_policy"],
            "schedule_type": config["schedule_type"],
            "interval_hours": config["interval_hours"],
            "daily_time": config["daily_time"],
            "timezone": config["timezone"],
        })
        runtime = {
            "run_id": run_id,
            "log_id": log_id,
            "reason": reason,
            "stop": threading.Event(),
            "status": "running",
            "stage": "starting",
            "started_at": started_at,
            "results": [],
            "done": 0,
            "total": 0,
            "finished": False,
            "target_profile": config["target_profile"],
            "rounds": config["rounds"],
            "max_concurrent": config["max_concurrent"],
            "detect_mode": config["detect_mode"],
            "repo_update_policy": config["repo_update_policy"],
            "schedule_type": config["schedule_type"],
            "interval_hours": config["interval_hours"],
            "daily_time": config["daily_time"],
            "timezone": config["timezone"],
        }
        auto_runtime[token] = runtime
        state = record["state"]
        state.update({
            "running": True,
            "status": "running",
            "session_id": run_id,
            "stage": "starting",
            "started_at": int(runtime["started_at"]),
            "finished_at": None,
            "next_run_at": compute_next_run(config, runtime["started_at"]) if config.get("enabled") else None,
            "error": None,
        })
        save_auto_record(token, {"config": config, "state": state})

    thread = threading.Thread(target=execute_auto_run, args=(token, config, run_id, reason), daemon=True)
    with auto_lock:
        if token in auto_runtime:
            auto_runtime[token]["thread"] = thread
    thread.start()
    return True, run_id


def stop_auto_run(token):
    token = sanitize_token(token)
    with auto_lock:
        runtime = auto_runtime.get(token)
        if not runtime:
            return False
        runtime["status"] = "stopping"
        runtime["stage"] = "stopping"
        runtime["stop"].set()
        record = load_auto_record(token)
        record["state"]["status"] = "stopping"
        record["state"]["stage"] = "stopping"
        save_auto_record(token, record)
    return True


def save_auto_config(token, config):
    token = sanitize_token(token)
    with auto_lock:
        record = load_auto_record(token)
        normalized = normalize_auto_config(config)
        state = record["state"]
        if normalized.get("enabled"):
            state["status"] = "running" if token in auto_runtime else "idle"
            if token not in auto_runtime:
                state["next_run_at"] = compute_next_run(normalized)
        else:
            state["status"] = "disabled"
            state["next_run_at"] = None
        state["running"] = token in auto_runtime
        state["stage"] = "running" if token in auto_runtime else state["status"]
        return save_auto_record(token, {"config": normalized, "state": state})


def mark_interrupted_auto_runs():
    now = int(time.time())
    for token in list_auto_tokens():
        with auto_lock:
            record = load_auto_record(token)
            config = normalize_auto_config(record.get("config", {}))
            state = record["state"]
            if not state.get("running"):
                continue
            summary = {
                "status": "interrupted",
                "reason": "service_restart",
                "started_at": state.get("started_at"),
                "finished_at": now,
                "duration_seconds": 0,
                "target_profile": config.get("target_profile", "generic"),
                "rounds": config.get("rounds", CHECK_ROUNDS),
                "max_concurrent": config.get("max_concurrent", MAX_CONCURRENT),
                "detect_mode": config.get("detect_mode", "skip"),
                "repo_update_policy": config.get("repo_update_policy", "stable_only"),
                "error": "服务重启，上一轮自动任务已中断",
            }
            state.update({
                "running": False,
                "status": "interrupted",
                "stage": "interrupted",
                "session_id": None,
                "finished_at": now,
                "next_run_at": now if config.get("enabled") else None,
                "error": summary["error"],
            })
            append_auto_history(state, summary)
            save_auto_record(token, {"config": config, "state": state})


def scheduler_loop():
    while True:
        due_tokens = []
        now = time.time()
        for token in list_auto_tokens():
            with auto_lock:
                record = load_auto_record(token)
                config = normalize_auto_config(record.get("config", {}))
                state = record["state"]
                if not config.get("enabled") or token in auto_runtime:
                    continue
                next_run_at = state.get("next_run_at")
                if next_run_at is None:
                    state["next_run_at"] = compute_next_run(config, now)
                    save_auto_record(token, {"config": config, "state": state})
                    continue
                try:
                    due = float(next_run_at) <= now
                except (TypeError, ValueError):
                    due = True
                if due:
                    due_tokens.append(token)
        for token in due_tokens:
            started, message = start_auto_run(token, "schedule")
            if started:
                log.info("Scheduled auto run started", extra={"token": token})
            else:
                log.warning("Scheduled auto run skipped", extra={"token": token, "message": message})
        time.sleep(30)


def start_auto_scheduler():
    mark_interrupted_auto_runs()
    threading.Thread(target=scheduler_loop, daemon=True).start()

# ============================================================
# Deep Check (optional, requires nodriver + Chrome)
# ============================================================
async def deep_check_nodriver(proxy_str, target_url, timeout=20):
    """
    Use nodriver (real browser) to verify proxy can bypass CF.
    Returns: (success, details)
    """
    if not NODRIVER_AVAILABLE:
        return False, {"error": "nodriver not installed"}

    browser = None
    try:
        # Configure nodriver with proxy
        config = nodriver.Config()
        config.add_argument(f"--proxy-server={proxy_str}")
        config.add_argument("--no-sandbox")
        config.add_argument("--disable-dev-shm-usage")
        config.headless = True

        browser = await nodriver.start(config=config)
        page = await browser.get(target_url)

        # Wait for page to load
        await asyncio.sleep(5)

        # Check page content
        title = await page.evaluate("document.title")
        body_text = await page.evaluate("document.body.innerText.substring(0, 2000)")

        # Check for CF challenge
        cf_detected = False
        cf_type = None
        for indicator in ["Just a moment", "Checking your browser", "Verify you are human", "challenge-platform"]:
            if indicator.lower() in body_text.lower():
                cf_detected = True
                if "turnstile" in body_text.lower():
                    cf_type = "turnstile"
                elif "just a moment" in body_text.lower():
                    cf_type = "js"
                else:
                    cf_type = "managed"
                break

        has_content = any(kw in body_text.lower() for kw in ["chatgpt", "chat.openai.com", "log in", "sign up"])

        return True, {
            "title": title,
            "body_preview": body_text[:500],
            "cf_detected": cf_detected,
            "cf_type": cf_type,
            "has_real_content": has_content,
            "success": has_content and not cf_detected,
        }

    except Exception as e:
        return False, {"error": str(e)[:200]}
    finally:
        if browser:
            try:
                await browser.stop()
            except Exception:
                pass

def run_deep_check(proxy_str, target_url=None):
    """Synchronous wrapper for deep check."""
    if not NODRIVER_AVAILABLE:
        return {"error": "nodriver not installed", "success": False}

    target = target_url or TARGET_CHAT
    loop = asyncio.new_event_loop()
    try:
        ok, details = loop.run_until_complete(
            deep_check_nodriver(proxy_str, target, timeout=20)
        )
        return {"success": ok, **details}
    finally:
        loop.close()

# ============================================================
# Main Check Runner
# ============================================================
def run_check(session_id, proxies, rounds=None, target_profile=None, max_concurrent=None, token="default"):
    if rounds is None:
        rounds = CHECK_ROUNDS
    rounds = normalize_rounds(rounds)
    target_profile = normalize_target_profile(target_profile)
    max_concurrent = normalize_max_concurrent(max_concurrent)
    token = sanitize_token(token)
    with sessions_lock:
        sessions[session_id]["stop"] = threading.Event()
    stop_event = sessions[session_id]["stop"]

    def publish_result(result):
        if result:
            with sessions_lock:
                s = sessions.get(session_id)
                if s:
                    s["results"].append(result)
                    s["done"] += 1

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
    finally:
        loop.close()

    with sessions_lock:
        s = sessions.get(session_id)
        if s:
            s["finished"] = True
            results = list(s.get("results", []))
            valid, unstable, invalid = runtime_counts(results)
            status = "stopped" if stop_event.is_set() else "completed"
            finish_run_log(token, s.get("log_id") or session_id, {
                "type": "manual",
                "status": status,
                "session_id": session_id,
                "finished_at": int(time.time()),
                "target_profile": target_profile,
                "target_name": get_target_profile_name(target_profile),
                "rounds": rounds,
                "max_concurrent": max_concurrent,
                "total": s.get("total", len(proxies)),
                "done": s.get("done", len(results)),
                "valid_count": valid,
                "unstable_count": unstable,
                "invalid_count": invalid,
            })

# ============================================================
# HTTP Server
# ============================================================
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc_type, exc, _ = sys.exc_info()
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, TimeoutError)):
            log.warning("Client disconnected early", extra={"client_address": client_address})
            return
        super().handle_error(request, client_address)

from http.server import SimpleHTTPRequestHandler

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]

        # Serve repo as txt: /api/repo/<token>.txt
        # Serve repo as JSON: /api/repo/<token>.json
        if path.startswith("/api/repo/") and path.endswith(".json"):
            token = path.split("/")[-1].replace(".json", "")
            json_file = os.path.join(REPO_DIR, f"{token}.json")
            if os.path.isfile(json_file):
                with open(json_file, "r") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"[]")
            return

        # Serve repo as txt: /api/repo/<token>.txt
        if path.startswith("/api/repo/") and path.endswith(".txt"):
            token = path.split("/")[-1].replace(".txt", "")
            repo_file = os.path.join(REPO_DIR, f"{token}.txt")
            if os.path.isfile(repo_file):
                with open(repo_file, "r") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Repository not found")
            return
        # Serve checked proxies as txt: /api/checked/<token>.txt
        if path.startswith("/api/checked/") and path.endswith(".txt"):
            token = path.split("/")[-1].replace(".txt", "")
            checked_file = os.path.join(CHECKED_DIR, f"{token}.txt")
            if os.path.isfile(checked_file):
                with open(checked_file, "r") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b"")
            return

        if path == "/login.html":
            self._send_static_file("login.html")
            return

        if path in ("/", "/index.html") and is_auth_enabled() and not is_request_authenticated(self.headers):
            self._send_static_file("login.html")
            return

        if path == "/app.js" and is_auth_enabled() and not is_request_authenticated(self.headers):
            self._json(401, {"error": "请先输入登录密码", "auth_required": True})
            return

        static_files = {
            "/": "index.html",
            "/index.html": "index.html",
            "/app.js": "app.js",
        }
        file_name = static_files.get(path)
        if file_name is None:
            self.send_response(404); self.end_headers(); return
        self._send_static_file(file_name)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            if self.path == "/api/auth/status":
                self._json(200, {
                    "authenticated": is_request_authenticated(self.headers),
                    "auth_required": is_auth_enabled(),
                })

            elif self.path == "/api/auth/login":
                password = str(body.get("password", ""))
                if not hmac.compare_digest(password, AUTH_PASSWORD):
                    self._json(401, {"error": "密码不正确", "auth_required": True})
                    return
                token = make_auth_token()
                self._json(200, {
                    "ok": True,
                    "token": token,
                    "expires_in": AUTH_SESSION_SECONDS,
                    "auth_required": is_auth_enabled(),
                }, [("Set-Cookie", make_auth_cookie(token))])

            elif self.path == "/api/auth/logout":
                self._json(200, {"ok": True}, [("Set-Cookie", make_auth_cookie("", 0))])

            elif self.path == "/api/capabilities":
                # Return server capabilities
                self._json(200, {
                    "nodriver": NODRIVER_AVAILABLE,
                    "xvfb": XVFB_AVAILABLE,
                    "deep_check": NODRIVER_AVAILABLE,
                    "fetch_proxies": FETCH_PROXIES_AVAILABLE,
                    "target_profiles": list(TARGET_PROFILE_OPTIONS),
                    "max_concurrent": MAX_CONCURRENT,
                    "max_concurrent_limit": MAX_CONCURRENT_LIMIT,
                    "auth_required": is_auth_enabled(),
                    "authenticated": is_request_authenticated(self.headers),
                    "auto_mode": True,
                    "auto_mode_hint": "后台自动模式仅在自托管 Python 服务中可用",
                    "settings": public_settings_payload(),
                    "proxy_sources": [{"id": s["id"], "name": s["name"]} for s in (PROXY_SOURCES if FETCH_PROXIES_AVAILABLE else [])],
                })

            elif not is_request_authenticated(self.headers):
                self._json(401, {"error": "请先输入登录密码", "auth_required": True})

            elif self.path == "/api/settings/get":
                self._json(200, {"settings": public_settings_payload(), "server_time": server_time_payload(APP_TIMEZONE)})

            elif self.path == "/api/settings/save":
                settings = body.get("settings", {})
                password_changed = save_runtime_settings(settings)
                response = {"ok": True, "settings": public_settings_payload(), "password_changed": password_changed}
                if password_changed:
                    token = make_auth_token()
                    response["token"] = token
                    response["expires_in"] = AUTH_SESSION_SECONDS
                    self._json(200, response, [("Set-Cookie", make_auth_cookie(token))])
                else:
                    self._json(200, response)

            elif self.path == "/api/logs/list":
                token = sanitize_token(body.get("token", "default"))
                self._json(200, run_logs_payload(token))

            elif self.path == "/api/logs/clear":
                token = sanitize_token(body.get("token", "default"))
                clear_run_logs(token)
                self._json(200, {"ok": True, **run_logs_payload(token)})

            elif self.path == "/api/start":
                proxies = body.get("proxies", [])
                rounds = normalize_rounds(body.get("rounds", CHECK_ROUNDS))
                target_profile = normalize_target_profile(body.get("target_profile", "generic"))
                max_concurrent = normalize_max_concurrent(body.get("max_concurrent", MAX_CONCURRENT))
                token = sanitize_token(body.get("token", ""))
                if body.get("token") and is_auto_running(token):
                    self._json(200, {"error": "自动任务正在执行，请先停止自动任务", "auto_running": True})
                    return
                sid = str(time.time()) + str(id(proxies))
                log_id = start_run_log(token, {
                    "id": sid,
                    "type": "manual",
                    "status": "running",
                    "session_id": sid,
                    "started_at": int(time.time()),
                    "target_profile": target_profile,
                    "target_name": get_target_profile_name(target_profile),
                    "rounds": rounds,
                    "max_concurrent": max_concurrent,
                    "total": len(proxies),
                    "timezone": APP_TIMEZONE,
                })
                with sessions_lock:
                    sessions[sid] = {
                        "results": [], "done": 0, "finished": False,
                        "stop": None, "total": len(proxies), "created": time.time(),
                        "rounds": rounds, "target_profile": target_profile,
                        "max_concurrent": max_concurrent, "token": token,
                        "log_id": log_id,
                    }
                threading.Thread(target=run_check, args=(sid, proxies, rounds, target_profile, max_concurrent, token), daemon=True).start()
                log.info(f"Start check: session={sid}, proxies={len(proxies)}, rounds={rounds}, target_profile={target_profile}, max_concurrent={max_concurrent}")
                self._json(200, {"session_id": sid, "total": len(proxies), "rounds": rounds, "target_profile": target_profile, "max_concurrent": max_concurrent})

            elif self.path == "/api/status":
                sid = body.get("session_id", "")
                since = body.get("since", 0)
                with sessions_lock:
                    s = sessions.get(sid)
                    if not s:
                        self._json(200, {"error": "not found"}); return
                    all_r = s["results"]
                    new_r = all_r[since:]
                    self._json(200, {
                        "new": new_r,
                        "total_done": s["done"],
                        "total": s["total"],
                        "finished": s["finished"],
                        "target_profile": s.get("target_profile", "generic"),
                        "max_concurrent": s.get("max_concurrent", MAX_CONCURRENT),
                        "valid_count": sum(1 for r in all_r if r.get("valid")),
                        "unstable_count": sum(1 for r in all_r if r.get("unstable")),
                        "invalid_count": sum(1 for r in all_r if not r.get("valid") and not r.get("unstable")),
                        "cf_bypass_count": sum(1 for r in all_r if r.get("cf_bypass")),
                    })

            elif self.path == "/api/auto/get":
                token = sanitize_token(body.get("token", "default"))
                self._json(200, get_auto_status(token, body.get("since", 0), body.get("session_id", "")))

            elif self.path == "/api/auto/save":
                token = sanitize_token(body.get("token", "default"))
                record = save_auto_config(token, body.get("config", {}))
                response = get_auto_status(token)
                response["saved"] = True
                response["config"] = record["config"]
                response["state"] = record["state"]
                self._json(200, response)

            elif self.path == "/api/auto/run-now":
                token = sanitize_token(body.get("token", "default"))
                started, message = start_auto_run(token, "manual")
                response = get_auto_status(token)
                response["started"] = started
                if not started:
                    response["error"] = message
                self._json(200, response)

            elif self.path == "/api/auto/stop":
                token = sanitize_token(body.get("token", "default"))
                stopped = stop_auto_run(token)
                response = get_auto_status(token, body.get("since", 0), body.get("session_id", ""))
                response["stopped"] = stopped
                self._json(200, response)

            elif self.path == "/api/auto/status":
                token = sanitize_token(body.get("token", "default"))
                self._json(200, get_auto_status(token, body.get("since", 0), body.get("session_id", "")))

            elif self.path == "/api/stop":
                sid = body.get("session_id", "")
                with sessions_lock:
                    s = sessions.get(sid)
                    if s and s.get("stop"):
                        s["stop"].set()
                self._json(200, {"ok": True})

            elif self.path == "/api/deep-check":
                # Optional deep check using nodriver
                proxy = body.get("proxy", "")
                if not proxy:
                    self._json(400, {"error": "proxy required"}); return
                if not NODRIVER_AVAILABLE:
                    self._json(200, {"success": False, "error": "nodriver not installed", "hint": "pip install nodriver"})
                    return
                target = body.get("target", TARGET_CHAT)
                result = run_deep_check(proxy, target)
                self._json(200, result)

            elif self.path == "/api/repo/save":
                # Accept full repo data (JSON array of objects) or legacy proxy list
                repo_data = body.get("repo", None)
                proxies = body.get("proxies", [])
                token = body.get("token", "default")
                if not token.replace("_","").isalnum():
                    token = "default"

                if repo_data is not None:
                    # Full JSON data — save as .json
                    json_file = os.path.join(REPO_DIR, f"{token}.json")
                    with open(json_file, "w") as f:
                        json.dump(repo_data, f, ensure_ascii=False)
                    # Also save txt for backwards compat
                    txt_file = os.path.join(REPO_DIR, f"{token}.txt")
                    proxy_list = [p.get("proxy","") if isinstance(p,dict) else str(p) for p in repo_data]
                    with open(txt_file, "w") as f:
                        f.write("\n".join(proxy_list))
                    log.info(f"Repo saved (JSON): token={token}, proxies={len(repo_data)}")
                    self._json(200, {"ok": True, "url": f"/api/repo/{token}.json", "count": len(repo_data)})
                else:
                    # Legacy txt-only
                    repo_file = os.path.join(REPO_DIR, f"{token}.txt")
                    with open(repo_file, "w") as f:
                        f.write("\n".join(proxies))
                    log.info(f"Repo saved (txt): token={token}, proxies={len(proxies)}")
                    self._json(200, {"ok": True, "url": f"/api/repo/{token}.txt", "count": len(proxies)})

            elif self.path == "/api/fetch-proxies":
                # Fetch proxies from external sources
                if not FETCH_PROXIES_AVAILABLE:
                    self._json(200, {"error": "fetch_proxies 模块不可用"})
                    return
                source_id = body.get("source", "proxifly")
                limit = min(int(body.get("limit", 999999)), 999999)
                proxies, source_name, err = fetch_proxies(source_id, limit)
                if err:
                    self._json(200, {"error": err, "source": source_name})
                else:
                    self._json(200, {
                        "proxies": proxies,
                        "count": len(proxies),
                        "source": source_name,
                        "source_id": source_id,
                    })

            elif self.path == "/api/checked/save":
                proxies = body.get("proxies", [])
                token = body.get("token", "default")
                if not token.replace("_","").isalnum():
                    token = "default"
                checked_file = os.path.join(CHECKED_DIR, f"{token}.txt")
                with open(checked_file, "w") as f:
                    f.write("\n".join(proxies))
                log.info(f"Checked proxies saved: token={token}, count={len(proxies)}")
                self._json(200, {"ok": True, "count": len(proxies)})

            elif self.path == "/api/checked/filter":
                # Given a list of proxies, return which ones are NOT yet checked
                proxies = body.get("proxies", [])
                token = body.get("token", "default")
                if not token.replace("_","").isalnum():
                    token = "default"
                checked_file = os.path.join(CHECKED_DIR, f"{token}.txt")
                checked_set = set()
                if os.path.isfile(checked_file):
                    with open(checked_file, "r") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                checked_set.add(line.lower())
                unchecked = [p for p in proxies if p.lower() not in checked_set]
                skipped = len(proxies) - len(unchecked)
                self._json(200, {
                    "unchecked": unchecked,
                    "skipped": skipped,
                    "total": len(proxies),
                    "checked_count": len(checked_set),
                })

            else:
                self.send_response(404); self.end_headers()

        except Exception as e:
            log.error(f"POST error: {e}")
            try:
                self._json(500, {"error": str(e)})
            except:
                pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Proxy-Auth")
        self.end_headers()

    def _json(self, code, data, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        for key, value in headers or []:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send_static_file(self, file_name):
        fp = os.path.join(BASE_DIR, file_name)
        ext = os.path.splitext(fp)[1]
        ct = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
              ".css": "text/css; charset=utf-8", ".json": "application/json"}.get(ext, "application/octet-stream")
        if os.path.isfile(fp):
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.end_headers()
            with open(fp, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    start_auto_scheduler()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info(f"Proxy Checker running at http://0.0.0.0:{PORT}")
    log.info(f"Deep check (nodriver): {'available' if NODRIVER_AVAILABLE else 'not installed'}")
    log.info(f"Concurrency: {MAX_CONCURRENT} | Rounds: {CHECK_ROUNDS}")
    log.info("Auto mode scheduler started")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopped.")
        server.server_close()
    except Exception as e:
        log.critical(f"Server crashed: {e}", exc_info=True)
