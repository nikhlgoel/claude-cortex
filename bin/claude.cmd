@echo off
REM Claude Cortex Windows Batch Shim
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0claude.ps1" %*
