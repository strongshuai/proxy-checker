# Proxy Checker v6.2

Proxy Checker 是一个自托管优先的免费代理检测、筛选、仓库维护工具。你可以把它理解成一个给代理池做体检的小面板：拉取持续更新的公共代理源，批量检测 HTTP、HTTPS、SOCKS4、SOCKS5、SOCKS5H，把真正有用的代理放进“我的仓库”，再生成稳定的 TXT / JSON 链接给脚本、服务或其他工具直接拉取。

如果你经常折腾代理、跑号服务器、API 连通性，v6.2 这一版就很适合放在自己的机器上跑。它不是那种“我在别的机器上测通了，所以你那里也一定能用”的玄学榜单，而是直接回答一个更实用的问题：**你这台服务器能不能连上这个代理，并且通过它访问目标服务？**

🚀 项目地址：[strongshuai/proxy-checker](https://github.com/strongshuai/proxy-checker)

<img width="2970" height="1830" alt="image" src="https://github.com/user-attachments/assets/c970c634-bb01-490d-ae6b-b9d257048623" />
<img width="2652" height="1563" alt="image" src="https://github.com/user-attachments/assets/84b9a523-aae2-4a4b-940e-954d52544089" />
<img width="2661" height="1556" alt="image" src="https://github.com/user-attachments/assets/78573d13-5fab-48e9-a60d-532572e5e381" />
<img width="1278" height="1815" alt="image" src="https://github.com/user-attachments/assets/44f3712d-77db-4a98-bc6b-2d398685c3e1" /><img width="1419" height="1527" alt="image" src="https://github.com/user-attachments/assets/6656ec66-fe46-45bf-b313-f9d364b66b57" />


## 这东西适合谁

- 想从公开免费代理源里捞可用代理，但不想手工复制、去重、挨个试。
- 想知道代理对当前服务器到底有没有用，而不是看别人服务器的检测结果。
- 想区分常规代理可用、网页可达、API 域名可达、Cloudflare 状态、出口 IP、国家和 IP 类型。
- 想维护一个自己的代理仓库，能筛选、复测、复制、导出，并生成稳定链接。
- 想让服务自己定时拉取、检测、更新仓库，浏览器关了也继续跑。

## 为什么推荐部署在自己用代理的服务器上

代理检测不是“全世界统一答案”，它本质上是这条链路是否通：

```text
你的检测服务器 -> 代理 IP -> 目标服务
```

别人服务器测出有效，只能说明别人那台机器到这个代理、再到目标服务是通的；你的服务器不一定能连上同一个代理。反过来也一样。**谁要用代理，谁来测，结果才最有参考价值。**

## 核心能力

### 1. 通用代理检测

- 支持 HTTP、HTTPS、SOCKS4、SOCKS5、SOCKS5H。
- 无协议前缀的代理会自动识别协议。
- 常规检测会关注 HTTPS 基础连通、出口 IP、国家、IP 类型。
- 结果会标记等级、稳定性和推荐用途，例如基础代理、网页可用、API 可用、网页+API。

### 2. AI 服务专项检测

内置 5 种检测模式：

- `generic`：默认常规代理检测。
- `openai`：检测 ChatGPT 首页、OpenAI API 域名、Cloudflare 状态。
- `grok`：检测 grok.com 和 xAI API。
- `gemini`：检测 gemini.google.com 和 Gemini API。
- `claude`：检测 claude.ai 和 Anthropic API。

API 返回 `401` / `403` 这类状态时，会被视为“API 域名可达”，因为它说明网络链路能到服务端；这不代表账号、Key 或额度可用。Cloudflare 状态只影响网页访问判断，不拿来误伤 API 可达性。

### 3. 不再检测“可注册”

v6.0 取消了注册页/账号入口检测。原因很简单：能打开注册页，不代表能注册成功。注册是否成功还受风控、手机号、邮箱、浏览器环境、历史行为、地区策略等影响，用一个 HTTP 状态下结论很容易误导。

现在工具只做更诚实也更有用的判断：当前服务器视角下，代理本身是否可用，目标网页/API 是否可达。

### 4. 免费代理源聚合

内置多个持续更新的代理源，包括 Proxifly、Databay、IPLocate、OpenProxyList/Roosterkid、TheSpeedX、VPSLab、Hookzof、Spys.me、ProxyScrape、GeoNode、My-Proxy，以及保守保留的 ProxyNova、hide.mn、free-proxy-list、CheckerProxy。

前端可以单独拉取某个源，也可以一键拉取所有免费代理源并按代理地址去重。不同时间点数量会波动，聚合规模通常可以到 1W+，最终质量仍以你自己的检测结果为准。

### 5. 有效代理 / 失效代理 / 我的仓库

- 三栏统一列表高度，适合长列表批量操作。
- 有效代理和失效代理都可以直接复制；有效代理可单行添加到仓库。
- “添加到我的仓库”后会自动同步云端仓库数据。
- 我的仓库按最新添加或更新置顶。
- 有效代理和我的仓库都支持标签筛选，例如等级、服务可达、API 域名可达、CF、国家、IP 类型。
- 每个标签都有鼠标 title 说明，hover 一下就能看到“这标签到底是什么意思”。
- 仓库链接使用浏览器稳定 token，公共部署时不同用户不会互相覆盖。

### 6. 刷新恢复和检测日志

- 手动检测过程中刷新页面，不会把 UI 状态搞丢，会恢复并继续轮询同一个后端任务。
- 检测日志会记录手动检测和自动任务的开始时间、结束时间、模式、轮次、并发、数量、有效/失效摘要。
- 日志在页面弹窗里查看，不需要翻服务器进程日志。

### 7. 后台自动任务

自托管 Python 服务支持真正的后端自动任务，不靠浏览器 `setInterval` 凑数。浏览器关闭后，服务仍然可以按计划拉取全部免费代理源，合并“我的仓库”里的代理，按设置的轮次、并发和检测模式批量检测，再把符合策略的结果同步到仓库 TXT / JSON 链接。

- 支持每隔 N 小时执行，也支持按指定时区每天固定 HH:MM 执行。
- 支持只检测新代理，或强制检测全部代理。
- 支持 `stable_only`、`include_unstable`、`archive_all` 三种入库策略。
- 默认启用复测失败清理：旧仓库代理参与本轮复测且判定失效时会被移除；整体任务异常时不会误删旧仓库。
- 自动任务运行中会拦截手动检测，避免同一台服务器被并发任务打爆。
- 状态区会显示自动运行进度；停止任务时会尽快打断后续检测。
- Vercel / Serverless 不支持后台常驻自动任务，会明确显示“不支持后台自动任务”。

### 8. 登录保护和全局设置

- 默认密码：`linux.do`，上线后建议立即修改。
- 同源自托管部署时，登录前只返回独立登录页，不下发主界面 HTML 和 `app.js`。
- 登录状态使用 HttpOnly Cookie；跨域静态前端可用登录后返回的访问令牌。
- 检测轮次、并发、请求超时、协议识别超时、登录有效期、日志保留条数、默认时区、登录密码都可以在设置弹窗里管理。
- 检测轮次默认 2 轮，上限保持 3 轮，避免免费代理批量检测被过度拖慢。
- 仓库 TXT / JSON 分享链接保持公开，方便其他程序直接拉取。

## v6.1 到 v6.2 更新内容

- 页面版本号更新到 `v6.2`，README 和 PRODUCT 同步更新发布说明。
- 修复自动任务入库后可能被旧浏览器本地仓库覆盖的问题：`/api/repo/save` 默认改为安全合并，旧本地记录不会再覆盖云端记录。
- 新增仓库写入防陈旧保护：明确删除/覆盖时带 `base_count` 校验，发现云端已被自动任务更新会拒绝覆盖并提示先刷新。
- 自动任务完成后，如果后端摘要里的仓库数量大于本地显示数量，前端会自动刷新“我的仓库”，让 UI、JSON、TXT 链接保持一致。
- “仓库链接”弹窗新增 `TXT` 和 `JSON` 两种链接：TXT 适合代理订阅，JSON 保留等级、国家、用途、服务可达等完整信息。
- 云端菜单里的“恢复云端数据”右侧新增云端代理数量显示，恢复前就能看到云端仓库大概有多少条。
- 我的仓库“清空”改成下拉菜单，支持按等级清空 A/B/C/D，也支持清空全部；清空会同步更新云端 TXT / JSON。
- 我的仓库筛选里的 4 个等级按钮合并为“等级筛选”下拉，减少筛选栏横向占用。
- 导入/导出菜单新增 JSON 格式，支持完整仓库数据的 JSON 导入和导出；TXT 导入导出继续保留。
- 从云端恢复仓库时不再触发反向自动同步，避免“刚读到云端数据又被旧本地状态写回”的覆盖风险。
- 日志、设置、自动任务弹窗改为先立即打开，再后台读取最新数据，减少点击后的等待感。
- 弹窗动画时间缩短，并支持 `prefers-reduced-motion`，操作反馈更快。
- 发布默认端口继续保持 `8888`，私有部署端口不写入公开项目。

## v6.0 到 v6.1 更新内容

- 页面版本号更新到 `v6.1`，README 和 PRODUCT 同步更新发布说明。
- 优化大批量结果渲染性能：有效代理、失效代理、我的仓库列表改为分批渲染，默认先渲染前 400 条，并提供“显示更多”，避免一口气把上万条代理全部塞进 DOM 导致前端卡顿。
- 检测结果保存改为延迟写入 `localStorage`，减少批量轮询时频繁序列化大 JSON 造成的主线程卡顿。
- 刷新恢复历史结果时也走分批渲染，不再因为历史结果很多而刷新后瞬间卡住。
- 有效代理、失效代理、我的仓库的筛选逻辑改为基于数据重新渲染，而不是在巨大的 DOM 列表上逐项隐藏/显示，筛选更稳也更轻。
- “CF绕过”文案改为更准确的“网页CF未拦截”，并在 hover title 里明确说明：这只代表目标网页本次没有遇到 Cloudflare 挑战，不保证注册、登录、Auth0 或其它账号链路一定能通过。
- 失效筛选里的 CF 文案同步改为“网页CF拦截”，避免让用户误以为工具承诺完整绕过 Cloudflare 风控。
- 修复设置弹窗里修改检测轮次后，外部实际检测仍沿用旧本地缓存轮次的问题。现在服务器设置返回后会同步覆盖隐藏检测控件和本地缓存。
- 确认并发设置真实生效：前端提交 `max_concurrent`，后端经过限制后同时作用于 `asyncio.Semaphore` 和 HTTP 客户端连接数。
- 自动模式统一改名为“自动任务”，相关按钮、弹窗标题、提示文案统一调整。
- 自动任务弹窗底部 4 个操作按钮改为一行等宽展示，保存、立即运行、停止、关闭更规整。
- 顶部标题区回归轻量样式：去掉 `.header` 背景和下边框，并增加负向底部间距，让主界面更紧凑。
- 页面标题居中展示，统计卡片从顶栏右侧移回代理输入卡片下方、结果区上方。
- 8 个统计卡片改成等宽网格并撑满容器，减少左右留白；上下间距调整一致。
- 动态状态文本 `statusText` 移到原来 `Ctrl+Enter 开始/停止` 的位置，不再占用按钮行最右侧空间。
- Deep Check 状态从代理列表卡片头部移入“设置”弹窗中展示，减少主界面常驻噪音。
- 所有主要按钮补充 emoji，包含登录、连接、检测、停止、清空、复制、添加仓库、筛选、设置、日志、自动任务、仓库操作和弹窗操作。
- “检测日志”按钮精简为“日志”，“自动模式”按钮改为“自动任务”。
- 我的仓库里的“清空仓库”精简为“清空”，“获取仓库链接”精简为“仓库链接”。
- 有效/失效/仓库内的清空按钮补充 emoji，操作入口更容易扫到。
- 仓库列表和结果列表里的复制、删除、添加到仓库、显示更多等动态按钮也统一补充 emoji。
- 本轮持续保持公开默认端口 `8888`，不把私有部署端口写入公开项目。

## v5.0 到 v6.0 更新内容

- 产品定位从单一 OpenAI/ChatGPT 代理检测，完整升级为通用免费代理检测、仓库维护、自动任务工具。
- 新增 `generic`、`openai`、`grok`、`gemini`、`claude` 五种检测模式。
- 重构代理有效性判断：以基础连通、目标首页/网页可达、API 域名可达、出口 IP、国家、IP 类型、CF 状态和推荐用途为核心。
- 取消注册页访问检测，不再用注册入口 HTTP 状态判断代理是否能注册账号。
- 首页失败不再提前终止检测，仍会继续尝试 API 和出口 IP，避免漏掉 API-only 代理。
- API `401` / `403` 继续算“API 域名可达”，明确不代表账号、Key 或额度可用。
- 新增等级与推荐用途展示：A/B/C/D/F、基础代理、网页可用、API 可用、网页+API、不稳定、失效。
- 新增出口 IP、国家、IP 类型显示，减少只看到 `HTTP 200` 却不知道代理实际出口的困惑。
- UI 文案从 ChatGPT 专用改为通用代理检测器，OpenAI 只是其中一个专项模式。
- 新增大量动态免费代理源：Databay、IPLocate、OpenProxyList/Roosterkid、TheSpeedX、VPSLab、Hookzof、Spys.me、ProxyScrape、GeoNode、My-Proxy 等。
- 拉取免费代理下拉菜单支持多列展示，避免源太多时菜单过长。
- 新增“一键拉取所有免费代理”，聚合后按代理地址去重，规模可达 1W+。
- 我的仓库新增和有效代理类似的标签筛选，支持等级、服务可达、API 域名可达、CF、国家、IP 类型等维度。
- 我的仓库列表高度和有效/失效列表统一，最新代理显示在第一位。
- 有效代理每行新增“添加到仓库”按钮，可单独入库；复制和添加按钮默认常显，不再只靠 hover。
- 失效代理复制按钮默认常显。
- 添加到我的仓库后自动同步云端仓库数据，仓库 TXT / JSON 链接保持最新。
- 仓库 token 改为每个浏览器稳定生成，公共部署不会互相覆盖。
- “获取仓库链接”从菜单里独立出来，放到云端按钮右侧。
- 检测任务支持刷新恢复，刷新页面不会打断检测 UI。
- 新增并发数量自定义，默认并发和上限可配置。
- 新增登录密码保护，默认密码 `linux.do`，并升级为登录前不下发主界面，避免只删前端浮层就能进入。
- 新增全局设置弹窗，可调整检测轮次、并发、超时、登录有效期、日志保留、默认时区和登录密码。
- 新增检测日志弹窗，手动检测和自动任务都会记录开始/结束时间、模式、轮次、并发、数量和结果摘要。
- 新增后台自动任务，自托管 Python 服务可在浏览器关闭后继续按计划执行。
- 新增自动任务持久化：每个浏览器 token 独立保存配置、状态、历史摘要和下次运行时间。
- 新增 `/api/auto/get`、`/api/auto/save`、`/api/auto/run-now`、`/api/auto/stop`、`/api/auto/status`。
- 自动任务会拉取全部免费代理源，合并“我的仓库”代理，按代理字符串去重后批量检测。
- 自动任务支持每隔 N 小时或每天固定计划时区执行，修复服务器时间和下次执行时间显示错位。
- 自动任务支持只检测新代理或强制检测全部代理。
- 自动任务支持三种入库策略：只入库稳定代理、包含不稳定代理、全部结果留档。
- 默认启用复测失败清理：旧仓库代理本轮复测失效时会删除，任务整体异常时不会误删。
- 自动任务运行中会拦截手动检测，避免服务器并发检测过载。
- 自动任务状态改为进度条胶囊展示，操作提示层级高于弹窗，保存/停止等提示不会被遮挡。
- 停止自动任务改为尽快停止后续队列；无法瞬间杀掉已经发出的网络请求时，会给出明确提示。
- 所有结果标签补充鼠标 title 说明，方便新用户理解每个标签含义。
- 合并前端入口，根目录 `index.html` 和 `app.js` 是唯一前端源码。
- Vercel / Serverless 明确降级为不支持后台自动任务，避免给用户错误预期。
- `tools/smoke.py` 改为无 SSH 密码、可指定 base URL 和登录密码，并覆盖检测模式、登录门禁、设置、日志、自动任务能力。
- README、PRODUCT 和页面版本号更新到 `v6.0`。
- 发布默认端口保持 `8888`，私有服务器端口不写入公开代码。

## v4.2 到 v5.0 历史回顾

- 移除 Vercel 相关旧引用，整理自托管 Python 服务路径。
- 修复代理拉取数量限制，支持拉取更多免费代理。
- README 增加在线体验、去重和部署说明。

## 快速开始

```bash
git clone https://github.com/strongshuai/proxy-checker.git
cd proxy-checker
pip install -r requirements.txt
python server.py
```

打开：

```text
http://localhost:8888
```

首次登录默认密码：

```text
linux.do
```

## 部署位置很重要

最好把 Proxy Checker 部署在你实际跑号、跑业务、调用目标服务的那台服务器上。

代理检测不是一个绝对结果，而是“检测服务器 -> 代理 IP -> 目标服务”这条链路在当前时间点是否可用。其他服务器能检测出有效代理，只能说明那台服务器可以连通这个代理 IP；不代表你的服务器也一定能连通。最终要看你的服务器能不能连上代理 IP，以及这个代理从你的服务器出口访问目标服务时是否正常。

简单说：谁要用代理，谁来测，结果才最有参考价值。

## 配置

默认配置在 [config.json](./config.json)。上线部署建议新建 `config.local.json` 覆盖私有配置，`config.local.json` 已加入 `.gitignore`，不会被提交。

示例：

```json
{
  "auth_password": "change-me",
  "auth_session_days": 7,
  "check_rounds": 2,
  "max_check_rounds": 3,
  "max_concurrent": 30,
  "max_concurrent_limit": 200,
  "timeout": 12,
  "detect_timeout": 8,
  "run_log_limit": 100,
  "timezone": "UTC",
  "port": 8888,
  "log_file": "server.log"
}
```

配置优先级：

```text
环境变量 > config.local.json > config.json > 程序默认值
```

可用配置：

| 配置项 | 环境变量 | 默认值 | 说明 |
|---|---|---:|---|
| `auth_password` | `AUTH_PASSWORD` | `linux.do` | 登录密码，留空可关闭密码保护 |
| `auth_session_days` | `AUTH_SESSION_DAYS` | `7` | 登录有效天数 |
| `check_rounds` | `CHECK_ROUNDS` | `2` | 默认检测轮次 |
| `max_check_rounds` | `MAX_CHECK_ROUNDS` | `3` | 页面允许选择的最大检测轮次 |
| `max_concurrent` | `MAX_CONCURRENT` | `30` | 默认检测并发数 |
| `max_concurrent_limit` | `MAX_CONCURRENT_LIMIT` | `200` | 用户可设置的最大并发数 |
| `timeout` | `TIMEOUT` | `12` | 目标服务请求超时秒数 |
| `detect_timeout` | `DETECT_TIMEOUT` | `8` | 自动识别代理协议时的单次超时秒数 |
| `run_log_limit` | `RUN_LOG_LIMIT` | `100` | 每个 token 保留的检测日志条数 |
| `timezone` | `APP_TIMEZONE` | `UTC` | 默认展示和计划任务时区 |
| `port` | `PORT` | `8888` | HTTP 服务端口 |
| `log_file` | `LOG_FILE` | `server.log` | 服务日志路径 |

## systemd 示例

```ini
[Unit]
Description=Proxy Checker
After=network.target

[Service]
WorkingDirectory=/opt/proxy-checker
ExecStart=/usr/bin/python3 /opt/proxy-checker/server.py
Restart=always
Environment=PORT=8888
Environment=AUTH_PASSWORD=change-me

[Install]
WantedBy=multi-user.target
```

## Smoke Test

```bash
python tools/smoke.py --base-url http://localhost:8888 --password linux.do
```

测试内容包括：

- `/api/capabilities`
- 登录认证
- 前端关键元素和函数
- `/api/start` 默认常规检测
- 5 个检测模式的无效代理回归
- 代理源清单、设置接口、检测日志、自动任务能力
- 未登录 capabilities 不暴露服务端日志路径

## 项目结构

```text
proxy-checker/
├── index.html          # 前端页面
├── app.js              # 前端逻辑
├── server.py           # Python HTTP 服务
├── api/index.py        # Serverless / Flask 入口
├── proxy_check.py      # 代理检测核心
├── fetch_proxies.py    # 免费代理源
├── config.json         # 默认配置
├── tools/smoke.py      # Smoke test
├── PRODUCT.md          # 产品上下文
├── requirements.txt    # Python 依赖
├── repo_data/          # 运行期仓库数据，已忽略
├── checked_data/       # 运行期已检测记录，已忽略
├── auto_data/          # 运行期自动任务配置和状态，已忽略
├── run_logs/           # 运行期检测日志，已忽略
└── README.md
```

## 发布前提醒

- 修改默认登录密码。
- 尽量部署在实际使用代理的服务器上，避免“别的机器测通、你的机器用不了”的误判。
- 不要提交 `config.local.json`、`.env`、日志文件、仓库数据、检测历史。
- 如果部署在公网，建议使用反向代理加 HTTPS。
- 免费代理质量波动很大，检测结果只代表当前时间点。

## License

MIT License
