#!/bin/sh
set -eu

SOURCE_DIR="/opt/proxy-checker"
APP_DIR="/app"

mkdir -p "${APP_DIR}"

# 同步镜像内置源码到运行目录，同时保留容器卷中的运行时数据。
rsync -a --delete \
    --exclude="config.local.json" \
    --exclude="repo_data/" \
    --exclude="checked_data/" \
    --exclude="auto_data/" \
    --exclude="run_logs/" \
    --exclude="server.log" \
    "${SOURCE_DIR}/" "${APP_DIR}/"

# 运行时目录由应用按需写入；这里提前创建，便于卷权限和健康检查稳定。
mkdir -p \
    "${APP_DIR}/repo_data" \
    "${APP_DIR}/checked_data" \
    "${APP_DIR}/auto_data" \
    "${APP_DIR}/run_logs"

cd "${APP_DIR}"

exec "$@"
