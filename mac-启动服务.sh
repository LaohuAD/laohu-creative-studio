#!/bin/bash
cd "$(dirname "$0")" || exit 1
# 安装和启动复用同一环境；浏览器只在服务真正就绪后打开。
if [ -x ".venv/bin/python" ]; then
  PYEXE="$PWD/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYEXE="$(command -v python3)"
else
  echo "找不到可启动安装程序的 Python。请检查根目录 .python-version，并安装其指定版本：https://www.python.org/downloads/"
  exit 1
fi
exec "$PYEXE" "$PWD/local_runtime.py" "$@"
