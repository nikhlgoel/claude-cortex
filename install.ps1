# ==============================================================================
# Claude Cortex installer (Windows, PowerShell)
#
# A thin launcher. Everything the installer does lives in install.py, which is the
# one tested implementation (backup, settings merge, surfaces, profiles). This file
# only finds Python and hands over, so the two can never drift apart again.
#
#   .\install.ps1 -DryRun                              show what would change, change nothing
#   .\install.ps1                                      ask first, then install
#   .\install.ps1 -Yes -Surfaces terminal,desktop      unattended, with these surfaces
#   $env:CORTEX_SANDBOX = "1"; .\install.ps1           throwaway test home
#   $env:CORTEX_PYTHON = "C:\Python312\python.exe"     use a specific interpreter
#
# The usual switches also work in their install.py spelling: --yes --dry-run --surfaces
# Needs Python 3.8+. Exit codes: 0 done, 2 bad option, 3 the safety prompt stopped it.
# ==============================================================================

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $here) { $here = (Get-Location).Path }

# Scripts extracted from a downloaded zip carry a "mark of the web" that can block them.
# Only the script types PowerShell/cmd refuse to run are unblocked: walking the whole tree
# (including .git) made every launch take minutes.
foreach ($pattern in @("*.ps1", "*.cmd")) {
    Get-ChildItem -Path $here -Filter $pattern -File -ErrorAction SilentlyContinue |
        Unblock-File -ErrorAction SilentlyContinue
    Get-ChildItem -Path (Join-Path $here "bin") -Filter $pattern -File -ErrorAction SilentlyContinue |
        Unblock-File -ErrorAction SilentlyContinue
}

# Translate the PowerShell spellings into install.py's. Anything else is passed through
# untouched so install.py can refuse what it does not know.
$forward = New-Object System.Collections.Generic.List[string]
for ($i = 0; $i -lt $args.Count; $i++) {
    $a = [string]$args[$i]
    switch -Regex ($a) {
        '^-(Yes|y)$'          { $forward.Add("--yes") }
        '^-DryRun$'           { $forward.Add("--dry-run") }
        '^-NoPrimaryProfile$' { $forward.Add("--no-primary-profile") }
        '^-Surfaces$'         {
            $forward.Add("--surfaces")
            if ($i + 1 -lt $args.Count) { $i++; $forward.Add(([string[]]$args[$i]) -join ",") }
        }
        default               { $forward.Add($a) }
    }
}

function Test-Python([string[]]$cmd) {
    # The Microsoft Store "python.exe" stub exits non-zero and prints an advert; running a
    # real one-liner tells the two apart.
    try {
        $exe = $cmd[0]
        $rest = @($cmd | Select-Object -Skip 1) + @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)")
        & $exe @rest *> $null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

$python = $null
if ($env:CORTEX_PYTHON) {
    if (Test-Python @($env:CORTEX_PYTHON)) { $python = @($env:CORTEX_PYTHON) }
    else {
        Write-Host "error: CORTEX_PYTHON='$($env:CORTEX_PYTHON)' is not a working Python 3.8+." -ForegroundColor Red
        exit 1
    }
} else {
    foreach ($candidate in @(@("py", "-3"), @("python"), @("python3"))) {
        if ((Get-Command $candidate[0] -ErrorAction SilentlyContinue) -and (Test-Python $candidate)) {
            $python = $candidate
            break
        }
    }
}

if (-not $python) {
    Write-Host "error: Python 3.8 or newer is required and was not found." -ForegroundColor Red
    Write-Host "       Install it from https://www.python.org/downloads/ (tick 'Add to PATH')," -ForegroundColor Red
    Write-Host "       or set CORTEX_PYTHON to the interpreter you want." -ForegroundColor Red
    exit 1
}

$exe = $python[0]
$pre = @($python | Select-Object -Skip 1)
& $exe @pre (Join-Path $here "install.py") @forward
exit $LASTEXITCODE
