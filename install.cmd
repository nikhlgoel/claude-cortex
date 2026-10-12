@echo off
setlocal EnableExtensions
REM ----------------------------------------------------------------------------
REM Claude Cortex installer (Windows, double-click or cmd.exe)
REM
REM A thin launcher: finds Python and runs install.py, which holds all the logic.
REM   install.cmd --dry-run
REM   install.cmd --yes --surfaces terminal,desktop
REM Needs Python 3.8+. Set CORTEX_PYTHON to use a specific interpreter.
REM Exit codes: 0 done, 2 bad option, 3 the safety prompt stopped it.
REM ----------------------------------------------------------------------------

set "HERE=%~dp0"
set "PYRUN="
set "RC=0"

if defined CORTEX_PYTHON (
    "%CORTEX_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
    if errorlevel 1 (
        echo error: CORTEX_PYTHON="%CORTEX_PYTHON%" is not a working Python 3.8+.
        set "RC=1"
        goto :done
    )
    set PYRUN="%CORTEX_PYTHON%"
    goto :run
)

REM A real one-liner is run on purpose: the Microsoft Store "python.exe" stub exists on
REM PATH but only prints an advert.
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYRUN=py -3"
)
if not defined PYRUN (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
        if not errorlevel 1 set "PYRUN=python"
    )
)
if not defined PYRUN (
    echo error: Python 3.8 or newer is required and was not found.
    echo        Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^),
    echo        or set CORTEX_PYTHON to the interpreter you want.
    set "RC=1"
    goto :done
)

:run
%PYRUN% "%HERE%install.py" %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="3" (
    echo.
    echo Stopped at the safety prompt. Nothing was changed.
) else if not "%RC%"=="0" (
    echo.
    echo The installer exited with code %RC%. See the messages above.
)

:done
REM Keep the window open only when it was double-clicked. Explorer starts a script as
REM   cmd.exe /c ""C:\path\install.cmd" "
REM (doubled quote); a terminal or automation never produces that form, and a pause there
REM would hang the caller.
set "RAW=%CMDCMDLINE:"=Q%"
if "%RAW:/c QQ=%"=="%RAW%" exit /b %RC%
echo.
pause
exit /b %RC%
