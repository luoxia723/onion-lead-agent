#!/bin/bash
set -u

PROJECT_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CODEX_BIN="$(command -v codex 2>/dev/null || true)"

if [[ -z "$CODEX_BIN" ]]; then
  for candidate in \
    "/Applications/ChatGPT.app/Contents/Resources/codex" \
    "$HOME/Applications/ChatGPT.app/Contents/Resources/codex"; do
    if [[ -x "$candidate" ]]; then
      CODEX_BIN="$candidate"
      break
    fi
  done
fi

echo
echo "========================================"
echo "  洋葱投放 Agent｜一键连接"
echo "========================================"
echo

if [[ -z "$CODEX_BIN" ]]; then
  echo "未找到 Codex。请先安装并登录 Codex 桌面端，然后重新双击本文件。"
  echo
  read -r -n 1 -p "按任意键关闭窗口..."
  echo
  exit 3
fi

cd "$PROJECT_ROOT" || exit 4
echo "即将打开浏览器。请只在浏览器页面粘贴管理员发放的一次性 Token。"
echo "连接完成前请保持本窗口和 Codex 开启，不要转发浏览器链接。"
echo

"$CODEX_BIN" mcp login onion-agent --oauth-client-registration dcr
STATUS=$?

echo
if [[ $STATUS -eq 0 ]]; then
  echo "连接成功。现在回到 Codex，输入 /mcp 确认 onion-agent 已连接。"
else
  echo "连接没有完成。请保持 Codex 开启后重试；如果浏览器一直等待，请检查本机防火墙是否拦截 127.0.0.1 回调。"
fi
echo
read -r -n 1 -p "按任意键关闭窗口..."
echo
exit "$STATUS"
