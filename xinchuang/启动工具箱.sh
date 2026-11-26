#!/usr/bin/env bash
# 国产信创系统（银河麒麟 / 统信 UOS / Linux）一键启动本机零联网工具箱
# 双击运行或在终端执行：bash xinchuang/启动工具箱.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLBOX="$SCRIPT_DIR/local_toolbox.py"

find_python() {
  local cand
  for cand in python3 python; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      printf '%s' "$cand"
      return 0
    fi
  done
  return 1
}

PY="$(find_python || true)"
if [ -z "$PY" ]; then
  echo "未找到 Python 3.9 及以上版本。"
  echo "请先请单位信息中心安装 python3（如 sudo apt install python3），"
  echo "或直接使用 xinchuang/templates/ 下的空白公文模板，以及 dist/prompts-bundles/ 中的提示词。"
  if [ -t 0 ]; then
    read -r -p "按回车键退出..." _
  fi
  exit 1
fi

PORT_FILE="$(mktemp "${TMPDIR:-/tmp}/gongwen-toolbox-port.XXXXXX")"
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$PORT_FILE"
}
trap cleanup EXIT INT TERM

"$PY" "$TOOLBOX" --auto-port --port-file "$PORT_FILE" &
SERVER_PID=$!

PORT=""
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if [ -s "$PORT_FILE" ]; then
    PORT="$(cat "$PORT_FILE" 2>/dev/null || true)"
    [ -n "$PORT" ] && break
  fi
  kill -0 "$SERVER_PID" 2>/dev/null || break
  sleep 0.25
done

if [ -n "$PORT" ]; then
  URL="http://127.0.0.1:${PORT}"
  echo "正在打开浏览器：$URL（若未自动弹出，请手动复制该地址到浏览器）"
  echo "关闭本窗口或按 Ctrl+C 即退出，脱敏映射表会随进程销毁。"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
  fi
fi

wait "$SERVER_PID"
