@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo =========================
echo 启动服务器...
echo =========================
start cmd /k "chcp 65001 >nul && cd /d "%~dp0" && py -3.11 server.py"

echo 等待服务器启动...
timeout /t 3 >nul

echo =========================
echo 启动客户端...
echo =========================
py -3.11 client_gui.py

pause