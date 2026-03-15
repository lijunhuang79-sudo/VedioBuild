#!/bin/bash
# 本地试用：启动前端（生产模式，避免 dev 模式 404/EMFILE）
# 在项目根目录执行: ./scripts/start-frontend.sh
set -e
cd "$(dirname "$0")/.."

export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
cd frontend
if [ ! -d .next ] || [ ! -f .next/BUILD_ID ]; then
  echo "首次或需重新构建前端..."
  npm run build
fi
echo "前端: http://localhost:3000  (API: $NEXT_PUBLIC_API_URL)"
echo "按 Ctrl+C 停止"
exec npm run start
