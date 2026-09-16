@echo off
REM ==========================================================================
REM Claude Cortex - IDE process wrapper (Windows)
REM
REM The extension invokes a wrapper as:
REM     wrapper <path-to-bundled-claude> [session args...]
REM passing its bundled binary as the FIRST argument. We shift it off and exec.
REM
REM Windows needs a real executable path here, which is why this is a .cmd and
REM not a bash script: the extension host cannot launch a shell script directly.
REM ==========================================================================
setlocal

if "%~1"=="" (
    echo cortex-ide-wrapper: expected the Claude binary path as the first argument 1>&2
    exit /b 2
)

set "REAL_CLAUDE=%~1"
shift

if defined CORTEX_PROFILE_DIR (
    set "CLAUDE_CONFIG_DIR=%CORTEX_PROFILE_DIR%"
    set "CLAUDE_SECURESTORAGE_CONFIG_DIR=%CORTEX_PROFILE_DIR%"
)

set "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE="
set "CLAUDE_CODE_AUTO_COMPACT_WINDOW="

REM %* still holds the original argv, so rebuild the tail after the binary path.
set "ARGS="
:collect
if "%~1"=="" goto run
set "ARGS=%ARGS% "%~1""
shift
goto collect

:run
"%REAL_CLAUDE%" %ARGS%
exit /b %ERRORLEVEL%
