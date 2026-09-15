@echo off
setlocal EnableDelayedExpansion
title Claude Cortex Windows Installer
color 0B

echo ======================================================================
echo           Installing Claude Cortex for Windows
echo ======================================================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Step 1: Execute PowerShell Installer with ExecutionPolicy Bypass
echo [1/3] Checking PowerShell execution...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "& { Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force -ErrorAction SilentlyContinue; Unblock-File -Path '%SCRIPT_DIR%*.*' -ErrorAction SilentlyContinue; & '%SCRIPT_DIR%install.ps1' %* }"
set PS_EXIT=%ERRORLEVEL%

if %PS_EXIT% equ 0 (
    echo.
    echo ======================================================================
    echo   [SUCCESS] Claude Cortex installed successfully via PowerShell!
    echo ======================================================================
    goto :DONE
)

echo.
echo [WARNING] PowerShell installation exited with status code %PS_EXIT%.
echo Attempting fallback installation via Python...
echo.

REM Step 2: Try Python fallback if PowerShell was blocked or failed
where python.exe >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [2/3] Launching installer via Python...
    python "%SCRIPT_DIR%install.py" %*
    if !ERRORLEVEL! equ 0 (
        echo.
        echo ======================================================================
        echo   [SUCCESS] Claude Cortex installed successfully via Python!
        echo ======================================================================
        goto :DONE
    )
)

where py.exe >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [3/3] Launching installer via Py launcher...
    py "%SCRIPT_DIR%install.py" %*
    if !ERRORLEVEL! equ 0 (
        echo.
        echo ======================================================================
        echo   [SUCCESS] Claude Cortex installed successfully via Py launcher!
        echo ======================================================================
        goto :DONE
    )
)

echo.
echo ======================================================================
echo [ERROR] Installation could not be completed automatically.
echo Please run either:
echo   powershell -ExecutionPolicy Bypass -File .\install.ps1
echo or:
echo   python install.py
echo ======================================================================

:DONE
echo.
echo Press any key to close this window...
pause >nul
exit /b %PS_EXIT%
