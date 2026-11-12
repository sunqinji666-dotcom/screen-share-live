#!/bin/bash
# 把同屏录制的 .webm 转成 QuickTime/剪辑软件都能直接打开的 .mp4
# 视频是 H.264，直接拷贝不重编码（秒级完成、画质无损）；只把音频 Opus 转 AAC。
# 用法：./rec2mp4.sh 文件1.webm [文件2.webm ...]    转出的 mp4 放在原文件旁边
set -euo pipefail
command -v ffmpeg >/dev/null || { echo "没有 ffmpeg，请先 brew install ffmpeg"; exit 1; }
for f in "$@"; do
  out="${f%.*}.mp4"
  vcodec=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$f")
  if [ "$vcodec" = "h264" ]; then
    ffmpeg -v error -y -i "$f" -c:v copy -c:a aac -b:a 160k -movflags +faststart "$out"
  else
    echo "（$f 视频是 $vcodec，需要重新编码，会慢一些）"
    ffmpeg -v error -y -i "$f" -c:v libx264 -preset veryfast -crf 20 -c:a aac -b:a 160k -movflags +faststart "$out"
  fi
  echo "已生成：$out"
done
