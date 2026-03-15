#!/usr/bin/env bash
# 创建 worker/assets/bgm 目录并提示放入 BGM 文件（本系统不自动生成 BGM）
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BGM_DIR="$ROOT_DIR/worker/assets/bgm"
mkdir -p "$BGM_DIR"
echo "已创建目录: $BGM_DIR"
echo "请将 MP3 文件放入该目录并命名为 default.mp3（或 tech.mp3 / blockbuster.mp3），详见: $BGM_DIR/README.md"
