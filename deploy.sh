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
  sed -i '' "s/__BUILD__/$BUILD/g" "$f"
done

rsync -az "$STAGE/" jacksun-tencent:screen-share-live/web/
echo "已部署（构建 ${BUILD}）— 页面 no-cache，浏览器刷新即生效"
