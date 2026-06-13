# 🔍 ChatGPT Proxy Checker v4.1

多维度代理检测器 — 专为 OpenAI 账号注册场景设计，自动检测免费代理可用性。

## 🌐 截图
<img width="3743" height="1992" alt="屏幕截图_13-6-2026_11916_23 94 202 182" src="https://github.com/user-attachments/assets/d1b200dd-adf7-41d4-a5b9-af6194b97612" />

## ✨ 功能特性

### 检测能力
- **多协议支持** — HTTP / HTTPS / SOCKS4 / SOCKS5 / SOCKS5H，无前缀自动探测
- **Cloudflare 检测** — 响应体 + Headers 分析，识别 JS 挑战 / Managed 挑战 / Turnstile / 封锁
- **多目标检测** — 同时检测 chat.openai.com 首页、auth0 注册页、API 端点
- **IP 质量识别** — 自动识别住宅 IP vs 机房 IP，显示归属组织和国家
- **质量等级** — A/B/C/D/F 五级评定，一目了然
- **可配置检测轮数** — 1 轮(快速) / 2 轮(推荐) / 3 轮(严格)
- **多线程并发** — 默认 30 并发，支持大量代理批量检测

### 一键拉取免费代理
- **5 个免费代理源** — 一键拉取最新可用代理，自动追加到检测框
  - Proxifly Free Proxy List (~3500+ 条)
  - ProxyNova Proxy Server List
  - hidemy.name Proxy List
  - Free-Proxy-List.net Socks
  - CheckerProxy.net Archive (最近 3 天存档)

### 智能检测跳过 (v4 新增)
- **检测历史持久化** — 自动记录已检测过的代理，换浏览器/清缓存不丢失
- **跳过已检测代理** — 默认模式自动跳过，避免重复检测浪费时间
- **强制检测全部** — 下拉菜单可切换，一键重新检测所有代理
- **清空检测记录** — 随时清空历史，重新开始

### Tab 三合一面板 (v4 新增)
- **有效代理 Tab** — 筛选栏(全部/稳定/不稳定/CF绕过/可注册/延迟区间) + 清空/复制/添加到仓库
- **失效代理 Tab** — 筛选栏(全部/超时/CF拦截/连接错误/其他) + 清空/复制
- **我的仓库 Tab** — 清空仓库/导入导出/云端同步/再次检测

### 代理仓库
- **本地持久化** — localStorage 保存，刷新不丢失
- **云端持久化** — 服务器端 JSON 格式保存完整检测信息(等级/延迟/IP/CF/注册)
- **导入 TXT** — 支持导入外部 txt/csv 文件，自动去重
- **导出 TXT** — 一键导出仓库所有代理
- **恢复/保存云端** — 手动同步云端数据，换设备也能恢复
- **仓库链接分享** — 生成可分享的代理列表链接

## 📋 更新日志

### v4.1
- **链接不再变化** — 修复了"获取仓库链接"功能，token 不再基于内容 hash 生成
- **固定为 `/api/repo/myrepo.txt`** — 复制到其他程序后无需反复更新

### v4
- **统计面板移至右上角** — 8 个统计卡片在 header 右侧横向排列
- **三面板合并为 Tab 切换** — 有效代理/失效代理/我的仓库合为一个卡片
- **检测历史持久化** — 服务器端保存已检测代理列表，换设备不丢失
- **JSON 格式存储** — 云端保存完整检测信息
- **一键拉取免费代理** — 5 个免费代理源，一键拉取

## 🚀 快速部署

### 方式一：直接运行
```bash
git clone https://github.com/strongshuai/proxy-checker.git
cd proxy-checker
pip install -r requirements.txt
python server.py
# 访问 http://localhost:8888
```

## 📁 项目结构

```
proxy-checker/
├── index.html          # 前端页面
├── app.js              # 前端逻辑
├── server.py           # 后端服务
├── fetch_proxies.py    # 免费代理拉取模块
├── requirements.txt    # Python 依赖
└── README.md
```

## ⚙️ 配置

### 环境变量
- `PORT` — 服务端口，默认 8888

### 检测配置 (server.py)
- `TIMEOUT` — 请求超时时间，默认 12 秒
- `DETECT_TIMEOUT` — 单次检测超时，默认 8 秒
- `MAX_CONCURRENT` — 最大并发数，默认 30
- `CHECK_ROUNDS` — 默认检测轮数，默认 2

## 📄 License

MIT License
