@echo off
REM ==========================================================================
REM  Apartment management system - launcher
REM
REM    double-click this file    -> serve on this PC only
REM    run with argument /lan    -> also reachable from a phone on the same Wi-Fi
REM    run with argument /phone  -> reachable from your own phones anywhere,
REM                                 over Tailscale only. See docs\adr\0007.
REM    run with argument /excel  -> no server at all: write this year's records
REM                                 to an Excel workbook and open it. The file
REM                                 travels (LINE, email, OneDrive) and opens on
REM                                 any phone, but it is a snapshot, not live.
REM
REM  KEEP THIS FILE ASCII-ONLY.
REM  cmd.exe re-reads a batch file by byte offset while `chcp` changes how those
REM  bytes decode. Any non-ASCII character in here - even inside a REM comment -
REM  corrupts the parsing of later lines: variables come out empty and fragments
REM  of text get run as commands. All Thai text belongs in tools\stop-server.ps1
REM  or in Python, both of which handle UTF-8 properly. See docs\adr\0006.
REM ==========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "HOST=127.0.0.1"
if /i "%~1"=="/lan" set "HOST=0.0.0.0"
if /i "%~1"=="/phone" set "HOST=tailscale"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo   ERROR: Python was not found on this PC.
    echo   Install Python 3 from python.org, tick "Add python.exe to PATH",
    echo   then run this file again.
    echo.
    pause
    exit /b 1
)

REM Jumps before the server is touched: the workbook is a separate errand, and
REM it must not stop a server the owner is already using on this PC.
if /i "%~1"=="/excel" goto excel

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\stop-server.ps1"

python -m apartment serve --host "%HOST%" --port 8765 --open

if errorlevel 1 (
    echo.
    pause
)
exit /b 0

:excel
python -m apartment export --open
if errorlevel 1 (
    echo.
    pause
)
exit /b 0
