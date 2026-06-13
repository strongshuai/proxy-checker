"""
Proxy source definitions and fetcher.
Each source has a name, fetch function, and parser.
"""
import json
import re
import subprocess
from curl_cffi import requests as cffi_requests

PROXY_SOURCES = [
    {
        "id": "proxifly",
        "name": "Proxifly Free Proxy List",
        "url": "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/all/data.json",
    },
    {
        "id": "proxynova",
        "name": "ProxyNova Proxy Server List",
        "url": "https://www.proxynova.com/proxy-server-list/",
    },
    {
        "id": "hidemn",
        "name": "hidemy.name Proxy List",
        "url": "https://hide.mn/en/proxy-list/",
    },
    {
        "id": "freeproxy",
        "name": "Free-Proxy-List.net Socks",
        "url": "https://free-proxy-list.net/zh-cn/socks-proxy.html",
    },
    {
        "id": "checkerproxy",
        "name": "CheckerProxy.net Archive",
        "url": "https://api.checkerproxy.net/v1/landing/archive",
    },
]


def _fetch_proxifly(url, limit):
    """Fetch from Proxifly (JSON via jsDelivr CDN)."""
    resp = cffi_requests.get(url, timeout=20, impersonate="chrome")
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        return [], "数据格式错误"
    proxies = []
    for item in data[:limit]:
        proxy_str = item.get("proxy", "")
        if proxy_str:
            proxies.append({
                "proxy": proxy_str,
                "protocol": item.get("protocol", ""),
                "ip": item.get("ip", ""),
                "port": item.get("port", ""),
                "country": item.get("geolocation", {}).get("country", ""),
                "city": item.get("geolocation", {}).get("city", ""),
            })
    return proxies, None


def _fetch_proxynova(url, limit):
    """Fetch from ProxyNova (HTML with JS-obfuscated IPs, decoded via Node.js)."""
    resp = cffi_requests.get(url, timeout=20, impersonate="chrome")
    resp.raise_for_status()
    html = resp.text

    rows = re.findall(r'<tr data-proxy-id="(\d+)">(.*?)</tr>', html, re.DOTALL)
    if not rows:
        return [], "未找到代理数据"

    node_inputs = []
    for rid, row in rows:
        script_match = re.search(r'<script>(document\.write\([^<]+)</script>', row)
        if not script_match:
            continue
        js = script_match.group(1)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        port_raw = tds[1].strip() if len(tds) > 1 else ""
        port_match = re.search(r"(\d{2,5})", port_raw)
        port = port_match.group(1) if port_match else ""
        country_match = re.search(r'flag-([a-z]{2})', row)
        country = country_match.group(1).upper() if country_match else ""
        node_inputs.append({"js": js, "port": port, "country": country, "id": rid})

    if not node_inputs:
        return [], "未找到可解析的代理脚本"

    node_script = """
const vm = require('vm');
const atob = (s) => Buffer.from(s, 'base64').toString('binary');
const inputs = %s;
const results = [];
for (const item of inputs) {
    try {
        let output = '';
        const sandbox = { document: { write: (s) => { output = s; } }, atob: atob };
        vm.createContext(sandbox);
        vm.runInContext(item.js, sandbox, { timeout: 3000 });
        results.push({ id: item.id, ip: output, port: item.port, country: item.country });
    } catch(e) {
        results.push({ id: item.id, ip: '', port: item.port, country: item.country });
    }
}
console.log(JSON.stringify(results));
""" % json.dumps(node_inputs)

    try:
        proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return [], f"Node.js 解析失败: {proc.stderr[:200]}"
        decoded = json.loads(proc.stdout)
    except Exception as e:
        return [], f"Node.js 执行异常: {str(e)[:200]}"

    proxies = []
    ip_re = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
    for item in decoded[:limit]:
        ip = item.get("ip", "")
        port = item.get("port", "")
        if ip and port and ip_re.match(ip):
            proxies.append({
                "proxy": f"http://{ip}:{port}",
                "protocol": "http",
                "ip": ip,
                "port": int(port),
                "country": item.get("country", ""),
                "city": "",
            })
    return proxies, None


def _fetch_hidemn(url, limit):
    """Fetch from hidemy.name (HTML table, 64 per page)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = cffi_requests.get(url, timeout=20, impersonate="chrome", headers=headers)
    resp.raise_for_status()
    html = resp.text

    rows = re.findall(
        r'<tr><td>(\d+\.\d+\.\d+\.\d+)</td><td>(\d+)</td>'
        r'.*?<span class=country>(.*?)</span>'
        r'.*?<td>\s*(HTTP|HTTPS|SOCKS4|SOCKS5)\s*</td>',
        html, re.DOTALL
    )
    if not rows:
        return [], "未找到代理数据"

    proxies = []
    for ip, port, country, ptype in rows[:limit]:
        proto = ptype.lower()
        proxies.append({
            "proxy": f"{proto}://{ip}:{port}",
            "protocol": proto,
            "ip": ip,
            "port": int(port),
            "country": country.strip(),
            "city": "",
        })
    return proxies, None


def _fetch_freeproxy(url, limit):
    """Fetch from free-proxy-list.net socks proxy page (HTML table)."""
    resp = cffi_requests.get(url, timeout=20, impersonate="chrome")
    resp.raise_for_status()
    html = resp.text

    rows = re.findall(
        r'<tr><td>(\d+\.\d+\.\d+\.\d+)</td><td>(\d+)</td>'
        r'<td>([A-Z]{2})</td><td class=.hm.>(.*?)</td>'
        r'<td>(Socks[45])</td>',
        html, re.DOTALL
    )
    if not rows:
        return [], "未找到代理数据"

    proxies = []
    for ip, port, cc, country, stype in rows[:limit]:
        proto = stype.lower()  # socks4 / socks5
        proxies.append({
            "proxy": f"{proto}://{ip}:{port}",
            "protocol": proto,
            "ip": ip,
            "port": int(port),
            "country": cc,
            "city": country.strip(),
        })
    return proxies, None


def _fetch_checkerproxy(url, limit):
    """Fetch from CheckerProxy.net archive (last 3 days, ip:port format)."""
    api_base = "https://api.checkerproxy.net"
    headers = {"User-Agent": "Mozilla/5.0"}

    # Step 1: Get archive list
    resp = cffi_requests.get(url, timeout=15, impersonate="chrome", headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success") or not data.get("data", {}).get("items"):
        return [], "未找到存档数据"

    items = data["data"]["items"][:3]  # last 3 days

    # Step 2: Fetch proxies for each date
    all_proxies = []
    for item in items:
        date = item["date"]
        try:
            r = cffi_requests.get(
                f"{api_base}/v1/landing/archive/{date}",
                timeout=15, impersonate="chrome", headers=headers
            )
            r.raise_for_status()
            d = r.json()
            if d.get("success") and d.get("data", {}).get("proxyList"):
                for p in d["data"]["proxyList"][:limit]:
                    all_proxies.append({"raw": p, "date": date})
        except Exception:
            continue

    if not all_proxies:
        return [], "拉取存档失败"

    # Step 3: Parse ip:port strings
    proxies = []
    seen = set()
    ip_port_re = re.compile(r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{2,5})$")
    for item in all_proxies:
        raw = item["raw"].strip()
        if raw in seen:
            continue
        seen.add(raw)
        m = ip_port_re.match(raw)
        if m:
            ip, port = m.group(1), m.group(2)
            proxies.append({
                "proxy": f"http://{ip}:{port}",
                "protocol": "http",
                "ip": ip,
                "port": int(port),
                "country": "",
                "city": "",
            })
            if len(proxies) >= limit:
                break
    return proxies, None


def fetch_proxies(source_id, limit=999999):
    """
    Fetch proxies from a source. Returns (proxy_list, source_name, error).
    """
    source = None
    for s in PROXY_SOURCES:
        if s["id"] == source_id:
            source = s
            break
    if not source:
        return [], None, f"未知来源: {source_id}"

    try:
        if source_id == "proxifly":
            proxies, err = _fetch_proxifly(source["url"], limit)
        elif source_id == "proxynova":
            proxies, err = _fetch_proxynova(source["url"], limit)
        elif source_id == "hidemn":
            proxies, err = _fetch_hidemn(source["url"], limit)
        elif source_id == "freeproxy":
            proxies, err = _fetch_freeproxy(source["url"], limit)
        elif source_id == "checkerproxy":
            proxies, err = _fetch_checkerproxy(source["url"], limit)
        else:
            return [], source["name"], f"未适配的来源: {source_id}"

        if err:
            return [], source["name"], err
        return proxies, source["name"], None

    except Exception as e:
        return [], source["name"], f"请求失败: {str(e)[:200]}"
