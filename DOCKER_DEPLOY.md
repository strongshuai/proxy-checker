# Docker Compose 镜像独立部署

本部署方式不修改业务源码，不依赖宿主机源码挂载。镜像内置默认配置 `config.json`，运行时配置和数据保存在 Docker 命名卷 `/app` 中。镜像构建阶段会安装 Playwright Chromium，用于可选的浏览器真实检测。

## 配置原则

- `config.json` 不单独挂载：它是版本默认配置，应随镜像更新。
- 运行时设置写入 `config.local.json`，并通过命名卷持久化。
- 不建议单文件挂载 `config.local.json`：应用使用临时文件加 `os.replace()` 原子写入，单文件挂载容易导致替换失败。
- 如需生产环境固定登录密码，可以在 `.env` 设置 `AUTH_PASSWORD`；设置后应用内修改密码会被禁用，这是当前源码行为。

## 快速启动

```bash
cp ".env.example" ".env"
docker compose build
docker compose up -d
docker compose logs -f "proxy-checker"
```

打开：

```text
http://localhost:8888
```

默认登录密码：

```text
linux.do
```

## 常用配置

编辑 `.env`：

```env
PROXY_CHECKER_PORT=8888
TZ=Asia/Shanghai
APP_TIMEZONE=Asia/Shanghai
AUTH_SESSION_SECRET=replace-with-a-random-secret
# AUTH_PASSWORD=your-strong-password
```

如果只想修改宿主机端口：

```bash
PROXY_CHECKER_PORT=8899 docker compose up -d
```

## 数据持久化

Compose 使用命名卷 `proxy-checker-data` 挂载到容器 `/app`。其中会保留：

- `config.local.json`
- `repo_data/`
- `checked_data/`
- `auto_data/`
- `run_logs/`
- `server.log`

升级镜像时，入口脚本会把 `/opt/proxy-checker/` 的新版本源码同步到 `/app/`，同时保留以上运行时数据。

## 验证

检查 Compose 配置：

```bash
docker compose config
```

检查服务能力：

```bash
curl -s -X POST "http://127.0.0.1:8888/api/capabilities" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

关键字段应为：

```json
{
  "auto_mode": true,
  "fetch_proxies": true,
  "playwright": true,
  "browser_check": true,
  "xvfb": true,
  "deep_check": true
}
```

运行项目自带冒烟测试：

```bash
python3 "tools/smoke.py" \
  --base-url "http://127.0.0.1:8888" \
  --password "linux.do"
```

成功时输出：

```text
smoke ok
```

## 运维命令

重启：

```bash
docker compose restart
```

查看日志：

```bash
docker compose logs -f "proxy-checker"
```

停止：

```bash
docker compose down
```

停止并删除持久化数据卷：

```bash
docker compose down -v
```

注意：`down -v` 会删除仓库、自动任务、日志和本地配置。
