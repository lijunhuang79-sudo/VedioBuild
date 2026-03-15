#!/bin/bash
# 第二步：添加远程仓库并推送（第一步请在浏览器创建 GitHub 仓库）
# 用法: ./scripts/setup-remote-and-push.sh https://github.com/你的用户名/仓库名.git

set -e
cd "$(dirname "$0")/.."
REPO_URL="$1"
if [ -z "$REPO_URL" ]; then
  echo "用法: $0 <仓库URL>"
  echo "示例: $0 https://github.com/你的用户名/VedioBuild.git"
  echo ""
  echo "请先在 GitHub 创建仓库: https://github.com/new?name=VedioBuild"
  echo "创建后复制仓库的 HTTPS 地址，粘贴到上面命令中。"
  exit 1
fi
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"
git push -u origin main
echo "推送完成。在 Netlify 里连接该仓库即可自动部署。"
