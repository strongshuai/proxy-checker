#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
SERVER_PID=""

kill_process_tree() {
  local signal="$1"
  local pid="$2"
  local child_pid

  # 先递归处理子进程，避免浏览器检测等子进程残留。
  while IFS= read -r child_pid; do
    [[ -n "${child_pid}" ]] && kill_process_tree "${signal}" "${child_pid}"
  done < <(pgrep -P "${pid}" 2>/dev/null || true)

  kill "-${signal}" "${pid}" 2>/dev/null || true
}

cleanup() {
  if [[ -n "${SERVER_PID}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo
    echo "正在停止 Proxy Checker 服务..."
    kill_process_tree "TERM" "${SERVER_PID}"

    for _ in {1..10}; do
      if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
        wait "${SERVER_PID}" 2>/dev/null || true
        return
      fi
      sleep 0.3
    done

    echo "服务未及时退出，执行强制结束..."
    kill_process_tree "KILL" "${SERVER_PID}"
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}

trap cleanup INT TERM EXIT

cd "${ROOT_DIR}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：未找到 python3，请先安装 Python 3。"
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "创建 Python 虚拟环境：${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

echo "安装/更新 Python 依赖..."
python -m pip install --upgrade pip
python -m pip install -r "${ROOT_DIR}/requirements.txt"
python -m playwright install chromium

echo "启动 Proxy Checker 服务..."
python3 "${ROOT_DIR}/server.py" &
SERVER_PID="$!"

wait "${SERVER_PID}"
SERVER_PID=""
