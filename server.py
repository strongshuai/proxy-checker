import json
import time
import os
import re
import threading
import asyncio
import logging
from http.server import HTTPServer
from socketserver import ThreadingMixIn
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as cffi_requests

# ============================================================
# My Repository — save/retrieve repo proxies as txt
# ============================================================
REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'repo_data')
os.makedirs(REPO_DIR, exist_ok=True)

# Checked proxies persistence — per-token checked history
CHECKED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'checked_data')
os.makedirs(CHECKED_DIR, exist_ok=True)

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

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/opt/vpntest/server.log', encoding='utf-8')
    ]
)
log = logging.getLogger('vpntest')

# ============================================================
# Configuration
# ============================================================
TIMEOUT = 12
DETECT_TIMEOUT = 8
MAX_CONCURRENT = 30
CHECK_ROUNDS = 2
PORT = int(os.environ.get("PORT", 8888))

# Check targets — multiple endpoints for comprehensive detection
TARGET_CHAT = "https://chat.openai.com/"
TARGET_SIGNUP = "https://auth0.openai.com/u/signup/authorize?client_id=DRivsnm2Mu42T3KOpqdtwB3NYviHYzwD&scope=openid%20email%20profile%20offline_access%20model.request%20model.read%20organization.read%20organization.write&response_type=code&redirect_uri=https%3A%2F%2Fchatgpt.com%2Fapi%2Fauth%2Fcallback%2Flogin-web&audience=https%3A%2F%2Fapi.openai.com%2Fv1&prompt=login&screen_hint=signup"
TARGET_API = "https://api.openai.com/v1/models"
# IP check endpoint
TARGET_IP = "https://httpbin.org/ip"
# Alternative IP check (more reliable)
TARGET_IP2 = "https://api.ipify.org?format=json"

# CF challenge indicators in response body
CF_BODY_INDICATORS = [
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
]

# CF challenge indicators in headers
CF_HEADER_INDICATORS = [
    "cf-ray",
    "cf-chl",
    "cf-cache-status",
]

# OpenAI-specific indicators
OPENAI_REAL_PAGE_INDICATORS = [
    "__next",
    "chat.openai.com",
    "ChatGPT",
    "prompt-textarea",
    "conversation-turn",
]

OPENAI_SIGNUP_INDICATORS = [
    "signup",
    "auth0",
    "Create your account",
    "email",
    "password",
    "Sign up",
]

executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT)
sessions = {}
sessions_lock = threading.Lock()

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
# CF Challenge Detection
# ============================================================
def detect_cf_challenge(resp):
    """
    Analyze response to detect Cloudflare challenge pages.
    Returns: (is_cf_challenge, cf_details)
    """
    details = {
        "cf_detected": False,
        "cf_challenge_type": None,  # "managed", "js", "turnstile", "block"
        "cf_indicators": [],
        "response_size": len(resp.text) if resp.text else 0,
        "has_real_content": False,
    }

    # Check headers
    headers_lower = {k.lower(): v for k, v in resp.headers.items()}
    for indicator in CF_HEADER_INDICATORS:
        if any(indicator in k for k in headers_lower):
            details["cf_detected"] = True
            details["cf_indicators"].append(f"header:{indicator}")

    # Check response body
    body = resp.text or ""
    body_lower = body.lower()

    for indicator in CF_BODY_INDICATORS:
        if indicator.lower() in body_lower:
            details["cf_detected"] = True
            details["cf_indicators"].append(f"body:{indicator}")

    # Classify CF challenge type
    if details["cf_detected"]:
        if "turnstile" in body_lower or "cf-turnstile" in body_lower:
            details["cf_challenge_type"] = "turnstile"
        elif "managed-challenge" in body_lower or "challenge-platform" in body_lower:
            details["cf_challenge_type"] = "managed"
        elif "just a moment" in body_lower or "checking your browser" in body_lower:
            details["cf_challenge_type"] = "js"
        elif resp.status_code == 403:
            details["cf_challenge_type"] = "block"
        else:
            details["cf_challenge_type"] = "unknown"

    # Check if page has real content (not just challenge)
    for indicator in OPENAI_REAL_PAGE_INDICATORS:
        if indicator.lower() in body_lower:
            details["has_real_content"] = True
            break

    # If CF detected but also has real content, it might be a soft challenge
    if details["cf_detected"] and details["has_real_content"]:
        details["cf_challenge_type"] = "soft_challenge"

    return details["cf_detected"], details

def detect_signup_access(resp):
    """Check if the signup page is accessible (not blocked by CF)."""
    body = (resp.text or "").lower()
    status = resp.status_code

    # Signup page should return 200 with auth0 content
    if status == 200:
        for indicator in OPENAI_SIGNUP_INDICATORS:
            if indicator.lower() in body:
                return True, "signup_accessible"
        # If 200 but no signup content, might be CF challenge
        if any(ind in body for ind in ["challenge-platform", "just a moment"]):
            return False, "cf_challenge_on_signup"
        return True, "signup_200"

    if status in (301, 302, 303, 307, 308):
        return True, f"signup_redirect_{status}"

    if status == 403:
        return False, "signup_blocked_403"

    if status == 407:
        return False, "proxy_auth_required"

    return False, f"signup_error_{status}"

def classify_ip_type(ip_info):
    """Classify IP as residential/datacenter/unknown based on common ranges."""
    if not ip_info:
        return "unknown"

    # Common datacenter IP ranges (simplified)
    ip = ip_info.get("ip", "")
    org = ip_info.get("org", "").lower()

    dc_keywords = ["amazon", "aws", "google", "cloudflare", "azure", "microsoft",
                   "digitalocean", "linode", "vultr", "hetzner", "ovh", "oracle",
                   "alibaba", "tencent", "datacenter", "hosting", "server", "cloud"]

    for kw in dc_keywords:
        if kw in org:
            return "datacenter"

    return "residential"

# ============================================================
# Core Check Functions
# ============================================================
def classify_error(err):
    e = err.lower()
    if "timeout" in e or "timed out" in e: return "连接超时"
    if "refused" in e: return "连接被拒绝"
    if "resolve" in e or "dns" in e: return "DNS解析失败"
    if "socks" in e: return "SOCKS握手失败"
    if "ssl" in e or "certificate" in e: return "SSL/TLS错误"
    if "auth" in e or "407" in e: return "代理需要认证"
    if "connection reset" in e: return "连接被重置"
    if "eof" in e: return "连接异常断开"
    return err[:100]

def do_check_once(proxy_str, stop_event=None, timeout=TIMEOUT):
    """Single check round — returns comprehensive result."""
    if stop_event and stop_event.is_set():
        return {"valid": False, "error": "已停止"}

    r = {
        "valid": False,
        "latency": None,
        "error": None,
        "status_code": None,
        "ip": None,
        "ip_type": None,
        "api_reachable": None,
        "cf_bypass": False,
        "cf_challenge": False,
        "cf_challenge_type": None,
        "cf_indicators": [],
        "registration_ready": False,
        "registration_detail": None,
        "checks_detail": {},
    }

    try:
        proxies = {"http": proxy_str, "https": proxy_str}
        impersonate = "chrome"

        # === Check 1: chat.openai.com (main page) ===
        try:
            t0 = time.time()
            resp = cffi_requests.get(
                TARGET_CHAT, proxies=proxies, timeout=timeout,
                impersonate=impersonate, allow_redirects=True
            )
            r["latency"] = round((time.time() - t0) * 1000)
            r["status_code"] = resp.status_code

            is_cf, cf_details = detect_cf_challenge(resp)

            r["checks_detail"]["chat"] = {
                "status": resp.status_code,
                "cf_detected": is_cf,
                "cf_type": cf_details.get("cf_challenge_type"),
                "has_content": cf_details.get("has_real_content", False),
                "size": cf_details.get("response_size", 0),
            }

            if resp.status_code in (200, 301, 302, 303, 307, 308):
                if is_cf and not cf_details.get("has_real_content"):
                    # CF challenge — proxy might not bypass CF
                    r["cf_challenge"] = True
                    r["cf_challenge_type"] = cf_details.get("cf_challenge_type")
                    r["cf_indicators"] = cf_details.get("cf_indicators", [])
                    r["valid"] = False  # CF blocked = not truly valid
                    r["error"] = f"CF拦截({cf_details.get('cf_challenge_type', 'unknown')})"
                elif is_cf and cf_details.get("has_real_content"):
                    # Soft challenge — page loaded but with some CF elements
                    r["cf_bypass"] = True
                    r["cf_challenge"] = True
                    r["cf_challenge_type"] = "soft_challenge"
                    r["valid"] = True
                else:
                    # No CF challenge — clean access
                    r["cf_bypass"] = True
                    r["valid"] = True
            else:
                r["valid"] = False
                r["error"] = f"HTTP {resp.status_code}"

        except Exception as e:
            r["error"] = classify_error(str(e))
            r["valid"] = False
            return r  # Can't even connect, no point checking further

        if not r["valid"] and not r.get("cf_bypass"):
            return r

        # === Check 2: API endpoint ===
        try:
            ar = cffi_requests.get(
                TARGET_API, proxies=proxies, timeout=timeout,
                impersonate=impersonate
            )
            r["api_reachable"] = ar.status_code in (200, 401)
            r["checks_detail"]["api"] = {
                "status": ar.status_code,
                "reachable": r["api_reachable"],
            }
        except Exception:
            r["api_reachable"] = False
            r["checks_detail"]["api"] = {"status": None, "reachable": False}

        # === Check 3: Registration page ===
        try:
            sr = cffi_requests.get(
                TARGET_SIGNUP, proxies=proxies, timeout=timeout,
                impersonate=impersonate, allow_redirects=True
            )
            reg_ok, reg_detail = detect_signup_access(sr)
            r["registration_ready"] = reg_ok
            r["registration_detail"] = reg_detail
            r["checks_detail"]["signup"] = {
                "status": sr.status_code,
                "accessible": reg_ok,
                "detail": reg_detail,
                "final_url": sr.url if hasattr(sr, 'url') else None,
            }
        except Exception as e:
            r["registration_ready"] = False
            r["registration_detail"] = f"signup_error: {classify_error(str(e))}"
            r["checks_detail"]["signup"] = {"status": None, "accessible": False, "detail": str(e)[:80]}

        # === Check 4: IP detection ===
        for ip_endpoint in [TARGET_IP, TARGET_IP2]:
            try:
                ir = cffi_requests.get(
                    ip_endpoint, proxies=proxies, timeout=6,
                    impersonate=impersonate
                )
                if ir.status_code == 200:
                    ip_data = ir.json()
                    r["ip"] = ip_data.get("origin") or ip_data.get("ip")
                    # Try to get IP info
                    if r["ip"]:
                        try:
                            info_resp = cffi_requests.get(
                                f"https://ipinfo.io/{r['ip']}/json",
                                timeout=5, impersonate=impersonate
                            )
                            if info_resp.status_code == 200:
                                ip_info = info_resp.json()
                                r["ip_type"] = classify_ip_type(ip_info)
                                r["checks_detail"]["ip_info"] = {
                                    "ip": r["ip"],
                                    "org": ip_info.get("org", ""),
                                    "country": ip_info.get("country", ""),
                                    "type": r["ip_type"],
                                }
                        except Exception:
                            r["ip_type"] = "unknown"
                    break
            except Exception:
                continue

    except Exception as e:
        r["error"] = classify_error(str(e))

    return r

def auto_detect(bare_addr, stop_event=None):
    for prefix in ["http://", "https://", "socks5://", "socks5h://"]:
        if stop_event and stop_event.is_set():
            return None, False
        r = do_check_once(prefix + bare_addr, stop_event, DETECT_TIMEOUT)
        if r["valid"] or (r.get("cf_bypass") and r.get("status_code")):
            return prefix + bare_addr, True
    return None, False

def check_proxy_full(proxy_input, stop_event=None, rounds=None):
    if rounds is None:
        rounds = CHECK_ROUNDS
    proxy_input = proxy_input.strip()
    if not proxy_input or proxy_input.startswith("#"):
        return None
    if stop_event and stop_event.is_set():
        return None
    original = proxy_input
    has_prefix = proxy_input.startswith(("http://", "https://", "socks4://", "socks5://", "socks5h://"))
    if not has_prefix:
        proxy_input, found = auto_detect(proxy_input, stop_event)
        if not found:
            return {
                "proxy": original, "original": original,
                "valid": False, "unstable": False,
                "checks_passed": 0, "checks_total": rounds,
                "error": "所有协议均不可用(HTTP/HTTPS/SOCKS4/SOCKS5)",
                "latency": None, "status_code": None,
                "ip": None, "ip_type": None, "api_reachable": None,
                "cf_bypass": False, "cf_challenge": False,
                "cf_challenge_type": None, "cf_indicators": [],
                "registration_ready": False, "registration_detail": None,
                "detected_protocol": None, "timestamp": time.time(),
                "checks_detail": {},
            }

    passed = 0
    lats = []
    last = None
    for _ in range(rounds):
        if stop_event and stop_event.is_set():
            break
        r = do_check_once(proxy_input, stop_event)
        last = r
        if r["valid"]:
            passed += 1
            if r.get("latency"):
                lats.append(r["latency"])

    avg = round(sum(lats) / len(lats)) if lats else (last.get("latency") if last else None)
    proto = proxy_input.split("://")[0] if "://" in proxy_input else None

    # Determine quality grade based on all checks
    chat_ok = passed == rounds
    api_ok = last.get("api_reachable") if last else False
    reg_ok = last.get("registration_ready") if last else False
    cf_ok = last.get("cf_bypass") if last else False

    if chat_ok and api_ok and reg_ok and cf_ok:
        grade = "A"  # All checks pass — best for registration
    elif chat_ok and api_ok and cf_ok:
        grade = "B"  # Chat + API + CF bypass, registration untested
    elif chat_ok and api_ok:
        grade = "C"  # Chat + API accessible, may hit CF on signup
    elif chat_ok:
        grade = "D"  # Chat only, API/CF uncertain
    else:
        grade = "F"  # Failed

    # "valid" = at least chat + API accessible (grade C or better)
    is_valid = chat_ok and api_ok
    is_unstable = (chat_ok or api_ok) and not is_valid and passed > 0

    return {
        "proxy": proxy_input,
        "original": original,
        "valid": is_valid,
        "unstable": is_unstable,
        "grade": grade,
        "checks_passed": passed,
        "checks_total": rounds,
        "error": last["error"] if last and not last["valid"] else None,
        "latency": avg,
        "status_code": last["status_code"] if last else None,
        "ip": last["ip"] if last else None,
        "ip_type": last["ip_type"] if last else None,
        "api_reachable": last["api_reachable"] if last else None,
        "cf_bypass": last["cf_bypass"] if last else False,
        "cf_challenge": last["cf_challenge"] if last else False,
        "cf_challenge_type": last["cf_challenge_type"] if last else None,
        "cf_indicators": last["cf_indicators"] if last else [],
        "registration_ready": last["registration_ready"] if last else False,
        "registration_detail": last["registration_detail"] if last else None,
        "detected_protocol": proto,
        "timestamp": time.time(),
        "checks_detail": last["checks_detail"] if last else {},
    }



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
def run_check(session_id, proxies, rounds=None):
    if rounds is None:
        rounds = CHECK_ROUNDS
    with sessions_lock:
        sessions[session_id]["stop"] = threading.Event()
    stop_event = sessions[session_id]["stop"]

    def check_one(proxy):
        if stop_event.is_set():
            return None
        r = check_proxy_full(proxy, stop_event=stop_event, rounds=rounds)
        if r:
            with sessions_lock:
                s = sessions.get(session_id)
                if s:
                    s["results"].append(r)
                    s["done"] += 1
        return r

    loop = asyncio.new_event_loop()
    try:
        tasks = [loop.run_in_executor(executor, check_one, p) for p in proxies]
        loop.run_until_complete(asyncio.gather(*tasks))
    finally:
        loop.close()

    with sessions_lock:
        s = sessions.get(session_id)
        if s:
            s["finished"] = True

# ============================================================
# HTTP Server
# ============================================================
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

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
        if path == "/": path = "/index.html"
        base_dir = os.path.dirname(os.path.abspath(__file__))
        fp = os.path.normpath(os.path.join(base_dir, path.lstrip("/")))
        if not fp.startswith(base_dir):
            self.send_response(403); self.end_headers(); return
        ext = os.path.splitext(fp)[1]
        ct = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
              ".css": "text/css; charset=utf-8", ".json": "application/json"}.get(ext, "application/octet-stream")
        if os.path.isfile(fp):
            self.send_response(200); self.send_header("Content-Type", ct); self.end_headers()
            with open(fp, "rb") as f: self.wfile.write(f.read())
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            if self.path == "/api/start":
                proxies = body.get("proxies", [])
                rounds = body.get("rounds", CHECK_ROUNDS)
                rounds = max(1, min(5, int(rounds)))  # clamp 1-5
                sid = str(time.time()) + str(id(proxies))
                with sessions_lock:
                    sessions[sid] = {
                        "results": [], "done": 0, "finished": False,
                        "stop": None, "total": len(proxies), "created": time.time(),
                        "rounds": rounds,
                    }
                threading.Thread(target=run_check, args=(sid, proxies, rounds), daemon=True).start()
                log.info(f"Start check: session={sid}, proxies={len(proxies)}, rounds={rounds}")
                self._json(200, {"session_id": sid, "total": len(proxies), "rounds": rounds})

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
                        "valid_count": sum(1 for r in all_r if r.get("valid")),
                        "unstable_count": sum(1 for r in all_r if r.get("unstable")),
                        "invalid_count": sum(1 for r in all_r if not r.get("valid") and not r.get("unstable")),
                        "cf_bypass_count": sum(1 for r in all_r if r.get("cf_bypass")),
                        "registration_count": sum(1 for r in all_r if r.get("registration_ready")),
                    })

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

            elif self.path == "/api/capabilities":
                # Return server capabilities
                self._json(200, {
                    "nodriver": NODRIVER_AVAILABLE,
                    "xvfb": XVFB_AVAILABLE,
                    "deep_check": NODRIVER_AVAILABLE,
                    "fetch_proxies": FETCH_PROXIES_AVAILABLE,
                    "proxy_sources": [{"id": s["id"], "name": s["name"]} for s in (PROXY_SOURCES if FETCH_PROXIES_AVAILABLE else [])],
                })

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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _json(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    log.info(f"Proxy Checker running at http://0.0.0.0:{PORT}")
    log.info(f"Deep check (nodriver): {'available' if NODRIVER_AVAILABLE else 'not installed'}")
    log.info(f"Concurrency: {MAX_CONCURRENT} | Rounds: {CHECK_ROUNDS}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopped.")
        server.server_close()
    except Exception as e:
        log.critical(f"Server crashed: {e}", exc_info=True)