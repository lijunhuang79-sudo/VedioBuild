#!/bin/bash
# 一键启动后端 + 前端（本地 + 局域网 IP 访问）
# 项目根目录执行: ./scripts/start-all-local.sh
# 前端会监听 0.0.0.0:3000，可用 http://192.168.2.190:3000 访问
set -e
cd "$(dirname "$0")/.."
ROOT=$PWD

# 先启动后端（后台）
if lsof -ti:8000 >/dev/null 2>&1; then
  echo "后端已在运行 (8000)"
else
  echo "正在启动后端..."
  nohup "$ROOT/scripts/start-backend.sh" > /tmp/ai-video-backend.log 2>&1 &
  sleep 5
  if ! curl -s -o /dev/null -w "" http://localhost:8000/health 2>/dev/null; then
    echo "后端启动可能未就绪，请稍等几秒后访问"
  fi
fi

echo "正在启动前端 (0.0.0.0:3000)..."
echo "  本机: http://localhost:3000"
echo "  局域网: http://192.168.2.190:3000 (以本机实际 IP 为准)"
echo "按 Ctrl+C 停止前端（后端继续在后台运行）"
cd "$ROOT/frontend"
exec npm run dev
