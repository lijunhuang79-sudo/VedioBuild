#!/bin/bash
# 释放 8000 端口并用「本地试用」配置重启后端
set -e
cd "$(dirname "$0")/.."
echo "正在释放 8000 端口..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true
sleep 1
echo "启动后端（SQLite + 进程内 Worker）..."
exec ./scripts/start-backend.sh
