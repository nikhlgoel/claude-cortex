# ==============================================================================
# Claude Cortex: Windows PowerShell Wrapper
# Multi-Account Manager, Capacity Auto-Failover, Memory Palace, Models & Reasoning, Providers
# ==============================================================================

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ProfilesDir = Join-Path $HOME ".claude-profiles"
$CurrentProfileFile = Join-Path $ProfilesDir "current_profile"
$SharedClaudeDir = Join-Path $HOME ".claude"
$CleanupScript = Join-Path $SharedClaudeDir "scripts\token-opt-clean.ps1"
$CapacityScript = Join-Path $SharedClaudeDir "scripts\claude-capacity-check.py"
$PalaceScript = Join-Path $SharedClaudeDir "scripts\claude-palace.py"
$ProviderScript = Join-Path $SharedClaudeDir "scripts\claude-provider.py"
$ResearchScript = Join-Path $SharedClaudeDir "scripts\claude-research.py"
$CognitionScript = Join-Path $SharedClaudeDir "scripts\claude-cognition.py"

# Locate real Claude Code binary on Windows
$RealClaude = $null
$Candidates = @(
    (Join-Path $HOME ".local\bin\claude.real.exe"),
    (Join-Path $HOME ".local\bin\claude.real.cmd"),
    (Join-Path $HOME ".local\bin\claude.real.ps1"),
    (Join-Path $env:LOCALAPPDATA "Programs\claude\claude.exe"),
    (Join-Path $HOME "AppData\Roaming\npm\claude.cmd")
)

foreach ($c in $Candidates) {
    if (Test-Path $c) {
        $RealClaude = $c
        break
    }
}

if (-not $RealClaude) {
    $found = Get-Command "claude.exe" -ErrorAction SilentlyContinue
    if ($found) {
        $RealClaude = $found.Source
    }
}

if (-not $RealClaude) {
    Write-Error "Error: Claude Code binary not found. Please install Claude Code first."
    exit 1
}

function Get-AllProfiles {
    if (Test-Path $ProfilesDir) {
        return @(Get-ChildItem $ProfilesDir -Directory | Select-Object -ExpandProperty Name)
    }
    return @()
}

function Get-ActiveProfile {
    if ($env:CLAUDE_PROFILE) {
        return $env:CLAUDE_PROFILE.ToLower().Trim()
    }
    if (Test-Path $CurrentProfileFile) {
        return (Get-Content $CurrentProfileFile).ToLower().Trim()
    }
    $all = Get-AllProfiles
    if ($all.Count -gt 0) {
        return $all[0]
    }
    return "main"
}

function Get-ProfileMode([string]$prof) {
    $modeFile = Join-Path $ProfilesDir "$prof\.profile_mode"
    if (Test-Path $modeFile) {
        return (Get-Content $modeFile).ToLower().Trim()
    }
    return "synced"
}

function Ensure-ProfileStructure([string]$prof, [string]$mode = "synced") {
    $targetDir = Join-Path $ProfilesDir $prof
    if (-not (Test-Path $targetDir)) { New-Item -ItemType Directory -Path $targetDir -Force | Out-Null }
    Set-Content -Path (Join-Path $targetDir ".profile_mode") -Value $mode -NoNewline

    if ($mode -eq "synced") {
        $sharedItems = @(
            "projects", "file-history", "history.jsonl", "commands",
            "skills", "rules", "plugins", "settings.json", "mcp-configs",
            "session-env", "shell-snapshots", "ide", "palace"
        )
        foreach ($item in $sharedItems) {
            $src = Join-Path $SharedClaudeDir $item
            $dst = Join-Path $targetDir $item
            if ((Test-Path $src) -and (-not (Test-Path $dst))) {
                if (Test-Path $src -PathType Container) {
                    New-Item -ItemType Junction -Path $dst -Target $src -Force | Out-Null
                } else {
                    New-Item -ItemType HardLink -Path $dst -Target $src -Force | Out-Null
                }
            }
        }
    } else {
        New-Item -ItemType Directory -Path (Join-Path $targetDir "projects") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $targetDir "commands") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $targetDir "mcp-configs") -Force | Out-Null
        $sharedSettings = Join-Path $SharedClaudeDir "settings.json"
        $profSettings = Join-Path $targetDir "settings.json"
        if ((Test-Path $sharedSettings) -and (-not (Test-Path $profSettings))) {
            Copy-Item -Path $sharedSettings -Destination $profSettings -Force
        }
    }
}

function Show-Status {
    if (Test-Path $CapacityScript) {
        python $CapacityScript
    } else {
        $cur = Get-ActiveProfile
        Write-Host "======================================================================" -ForegroundColor Cyan
        Write-Host "              Claude Cortex - Windows Status" -ForegroundColor Cyan
        Write-Host "======================================================================" -ForegroundColor Cyan
        Write-Host "Active Default Profile:  $($cur.ToUpper())`n"

        Write-Host "Configured Profiles:"
        Write-Host ("  {0,-12} {1,-10} {2}" -f "PROFILE / KEY", "MODE", "ACTIVE")
        Write-Host ("  {0,-12} {1,-10} {2}" -f "-------------", "----", "------")

        $all = Get-AllProfiles
        $idx = 1
        foreach ($pname in $all) {
            $pmode = (Get-ProfileMode $pname).ToUpper()
            $activeTag = if ($pname -eq $cur) { "<-- ACTIVE" } else { "" }
            Write-Host ("  {0,-12} {1,-10} {2}" -f "$pname (-$idx)", $pmode, $activeTag)
            $idx++
        }
    }

    Write-Host "`nQuick Commands:" -ForegroundColor Yellow
    Write-Host "  claude continue        Auto-check capacity across all accounts and resume session"
    Write-Host "  claude switch [prof]   Toggle or switch active default profile"
    Write-Host "  claude status / quota  Display real-time capacity and rate-limit countdowns"
    Write-Host "  claude palace          Inspect Cognitive Memory Palace"
    Write-Host "  claude provider        Manage external API providers"
    Write-Host "  claude reasoning [lvl] Configure thinking effort level"
    Write-Host "  claude docs            View comprehensive Cortex documentation"
    Write-Host "======================================================================" -ForegroundColor Cyan
}

function Show-Docs {
    Write-Host @"
===============================================================================
                     CLAUDE CORTEX USER GUIDE
===============================================================================

1. ACCOUNT & PROFILE MANAGEMENT
-------------------------------------------------------------------------------
  claude -1 / claude -2   Launch by profile index (1st profile, 2nd profile)
  claude -ws / claude -vl Launch by profile name (e.g. claude -work, claude -main)
  claude switch           Toggle between configured profiles
  claude switch <profile> Set specific profile as active default
  claude status / quota   Display real-time capacity and rate-limit countdowns
  claude menu             Launch interactive terminal menu

2. LATEST MODELS & REASONING CONTROL
-------------------------------------------------------------------------------
  claude -s / --sonnet    Launch Claude Sonnet 5 (claude-sonnet-5)
  claude -o / --opus      Launch Claude Opus 5 (claude-opus-5)
  claude -h / --haiku     Launch Claude Haiku 4.5 (claude-haiku-4-5)
  claude -e <level>       Set reasoning effort (low, medium, high, max)
  claude --think-high     Deep reasoning effort
  claude reasoning <lvl>  Configure default reasoning level in settings.json

3. AUTONOMOUS CAPACITY-BASED AUTO-FAILOVER (RATE-LIMIT BYPASS)
-------------------------------------------------------------------------------
  When limits hit, simply run:
    claude continue
  Scans all configured accounts, calculates reset times, automatically picks
  an account with available capacity, and resumes session with --continue!

4. COGNITIVE MEMORY PALACE
-------------------------------------------------------------------------------
  claude palace           View Memory Palace map & rooms
  claude remember <r> <n> Deposit a fix or architectural lesson
  claude recall <query>   Recall past solutions matching a topic

5. COGNITIVE DREAM ENGINE (STRESS TESTING)
-------------------------------------------------------------------------------
  claude dream            Simulate counterfactual scenarios (REM mode)
  claude dream --quick    Fast 2-chamber sanity check

6. EXTERNAL API PROVIDERS
-------------------------------------------------------------------------------
  claude provider         Manage providers (Anthropic API, OpenRouter, Gemini)
  claude --provider <p>   Launch with specific provider
===============================================================================
"@
}

# Subcommands
if ($ScriptArgs.Count -gt 0) {
    $SubArgs = if ($ScriptArgs.Count -gt 1) { @($ScriptArgs[1..($ScriptArgs.Count - 1)]) } else { @() }
    switch ($ScriptArgs[0].ToLower()) {
        "status" { Show-Status; exit 0 }
        "quota" { Show-Status; exit 0 }
        "limits" { Show-Status; exit 0 }
        "whoami" { Show-Status; exit 0 }
        "docs" { Show-Docs; exit 0 }
        "dream" {
            $DreamScript = Join-Path $SharedClaudeDir "scripts\claude-dream.py"
            if (Test-Path $DreamScript) {
                python $DreamScript @SubArgs
            }
            exit 0
        }
        "palace" {
            if (Test-Path $PalaceScript) {
                python $PalaceScript @SubArgs
            }
            exit 0
        }
        "remember" {
            if (Test-Path $PalaceScript) {
                python $PalaceScript remember @SubArgs
            }
            exit 0
        }
        "recall" {
            if (Test-Path $PalaceScript) {
                python $PalaceScript recall @SubArgs
            }
            exit 0
        }
        "provider" {
            if (Test-Path $ProviderScript) {
                python $ProviderScript @SubArgs
            }
            exit 0
        }
        "model" {
            $ModelsScript = Join-Path $SharedClaudeDir "scripts\claude-models.py"
            if (Test-Path $ModelsScript) {
                python $ModelsScript @SubArgs
            }
            exit 0
        }
        "models" {
            $ModelsScript = Join-Path $SharedClaudeDir "scripts\claude-models.py"
            if (Test-Path $ModelsScript) {
                python $ModelsScript @SubArgs
            }
            exit 0
        }
        "research" {
            if (Test-Path $ResearchScript) {
                python $ResearchScript @SubArgs
            }
            exit 0
        }
        "discovery" {
            if (Test-Path $ResearchScript) {
                python $ResearchScript @SubArgs
            }
            exit 0
        }
        "think" {
            if (Test-Path $CognitionScript) {
                python $CognitionScript @SubArgs
            }
            exit 0
        }
        "smart" {
            if (Test-Path $CognitionScript) {
                python $CognitionScript @SubArgs
            }
            exit 0
        }
        "cognition" {
            if (Test-Path $CognitionScript) {
                python $CognitionScript @SubArgs
            }
            exit 0
        }
        "turbo" {
            & "$PSCommandPath" -t @SubArgs
            exit $LASTEXITCODE
        }
        "fast" {
            & "$PSCommandPath" -t @SubArgs
            exit $LASTEXITCODE
        }
        "reasoning" {
            if ($ScriptArgs.Count -gt 1) {
                $lvl = $ScriptArgs[1].ToLower()
                $settingsPath = Join-Path $SharedClaudeDir "settings.json"
                if (Test-Path $settingsPath) {
                    $json = Get-Content $settingsPath -Raw | ConvertFrom-Json
                    $json | Add-Member -Name "effortLevel" -Value $lvl -MemberType NoteProperty -Force
                    $json | ConvertTo-Json | Set-Content $settingsPath
                }
                Write-Host "✓ Default reasoning effort set to: $lvl" -ForegroundColor Green
            }
            exit 0
        }
        "switch" {
            $all = Get-AllProfiles
            $target = ""
            if ($ScriptArgs.Count -gt 1) {
                $target = $ScriptArgs[1].ToLower().Trim().TrimStart("-")
                if ($target -match '^\d+$') {
                    $idx = [int]$target - 1
                    if ($idx -ge 0 -and $idx -lt $all.Count) { $target = $all[$idx] }
                }
            } else {
                if (Test-Path $CapacityScript) {
                    $best = (python $CapacityScript --best)
                    if ($best) { $target = $best.Trim() }
                }
                if (-not $target) {
                    $cur = Get-ActiveProfile
                    foreach ($p in $all) {
                        if ($p -ne $cur) { $target = $p; break }
                    }
                    if (-not $target) { $target = $cur }
                }
            }

            $targetDir = Join-Path $ProfilesDir $target
            if (-not (Test-Path $targetDir)) {
                Write-Error "Error: Profile '$target' does not exist."
                exit 1
            }
            Set-Content -Path $CurrentProfileFile -Value $target -NoNewline
            Write-Host "✓ Switched active Claude Code account to: $($target.ToUpper())" -ForegroundColor Green
            exit 0
        }
        "continue" {
            $all = Get-AllProfiles
            $target = ""
            $subArgs = @()
            if ($ScriptArgs.Count -gt 1) {
                $candidate = $ScriptArgs[1].ToLower().TrimStart("-")
                if ($candidate -match '^\d+$') {
                    $idx = [int]$candidate - 1
                    if ($idx -ge 0 -and $idx -lt $all.Count) { $candidate = $all[$idx] }
                }
                if (Test-Path (Join-Path $ProfilesDir $candidate)) {
                    $target = $candidate
                    $subArgs = $ScriptArgs[2..($ScriptArgs.Count - 1)]
                } else {
                    $subArgs = $ScriptArgs[1..($ScriptArgs.Count - 1)]
                }
            }
            if (-not $target) {
                if (Test-Path $CapacityScript) {
                    Write-Host "Scanning configured accounts for available capacity..." -ForegroundColor Cyan
                    python $CapacityScript
                    $best = (python $CapacityScript --best)
                    if ($best -and (Test-Path (Join-Path $ProfilesDir $best.Trim()))) {
                        $target = $best.Trim()
                    }
                }
                if (-not $target) {
                    $cur = Get-ActiveProfile
                    foreach ($p in $all) {
                        if ($p -ne $cur) { $target = $p; break }
                    }
                    if (-not $target) { $target = $cur }
                }
            }

            Ensure-ProfileStructure $target (Get-ProfileMode $target)
            Set-Content -Path $CurrentProfileFile -Value $target -NoNewline
            $env:CLAUDE_CONFIG_DIR = Join-Path $ProfilesDir $target
            $env:CLAUDE_SECURESTORAGE_CONFIG_DIR = Join-Path $ProfilesDir $target
            $env:COMPACT_CONTEXT_THRESHOLD = "100000"
            $env:COMPACT_CONTEXT_INTERVAL = "30000"
            $env:CLAUDE_CODE_AUTO_COMPACT_WINDOW = "100000"
            $env:BASH_MAX_OUTPUT_LENGTH = "20000"
            Write-Host "`n✓ Resuming session using profile: $($target.ToUpper())" -ForegroundColor Cyan
            $translatedSubArgs = @()
            for ($i = 0; $i -lt $subArgs.Count; $i++) {
                $arg = $subArgs[$i]
                if ($arg -eq "-y" -or $arg -eq "--yes") {
                    $translatedSubArgs += "--dangerously-skip-permissions"
                    continue
                }
                if ($arg -eq "-s" -or $arg -eq "--sonnet" -or $arg -eq "--sonnet-5") {
                    $translatedSubArgs += @("--model", "claude-sonnet-5")
                    continue
                }
                if ($arg -eq "-o" -or $arg -eq "--opus" -or $arg -eq "--opus-5") {
                    $translatedSubArgs += @("--model", "claude-opus-5")
                    continue
                }
                if ($arg -eq "-h" -or $arg -eq "--haiku" -or $arg -eq "--haiku-4-5") {
                    $translatedSubArgs += @("--model", "claude-haiku-4-5")
                    continue
                }
                if ($arg -eq "-e" -or $arg -eq "--effort" -or $arg -eq "-r" -or $arg -eq "--reasoning") {
                    $i++
                    $effVal = if ($i -lt $subArgs.Count) { $subArgs[$i] } else { "high" }
                    $translatedSubArgs += @("--effort", $effVal)
                    continue
                }
                if ($arg -eq "--think-low") { $translatedSubArgs += @("--effort", "low"); continue }
                if ($arg -eq "--think-med") { $translatedSubArgs += @("--effort", "medium"); continue }
                if ($arg -eq "--think-high") { $translatedSubArgs += @("--effort", "high"); continue }
                if ($arg -eq "--think-max") { $translatedSubArgs += @("--effort", "max"); continue }
                if ($arg -eq "--think-off") { $translatedSubArgs += @("--thinking", "disabled"); continue }
                $translatedSubArgs += $arg
            }
            & $RealClaude --continue $translatedSubArgs
            exit $LASTEXITCODE
        }
    }
}

# Fresh Installation Check
$allProfiles = Get-AllProfiles
if ($allProfiles.Count -eq 0) {
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "              Welcome to Claude Cortex!" -ForegroundColor Cyan
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "No profile found. Initializing primary profile [MAIN]..."
    Ensure-ProfileStructure "main" "synced"
    Set-Content -Path $CurrentProfileFile -Value "main" -NoNewline
    $env:CLAUDE_CONFIG_DIR = Join-Path $ProfilesDir "main"
    $env:CLAUDE_SECURESTORAGE_CONFIG_DIR = Join-Path $ProfilesDir "main"
    & $RealClaude auth login
}

# Parse profile flags, model shortcuts, and reasoning levels
$SelectedProfile = ""
$RemainingArgs = @()
$all = Get-AllProfiles

for ($i = 0; $i -lt $ScriptArgs.Count; $i++) {
    $arg = $ScriptArgs[$i]
    if ($arg -eq "-y" -or $arg -eq "--yes") {
        $RemainingArgs += "--dangerously-skip-permissions"
        continue
    }
    if ($arg -eq "-s" -or $arg -eq "--sonnet" -or $arg -eq "--sonnet-5") {
        $RemainingArgs += @("--model", "claude-sonnet-5")
        continue
    }
    if ($arg -eq "-o" -or $arg -eq "--opus" -or $arg -eq "--opus-5") {
        $RemainingArgs += @("--model", "claude-opus-5")
        continue
    }
    if ($arg -eq "-h" -or $arg -eq "--haiku" -or $arg -eq "--haiku-4-5") {
        $RemainingArgs += @("--model", "claude-haiku-4-5")
        continue
    }
    if ($arg -eq "-e" -or $arg -eq "--effort" -or $arg -eq "-r" -or $arg -eq "--reasoning") {
        $i++
        $RemainingArgs += @("--effort", $ScriptArgs[$i])
        continue
    }
    if ($arg -eq "--think-low") {
        $RemainingArgs += @("--effort", "low")
        continue
    }
    if ($arg -eq "--think-med") {
        $RemainingArgs += @("--effort", "medium")
        continue
    }
    if ($arg -eq "--think-high") {
        $RemainingArgs += @("--effort", "high")
        continue
    }
    if ($arg -eq "--think-max") {
        $RemainingArgs += @("--effort", "max")
        continue
    }
    if ($arg -eq "--think-off") {
        $RemainingArgs += @("--thinking", "disabled")
        continue
    }
    if ($arg -eq "-t" -or $arg -eq "--turbo" -or $arg -eq "--fast") {
        $RemainingArgs += @("--model", "claude-haiku-4-5", "--thinking", "disabled")
        $env:CLAUDE_TURBO = "1"
        $env:BASH_MAX_OUTPUT_LENGTH = "8000"
        continue
    }
    if ($arg -eq "--openrouter") {
        if (Test-Path $ProviderScript) {
            $envs = python $ProviderScript env openrouter
            foreach ($line in $envs) {
                if ($line -match "^export\s+([^=]+)='(.*)'") {
                    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
                }
            }
        }
        continue
    }
    if ($arg -eq "--gemini") {
        if (Test-Path $ProviderScript) {
            $envs = python $ProviderScript env gemini
            foreach ($line in $envs) {
                if ($line -match "^export\s+([^=]+)='(.*)'") {
                    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
                }
            }
        }
        continue
    }
    if ($arg -eq "--free") {
        if (Test-Path $ProviderScript) {
            $envs = python $ProviderScript env openrouter
            foreach ($line in $envs) {
                if ($line -match "^export\s+([^=]+)='(.*)'") {
                    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
                }
            }
        }
        $env:ANTHROPIC_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
        continue
    }
    if ($arg -match '^-[1-9]$' -or $arg -match '^--p[1-9]$' -or $arg -match '^-p[1-9]$') {
        $idx = [int]($arg -replace '\D', '') - 1
        if ($idx -ge 0 -and $idx -lt $all.Count) {
            $SelectedProfile = $all[$idx]
            continue
        }
    }
    if ($arg.StartsWith("-")) {
        $stripped = $arg.TrimStart("-").ToLower()
        if (Test-Path (Join-Path $ProfilesDir $stripped)) {
            $SelectedProfile = $stripped
            continue
        }
    }
    $RemainingArgs += $arg
}

if (-not $SelectedProfile) {
    $SelectedProfile = Get-ActiveProfile
}

Ensure-ProfileStructure $SelectedProfile (Get-ProfileMode $SelectedProfile)

$env:CLAUDE_CONFIG_DIR = Join-Path $ProfilesDir $SelectedProfile
$env:CLAUDE_SECURESTORAGE_CONFIG_DIR = Join-Path $ProfilesDir $SelectedProfile
$env:COMPACT_CONTEXT_THRESHOLD = "100000"
$env:COMPACT_CONTEXT_INTERVAL = "30000"
$env:CLAUDE_CODE_AUTO_COMPACT_WINDOW = "100000"
$env:BASH_MAX_OUTPUT_LENGTH = "20000"

# Auto-inject model flag if ANTHROPIC_MODEL is set
if ($env:ANTHROPIC_MODEL) {
    $hasModel = $false
    for ($i = 0; $i -lt $RemainingArgs.Count; $i++) {
        if ($RemainingArgs[$i] -eq "--model" -or $RemainingArgs[$i] -like "--model=*") {
            $hasModel = $true
            break
        }
    }
    if (-not $hasModel) {
        $RemainingArgs += @("--model", $env:ANTHROPIC_MODEL)
    }
}

& $RealClaude $RemainingArgs
exit $LASTEXITCODE
