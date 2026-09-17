@echo off
title Task Manager - All Services
echo ============================================
echo   Task Manager - Dang khoi dong...
echo ============================================
echo.

echo [1/2] Khoi dong DNS Server (port 53)...
start "DNS Server" cmd /c "cd /d "%~dp0" && python dns_server.py"
timeout /t 2 /nobreak >nul

echo [2/2] Khoi dong Web Server (port 80)...
start "Web Server" cmd /c "cd /d "%~dp0" && python app.py"

echo.
echo ============================================
echo   Tat ca da khoi dong!
echo   - Web:  http://dtnlamkhe.com
echo   - DNS:  127.0.0.1:53
echo ============================================
echo.
echo Nhan phim bat ky de dong...
pause >nul
