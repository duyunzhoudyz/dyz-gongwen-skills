@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 公文写作本机工具箱（零联网）

set "SCRIPT_DIR=%~dp0"
set "TOOLBOX=%SCRIPT_DIR%local_toolbox.py"
set "PY_CMD="

for %%P in ("py -3" "python" "python3") do (
    if not defined PY_CMD (
        %%~P -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
        if !errorlevel! equ 0 set "PY_CMD=%%~P"
    )
)

if not defined PY_CMD (
    echo 未找到 Python 3.9 及以上版本。
    echo 如无法安装 Python，可直接使用 xinchuang\templates\ 下的空白公文模板，
    echo 以及 dist\prompts-bundles\ 中的一站式提示词。
    pause
    exit /b 1
)

set "PORT_FILE=%TEMP%\gongwen_toolbox_port_%RANDOM%.txt"
if exist "%PORT_FILE%" del /f /q "%PORT_FILE%" >nul 2>&1

echo 正在启动本机零联网工具箱（仅监听 127.0.0.1）...
start "" /b cmd /v:on /c "for /l %%i in (1,1,20) do (if exist \"%PORT_FILE%\" (set /p P=<\"%PORT_FILE%\" & if defined P (start \"\" \"http://127.0.0.1:^!P^!\" & exit /b 0)) & ping -n 2 127.0.0.1 >nul)"

%PY_CMD% "%TOOLBOX%" --auto-port --port-file "%PORT_FILE%"
if exist "%PORT_FILE%" del /f /q "%PORT_FILE%" >nul 2>&1
pause
