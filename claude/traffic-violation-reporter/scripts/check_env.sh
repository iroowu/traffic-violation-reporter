#!/usr/bin/env bash
# 檢查交通違規檢舉小精靈需要的工具是否齊備。缺什麼就印出安裝指令。
# 用法：bash scripts/check_env.sh
missing=0
check() {
  local name="$1" hint="$2"
  if command -v "$name" >/dev/null 2>&1; then
    printf "  ✅ %-10s %s\n" "$name" "$(command -v "$name")"
  else
    printf "  ❌ %-10s 沒有安裝。安裝方式：%s\n" "$name" "$hint"
    missing=1
  fi
}
echo "== 必要工具 =="
check ffmpeg   "macOS: brew install ffmpeg ／ Ubuntu: sudo apt install ffmpeg ／ Windows: winget install ffmpeg"
check ffprobe  "隨 ffmpeg 一起安裝"
check exiftool "macOS: brew install exiftool ／ Ubuntu: sudo apt install libimage-exiftool-perl ／ Windows: 到 exiftool.org 下載"
check python3  "macOS 內建；Windows 到 python.org 下載 3.9 以上"
if command -v exiftool >/dev/null 2>&1; then
  v=$(exiftool -ver 2>/dev/null); major=${v%%.*}; minor=${v#*.}; minor=${minor%%.*}
  if [ "${major:-0}" -lt 13 ] || { [ "${major:-0}" -eq 13 ] && [ "${minor:-0}" -lt 7 ]; }; then
    echo "  ⚠️  exiftool 版本 $v 太舊：Viofo A229、Rexing 等新韌體的加密 GPS（LIGOGPSINFO）要 13.07 以上才讀得到。macOS: brew upgrade exiftool"
  else
    echo "  ✅ exiftool 版本 $v（≥ 13.07，支援新韌體加密 GPS）"
  fi
fi
echo
echo "== Python 套件（只用標準庫，不需另外安裝）=="
python3 - <<'PY' 2>/dev/null && echo "  ✅ python3 標準庫可用" || { echo "  ❌ python3 執行失敗"; exit 1; }
import json, math, subprocess, pathlib, datetime, argparse, statistics
PY
echo
echo "== 縣市邊界資料 =="
here="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$here/assets/taiwan_counties.geojson" ]; then
  echo "  ✅ assets/taiwan_counties.geojson $(du -h "$here/assets/taiwan_counties.geojson" | cut -f1)"
else
  echo "  ❌ 找不到 assets/taiwan_counties.geojson（skill 打包不完整）"
  missing=1
fi
if [ -f "$here/assets/taiwan_towns.geojson" ]; then
  echo "  ✅ assets/taiwan_towns.geojson $(du -h "$here/assets/taiwan_towns.geojson" | cut -f1)"
else
  echo "  ❌ 找不到 assets/taiwan_towns.geojson（skill 打包不完整）"
  missing=1
fi
echo
if [ "$missing" = 0 ]; then echo "全部就緒。"; else echo "有缺項，請先照上面的提示安裝，再重跑一次。"; exit 1; fi
