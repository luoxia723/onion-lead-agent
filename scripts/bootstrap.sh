#!/bin/bash
set -euo pipefail

MODE="check"
case "${1:-}" in
  ""|--check) MODE="check" ;;
  --prepare) MODE="prepare" ;;
  --install) MODE="install" ;;
  *) echo "用法: /bin/bash scripts/bootstrap.sh [--check|--prepare|--install]" >&2; exit 2 ;;
esac

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

python_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python || true)"
if [[ -z "$PYTHON_BIN" && "$MODE" == "install" ]]; then
  if command -v brew >/dev/null 2>&1; then
    brew install python@3.12
    PYTHON_BIN="$(find_python || true)"
  else
    echo "缺少Python 3.10+，且没有Homebrew。请先安装Homebrew或从python.org安装Python，再重新运行。" >&2
    exit 3
  fi
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "缺少Python 3.10+。让Codex在取得你的确认后运行: /bin/bash scripts/bootstrap.sh --install" >&2
  exit 3
fi

if ! command -v git >/dev/null 2>&1; then
  if [[ "$MODE" == "install" ]]; then
    if command -v brew >/dev/null 2>&1; then
      brew install git
    else
      echo "缺少Git且没有Homebrew。ZIP可以使用，但自动Pull需要先安装Git。" >&2
    fi
  else
    echo "WARN: 未找到Git；ZIP可以使用，仓库自动Pull不可用。"
  fi
fi

RUN_PYTHON="$PYTHON_BIN"
if [[ "$MODE" == "prepare" || "$MODE" == "install" ]]; then
  VENV_DIR="$PROJECT_ROOT/.runtime/venv"
  mkdir -p "$PROJECT_ROOT/.runtime"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  RUN_PYTHON="$VENV_DIR/bin/python"
fi

echo "环境口径: Python>=3.10；Git仅用于Pull；Node.js、FFmpeg和云厂商SDK不需要安装。"
"$RUN_PYTHON" "$PROJECT_ROOT/scripts/first_run_check.py" --offline
if [[ "$MODE" == "prepare" || "$MODE" == "install" ]]; then
  echo "environment_prepare=ok python=$RUN_PYTHON"
else
  echo "environment_check=ok python=$RUN_PYTHON"
fi
