# ==============================================================================
# Claude Cortex - PowerShell shim
#
# All logic lives in the Python core (cortex/). This file only locates it and
# hands over, so Windows and Linux run identical code. The previous PowerShell
# wrapper reimplemented the bash wrapper and had drifted badly: no login, no
# profile management, no doctor, and a different environment table.
# ==============================================================================

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ErrorActionPreference = "Stop"

# Locate the Cortex package: installed copy first, then alongside this script.
$CortexHome = $env:CORTEX_HOME
if (-not $CortexHome) {
    $candidates = @(
        (Join-Path $HOME ".claude\cortex-core"),
        (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path (Join-Path $c "cortex"))) {
            $CortexHome = $c
            break
        }
    }
}

if (-not $CortexHome -or -not (Test-Path (Join-Path $CortexHome "cortex"))) {
    Write-Error "cc: Cortex core not found. Reinstall with: powershell -File install.ps1"
    exit 1
}

$Python = $env:CORTEX_PYTHON
if (-not $Python) {
    foreach ($c in @("python", "python3", "py")) {
        $found = Get-Command $c -ErrorAction SilentlyContinue
        if ($found) { $Python = $found.Source; break }
    }
}

if (-not $Python) {
    Write-Error "cc: Python 3 is required but was not found on PATH."
    exit 1
}

$env:PYTHONPATH = $CortexHome
if ($null -eq $ScriptArgs) { $ScriptArgs = @() }

& $Python -m cortex @ScriptArgs
exit $LASTEXITCODE
