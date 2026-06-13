# 🔍 ChatGPT Proxy Checker v3

多维度代理检测器 — 专为 OpenAI 账号注册场景设计，自动检测免费代理可用性。

## 🌐 在线体验

**Vercel 版：** [https://proxy-checker-gold.vercel.app](https://proxy-checker-gold.vercel.app)

> ⚠️ Vercel 仅推荐用于测试体验，受限于 Serverless 冷启动，速度很慢准确性也大幅降低。建议部署到自己的服务器以获得更快的检测速度以及更准的测试。

## ✨ 功能特性

### 检测能力
- **多协议支持** — HTTP / HTTPS / SOCKS4 / SOCKS5 / SOCKS5H，无前缀自动探测
- **Cloudflare 检测** — 响应体 + Headers 分析，识别 JS 挑战 / Managed 挑战 / Turnstile / 封锁
- **多目标检测** — 同时检测 chat.openai.com 首页、auth0 注册页、API 端点
- **IP 质量识别** — 自动识别住宅 IP vs 机房 IP，显示归属组织和国家
- **质量等级** — A/B/C/D/F 五级评定，一目了然
- **可配置检测轮数** — 1 轮(快速) / 2 轮(推荐) / 3 轮(严格)
- **多线程并发** — 默认 30 并发，支持大量代理批量检测

### 一键拉取免费代理 (v3 新增)
- **5 个免费代理源** — 一键拉取最新可用代理，自动追加到检测框
  - Proxifly Free Proxy List (~3500+ 条)
  - ProxyNova Proxy Server List
  - hidemy.name Proxy List
  - Free-Proxy-List.net Socks
  - CheckerProxy.net Archive (最近 3 天存档)

### 代理仓库 (v3 新增)
- **我的仓库** — 检测完成后可将优质代理按等级添加到本地仓库
- **localStorage 持久化** — 仓库数据保存在浏览器本地，刷新不丢失
- **再次检测** — 一键将仓库中的代理重新投入检测
- **导出/复制** — 支持导出 TXT 或一键复制所有仓库代理

### UI 优化 (v3 新增)
- **实时代理计数** — 输入框标题旁实时显示当前代理数量
- **Textarea 拖拽缩放** — 底部边缘可拖动调整输入框高度
- **导出格式优化** — 导出为 TXT 格式（一行一个代理），更简洁
- **统一按钮样式** — 检测轮数下拉框与按钮高度一致
- **紫色滚动条** — 全局深色主题滚动条，美观统一

## 📊 质量等级说明

| 等级 | 条件 | 含义 |
|------|------|------|
| **A 最优** | 首页 + API + CF绕过 + 可注册 | 完美，直接用于注册 |
| **B 良好** | 首页 + API + CF绕过 | 很好，注册页待验证 |
| **C 可用** | 首页 + API 可达 | 能用，可能遇到 CF |
| **D 仅首页** | 只有首页能访问 | 不太靠谱 |
| **F 失效** | 全部失败 | 不能用 |

## 🚀 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/strongshuai/proxy-checker.git
cd proxy-checker

# 一键安装（需要 root 权限）
chmod +x deploy/install.sh
sudo bash deploy/install.sh
```

### 手动安装

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
python server.py
```

### 使用 systemd（推荐）

```bash
# 复制 service 文件
sudo cp deploy/vpntest.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vpntest
sudo systemctl start vpntest

# 查看状态
sudo systemctl status vpntest

# 查看日志
journalctl -u vpntest -f
```

## 📁 项目结构

```
proxy-checker/
├── server.py          # 后端服务（Python）
├── index.html         # 前端页面
├── app.js             # 前端逻辑
├── fetch_proxies.py   # 免费代理拉取模块
├── requirements.txt   # Python 依赖
├── deploy/
│   ├── install.sh     # 一键安装脚本
│   └── vpntest.service # systemd 服务文件
└── README.md
```

## 🔧 API 接口

### POST /api/start
开始检测代理

```json
{
  "proxies": ["socks5://1.2.3.4:1080", "http://5.6.7.8:8080"],
  "rounds": 2
}
```

### POST /api/status
查询检测进度

```json
{
  "session_id": "xxx",
  "since": 0
}
```

### POST /api/stop
停止检测

```json
{
  "session_id": "xxx"
}
```

### POST /api/capabilities
查询服务器能力（支持的代理源、Deep Check 等）

### POST /api/fetch-proxies
一键拉取免费代理

```json
{
  "source": "proxifly",
  "limit": 500
}
```

## 🛡️ Cloudflare 检测原理

1. **Header 分析** — 检查 `cf-ray`、`cf-chl-*` 等 CF 特征头
2. **响应体分析** — 检测 15+ 种 CF 挑战标识（challenge-platform, turnstile, cf-chl-b 等）
3. **页面内容验证** — 区分真实页面 vs CF 挑战页
4. **多目标交叉验证** — 首页、注册页、API 端点分别检测

## 📝 支持的代理格式

```
# 无前缀（自动识别协议）
1.2.3.4:1080

# HTTP
http://1.2.3.4:8080

# HTTPS
https://1.2.3.4:8443

# SOCKS4
socks4://1.2.3.4:1080

# SOCKS5
socks5://1.2.3.4:1080

# SOCKS5H（远程 DNS）
socks5h://1.2.3.4:1080

# 带认证
http://user:pass@1.2.3.4:8080
```

## 📋 系统要求

- Python 3.8+
- Linux / macOS / Windows
- 约 20MB 内存

## 📄 License

MIT
