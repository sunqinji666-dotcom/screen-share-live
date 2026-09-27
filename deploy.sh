#!/bin/bash
# screen-share-live 一键部署：注入构建号 → rsync 页面到服务器
# 用法：./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

BUILD=$(date "+%m-%d %H:%M")
STAGE=/tmp/ssl-deploy

rm -rf "$STAGE"
cp -R web "$STAGE"
for f in "$STAGE"/*.html; do
  # 兼容已注入过构建号的文件：先把旧构建号还原为占位符再注入，保证每次部署都刷新
  sed -i '' -E "s/构建 [0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}/构建 __BUILD__/g; s/__BUILD__/$BUILD/g" "$f"
done

rsync -az "$STAGE/" jacksun-tencent:screen-share-live/web/
echo "已部署（构建 ${BUILD}）— 页面 no-cache，浏览器刷新即生效"
