#!/bin/bash
# 下载 5 首不同的 BGM 到 worker/assets/bgm/，供 VedioBuild 视频混流使用。
# 若下载失败则用 ffmpeg 生成 5 段不同音高的可听占位 MP3（非静音），确保视频有 BGM 声。
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BGM_DIR="$ROOT_DIR/worker/assets/bgm"
mkdir -p "$BGM_DIR"
cd "$BGM_DIR"

# 5 个文件名与用途（与 worker _get_bgm_path 一致）
# default, tech, blockbuster, cinematic, upbeat
NAMES=(default tech blockbuster cinematic upbeat)

# 可选：直接 MP3 下载 URL（每行一个，顺序对应 NAMES；空则用 ffmpeg 生成占位）
# 可自行替换为 Pixabay/FreePD 等站的直链，或设环境变量 BGM_DEFAULT_URL 等
BGM_URLS=(
  "${BGM_DEFAULT_URL:-}"
  "${BGM_TECH_URL:-}"
  "${BGM_BLOCKBUSTER_URL:-}"
  "${BGM_CINEMATIC_URL:-}"
  "${BGM_UPBEAT_URL:-}"
)

log() { echo "[download-bgm] $*"; }

# 用 ffmpeg 生成一段非静音占位 MP3（指定频率与时长，便于区分 5 首）
gen_placeholder() {
  local out="$1"
  local freq="${2:-262}"
  local dur="${3:-60}"
  if command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -y -f lavfi -i "sine=frequency=${freq}:duration=${dur}:sample_rate=44100" -ac 2 -ar 44100 -q:a 5 "$out" 2>/dev/null && return 0
  fi
  return 1
}

# 尝试用 curl 下载
download_one() {
  local url="$1"
  local out="$2"
  [[ -z "$url" ]] && return 1
  curl -sSfL --connect-timeout 10 --max-time 60 -o "$out" "$url" 2>/dev/null && [[ -s "$out" ]] && return 0
  return 1
}

for i in "${!NAMES[@]}"; do
  name="${NAMES[$i]}"
  file="${name}.mp3"
  url="${BGM_URLS[$i]:-}"
  if [[ -n "$url" ]] && download_one "$url" "$file"; then
    log "已下载: $file"
  elif gen_placeholder "$file" "$((262 + i * 80))" 60; then
    log "已生成占位 BGM（可替换为真实 MP3）: $file"
  else
    log "跳过 $file（无 URL 且 ffmpeg 不可用）"
  fi
done

log "BGM 目录: $BGM_DIR"
log "请将 Docker 使用的 worker 挂载此目录，或把本目录复制到容器内 worker/assets/bgm/。"
