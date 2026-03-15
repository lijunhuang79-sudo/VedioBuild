#!/bin/bash
# 本地试用：启动后端（SQLite + 进程内 Worker）
# 在项目根目录执行: ./scripts/start-backend.sh
set -e
cd "$(dirname "$0")/.."
ROOT=$PWD

# 本地试用必须的环境变量（不依赖 xargs 加载 .env）
export DATABASE_URL="sqlite:///./demo.db"
export INLINE_WORKER=1
export LOCAL_STORAGE=1
export API_BASE_URL="http://localhost:8000"
export LOCAL_VIDEO_DIR="$ROOT/backend/static/videos"

# 从 .env 读取 DeepSeek 等（可选，逐行避免 xargs 问题）
if [ -f .env ]; then
  while IFS= read -r line; do
    [[ "$line" =~ ^#.*$ || -z "${line// }" ]] && continue
    key="${line%%=*}"
    val="${line#*=}"
    case "$key" in
      DEEPSEEK_API_KEY|DEEPSEEK_BASE_URL|DEEPSEEK_MODEL|JWT_SECRET_KEY) export "$key=$val" ;;
      ALIYUN_ACCESS_KEY_ID|ALIYUN_ACCESS_KEY_SECRET|ALIYUN_NLS_APPKEY|ALIYUN_NLS_REGION|ALIYUN_TTS_VOICE|ALIYUN_TTS_SPEECH_RATE|ALIYUN_TTS_PITCH_RATE|ALIYUN_TTS_VOLUME) export "$key=$val" ;;
      JIYMENG_IMAGE_API_URL|JIYMENG_IMAGE_API_KEY|JIYMENG_IMAGE_MODEL|PREFER_JIMENG_SCENE) export "$key=$val" ;;
      DASHSCOPE_API_KEY|USE_WANXIANG_VIDEO|DASHSCOPE_BASE_URL) export "$key=$val" ;;
    esac
  done < .env
fi

mkdir -p backend/static/videos
if lsof -ti:8000 >/dev/null 2>&1; then
  echo "错误: 端口 8000 已被占用。可先执行: lsof -ti:8000 | xargs kill -9"
  exit 1
fi
echo "后端启动: http://localhost:8000  (API 文档 http://localhost:8000/docs)"
echo "按 Ctrl+C 停止"
# 强制使用项目 .venv，保证 rembg 等依赖在 uvicorn 及子进程中都可用
if [ -x "$ROOT/.venv/bin/python" ]; then
  export PATH="$ROOT/.venv/bin:$PATH"
fi
cd backend
exec python -m uvicorn app.main:app --reload --reload-dir "$ROOT/backend" --reload-dir "$ROOT/worker" --host 0.0.0.0 --port 8000
