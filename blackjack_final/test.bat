@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 启动服务器...
start "服务器" cmd /k "chcp 65001 >nul && cd /d "%~dp0" && py -3.11 server.py"
timeout /t 2 >nul

echo 启动客户端1...
start "客户端1" cmd /k "chcp 65001 >nul && cd /d "%~dp0" && py -3.11 client_gui.py"
timeout /t 1 >nul

echo 启动客户端2...
start "客户端2" cmd /k "chcp 65001 >nul && cd /d "%~dp0" && py -3.11 client_gui.py"

echo 全部启动！两个客户端IP都填 127.0.0.1