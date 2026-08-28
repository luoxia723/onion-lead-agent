@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "CODEX_BIN="
where codex >nul 2>nul
if %ERRORLEVEL% EQU 0 set "CODEX_BIN=codex"

if not defined CODEX_BIN if exist "%LOCALAPPDATA%\Programs\ChatGPT\resources\codex.exe" set "CODEX_BIN=%LOCALAPPDATA%\Programs\ChatGPT\resources\codex.exe"
if not defined CODEX_BIN if exist "%LOCALAPPDATA%\Programs\ChatGPT\Resources\codex.exe" set "CODEX_BIN=%LOCALAPPDATA%\Programs\ChatGPT\Resources\codex.exe"
if not defined CODEX_BIN if exist "%ProgramFiles%\ChatGPT\resources\codex.exe" set "CODEX_BIN=%ProgramFiles%\ChatGPT\resources\codex.exe"
if not defined CODEX_BIN if exist "%ProgramFiles%\ChatGPT\Resources\codex.exe" set "CODEX_BIN=%ProgramFiles%\ChatGPT\Resources\codex.exe"

if not defined CODEX_BIN (
  for /d %%D in ("%LOCALAPPDATA%\ChatGPT\app-*") do (
    if exist "%%~fD\resources\codex.exe" set "CODEX_BIN=%%~fD\resources\codex.exe"
  )
)

echo.
echo ========================================
echo   洋葱投放 Agent｜一键连接
echo ========================================
echo.

if not defined CODEX_BIN (
  echo 未找到 Codex。请先安装并登录 Codex 桌面端，然后重新双击本文件。
  echo.
  pause
  exit /b 3
)

echo 即将打开浏览器。请只在浏览器页面粘贴管理员发放的一次性 Token。
echo 连接完成前请保持本窗口和 Codex 开启，不要转发浏览器链接。
echo.

"%CODEX_BIN%" mcp login onion-agent --oauth-client-registration dcr
set "STATUS=%ERRORLEVEL%"

echo.
if "%STATUS%"=="0" (
  echo 连接成功。现在回到 Codex，输入 /mcp 确认 onion-agent 已连接。
) else (
  echo 连接没有完成。请保持 Codex 开启后重试；如果浏览器一直等待，请检查本机防火墙是否拦截 127.0.0.1 回调。
)
echo.
pause
exit /b %STATUS%
