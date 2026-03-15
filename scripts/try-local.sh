#!/bin/bash
# 本地试用（无需 Docker）：SQLite + 进程内 Worker + 本地视频目录
set -e
cd "$(dirname "$0")/.."
ROOT=$PWD

# 加载 .env（保留 DeepSeek 等配置），并覆盖为本地试用配置
export DATABASE_URL="sqlite:///./demo.db"
export INLINE_WORKER=1
export LOCAL_STORAGE=1
export API_BASE_URL="http://localhost:8000"
[ -f .env ] && export $(grep -v '^#' .env | xargs)
export DATABASE_URL="sqlite:///./demo.db"
export INLINE_WORKER=1
export LOCAL_STORAGE=1

echo "=========================================="
echo "  AI 视频工厂 - 本地试用（无 Docker）"
echo "=========================================="
echo "  后端: http://localhost:8000"
echo "  前端: http://localhost:3000"
echo "  文档: http://localhost:8000/docs"
echo "=========================================="

# 后端目录下 static/videos 给 worker 写文件用
mkdir -p backend/static/videos
export LOCAL_VIDEO_DIR="$ROOT/backend/static/videos"

# 先装依赖（若未装）
if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "安装后端依赖..."
  pip3 install -r backend/requirements.txt -q
fi
if ! python3 -c "import moviepy" 2>/dev/null; then
  echo "安装 Worker 依赖（含 MoviePy）..."
  pip3 install -r worker/requirements.txt -q
fi

cd frontend
if [ ! -d node_modules ]; then
  echo "安装前端依赖..."
  npm install
fi
cd ..

echo ""
echo "启动后端（SQLite + 进程内 Worker）..."
(cd backend && python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!
sleep 3

echo "启动前端..."
(cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev) &
FRONT_PID=$!

echo ""
echo "已启动。按 Ctrl+C 停止。"
wait $BACKEND_PID $FRONT_PID 2>/dev/null || true
