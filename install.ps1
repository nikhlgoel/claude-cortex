# ==============================================================================
# Claude Cortex: 1-Click Universal Windows Installer
# Multi-Account Manager, Capacity Auto-Failover, Cognitive Memory Palace,
# Neuroscience Dream Simulation, Models & Reasoning Control, API Fallback Proxy
# ==============================================================================

Set-StrictMode -Off
$ErrorActionPreference = "Continue"

# 0. Auto-Bypass Execution Policy & Clear Mark of the Web
try {
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force -ErrorAction SilentlyContinue
} catch {}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $ScriptDir) { $ScriptDir = (Get-Location).Path }

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "          Installing Claude Cortex for Windows" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

# Unblock files in script directory to remove Zone.Identifier (Mark of the Web)
try {
    Get-ChildItem -Path $ScriptDir -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
} catch {}

$BinDir = Join-Path $HOME ".local\bin"
$ClaudeDir = Join-Path $HOME ".claude"
$ProfilesDir = Join-Path $HOME ".claude-profiles"
$BackupDir = Join-Path $HOME ".claude-backups"

# ==============================================================================
# SANDBOX GUARD
# This installer replaces the `claude` command, writes lifecycle hooks, and
# installs rules that change model behavior. It refuses to run unless the
# operator has explicitly opted in, so it cannot be triggered by accident.
#   CORTEX_SANDBOX=1  - container / throwaway environment
#   -Yes              - explicit opt-in
#   -DryRun           - print planned changes and exit
# ==============================================================================
$AssumeYes = $false
$DryRun = $false
foreach ($a in $args) {
    if ($a -eq "-Yes" -or $a -eq "--yes" -or $a -eq "-y") { $AssumeYes = $true }
    if ($a -eq "-DryRun" -or $a -eq "--dry-run") { $DryRun = $true }
}

if ($DryRun) {
    Write-Host "[DRY RUN] Would install Claude Cortex with:" -ForegroundColor Yellow
    Write-Host "  wrapper   -> $BinDir\claude.ps1 / claude.cmd"
    Write-Host "  scripts   -> $ClaudeDir\scripts\"
    Write-Host "  commands  -> $ClaudeDir\commands\"
    Write-Host "  rules     -> $ClaudeDir\rules\"
    Write-Host "  settings  -> $ClaudeDir\settings.json (hooks)"
    Write-Host "  profiles  -> $ProfilesDir\"
    Write-Host "[DRY RUN] No changes made." -ForegroundColor Yellow
    exit 0
}

if ($env:CORTEX_SANDBOX -ne "1" -and -not $AssumeYes) {
    Write-Host "======================================================================" -ForegroundColor Yellow
    Write-Host "  Claude Cortex installer - CONFIRMATION REQUIRED" -ForegroundColor Yellow
    Write-Host "======================================================================" -ForegroundColor Yellow
    Write-Host "  This will modify your live Claude Code installation:"
    Write-Host "    * replace the claude command in $BinDir"
    Write-Host "    * write lifecycle hooks into $ClaudeDir\settings.json"
    Write-Host "    * install rules that change model behavior"
    Write-Host ""
    Write-Host "  Set CORTEX_SANDBOX=1 to run in a container, or pass -DryRun first."
    Write-Host "======================================================================" -ForegroundColor Yellow
    # Exit code 3 means "the safety guard stopped this run". install.cmd must not
    # treat it as a recoverable failure and retry the Python installer, or the
    # guard is trivially bypassed.
    $confirm = Read-Host "  Type INSTALL to continue"
    if ($confirm -ne "INSTALL") {
        Write-Host "  Aborted. Nothing was changed." -ForegroundColor Green
        exit 3
    }
}
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

if (-not (Test-Path $BinDir)) { New-Item -ItemType Directory -Path $BinDir -Force | Out-Null }
if (-not (Test-Path $ClaudeDir)) { New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null }
if (-not (Test-Path $ProfilesDir)) { New-Item -ItemType Directory -Path $ProfilesDir -Force | Out-Null }
if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null }

# ==============================================================================
# 1. DETECT PREVIOUS OFFICIAL CLAUDE CODE INSTALLATION
# (installed via 'irm https://claude.ai/install.ps1 | iex', npm, or install.sh)
# ==============================================================================
Write-Host "`n[1/7] Checking for existing official Claude Code installations..." -ForegroundColor Cyan

$OfficialLocations = @(
    (Join-Path $env:LOCALAPPDATA "Programs\claude\claude.exe"),
    (Join-Path $HOME ".local\bin\claude.exe"),
    (Join-Path $HOME ".local\bin\claude.real.exe"),
    (Join-Path $ClaudeDir "bin\claude.exe"),
    (Join-Path $env:APPDATA "npm\claude.cmd"),
    (Join-Path $env:APPDATA "npm\claude")
)

$OfficialFound = @()
foreach ($loc in $OfficialLocations) {
    if (Test-Path $loc) {
        $OfficialFound += $loc
    }
}

$cmdClaude = Get-Command "claude.exe" -ErrorAction SilentlyContinue
if ($cmdClaude -and ($OfficialLocations -notcontains $cmdClaude.Source)) {
    $OfficialFound += $cmdClaude.Source
}

if ($OfficialFound.Count -gt 0) {
    Write-Host "  ✓ Detected existing Claude Code installation at:" -ForegroundColor Green
    foreach ($f in $OfficialFound) {
        Write-Host "    • $f" -ForegroundColor DarkCyan
    }
} else {
    Write-Host "  ℹ No existing official installation detected in standard directories." -ForegroundColor Gray
}

# ==============================================================================
# 2. COMPREHENSIVE SAFE BACKUP & DATA STAGING
# Safeguard .claude.json (OAuth/login), projects, conversation history & configs
# ==============================================================================
Write-Host "`n[2/7] Creating safe backup and staging core user data..." -ForegroundColor Cyan

$BackupZip = Join-Path $BackupDir "claude-backup-$Timestamp.zip"
$StagingDir = Join-Path $BackupDir "staged_user_data_$Timestamp"
if (-not (Test-Path $StagingDir)) { New-Item -ItemType Directory -Path $StagingDir -Force | Out-Null }

$UserClaudeJson = Join-Path $HOME ".claude.json"
$BackupTargets = @()

if (Test-Path $UserClaudeJson) {
    $BackupTargets += $UserClaudeJson
    Copy-Item -Path $UserClaudeJson -Destination (Join-Path $StagingDir ".claude.json") -Force
    Write-Host "  ✓ Staged authentication & account credentials (.claude.json)" -ForegroundColor Green
}

if (Test-Path (Join-Path $ClaudeDir "projects")) {
    Copy-Item -Path (Join-Path $ClaudeDir "projects") -Destination (Join-Path $StagingDir "projects") -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Staged user project memory & conversation history" -ForegroundColor Green
}

if (Test-Path (Join-Path $ClaudeDir "file-history")) {
    Copy-Item -Path (Join-Path $ClaudeDir "file-history") -Destination (Join-Path $StagingDir "file-history") -Recurse -Force -ErrorAction SilentlyContinue
}

if (Test-Path (Join-Path $ClaudeDir "history.jsonl")) {
    Copy-Item -Path (Join-Path $ClaudeDir "history.jsonl") -Destination (Join-Path $StagingDir "history.jsonl") -Force -ErrorAction SilentlyContinue
}

if (Test-Path (Join-Path $ClaudeDir "config.json")) {
    Copy-Item -Path (Join-Path $ClaudeDir "config.json") -Destination (Join-Path $StagingDir "config.json") -Force -ErrorAction SilentlyContinue
}

if (Test-Path $ClaudeDir) { $BackupTargets += $ClaudeDir }
if (Test-Path $ProfilesDir) { $BackupTargets += $ProfilesDir }

if ($BackupTargets.Count -gt 0) {
    try {
        Compress-Archive -Path $BackupTargets -DestinationPath $BackupZip -Force -ErrorAction SilentlyContinue
        Copy-Item -Path $BackupZip -Destination (Join-Path $BackupDir "latest.zip") -Force -ErrorAction SilentlyContinue
        $bSize = (Get-Item $BackupZip).Length / 1MB
        Write-Host ("  ✓ Created full pre-installation backup: {0:N2} MB" -f $bSize) -ForegroundColor Green
        
        # Keep last 5 backups
        Get-ChildItem -Path $BackupDir -Filter "claude-backup-*.zip" | Sort-Object CreationTime -Descending | Select-Object -Skip 5 | Remove-Item -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Host "  ⚠ Archive compression note: Staging directory safely preserved on disk." -ForegroundColor Yellow
    }
}

# ==============================================================================
# 3. PRESERVE OFFICIAL CLAUDE BINARY AS claude.real.exe
# ==============================================================================
Write-Host "`n[3/7] Preserving underlying official Claude engine..." -ForegroundColor Cyan

$RealClaudeTarget = Join-Path $BinDir "claude.real.exe"
$OfficialBinary = $null

foreach ($cand in $OfficialFound) {
    if ($cand.EndsWith(".exe") -and ($cand -notlike "*claude.real.exe*")) {
        $OfficialBinary = $cand
        break
    }
}

if ($OfficialBinary -and (Test-Path $OfficialBinary)) {
    try {
        Copy-Item -Path $OfficialBinary -Destination $RealClaudeTarget -Force
        Write-Host "  ✓ Preserved official binary to: $RealClaudeTarget" -ForegroundColor Green
    } catch {
        Write-Host "  ⚠ Note: Could not copy $OfficialBinary directly, checking existing claude.real.exe" -ForegroundColor Yellow
    }
}

if (-not (Test-Path $RealClaudeTarget)) {
    # No guessed CDN URLs. If we cannot find an existing official binary we stop,
    # rather than installing a wrapper that points at nothing - that is exactly how
    # the `claude` command ends up broken with no obvious cause.
    Write-Host "  ✗ No official Claude Code binary found to wrap." -ForegroundColor Red
    Write-Host "    Install Claude Code first: https://claude.ai/download" -ForegroundColor Yellow
    Write-Host "    Then re-run this installer." -ForegroundColor Yellow
    exit 1
}

# ==============================================================================
# 4. CLEAN REMOVAL OF CONFLICTING OFFICIAL INSTALLATION ARTIFACTS
# ==============================================================================
Write-Host "`n[4/7] Cleaning previous installation residue & temp artifacts..." -ForegroundColor Cyan

# Remove old installer downloads to save space
$OldDownloads = Join-Path $ClaudeDir "downloads"
if (Test-Path $OldDownloads) {
    Remove-Item -Path $OldDownloads -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Cleaned official installer download cache ($OldDownloads)" -ForegroundColor Green
}

# The official binary in %LOCALAPPDATA%\Programs\claude is LEFT IN PLACE.
#
# A previous version of this installer moved it aside to give the Cortex wrapper
# PATH priority. That breaks the official installation: its own updater, the IDE
# extensions, and any shim pointing at it all stop working, and the damage is not
# obvious until `claude` fails with a missing-file error.
#
# PATH order is the correct tool for precedence, so we only report a conflict.
$LocalAppClaude = Join-Path $env:LOCALAPPDATA "Programs\claude\claude.exe"
if ((Test-Path $LocalAppClaude) -and ($LocalAppClaude -ne $RealClaudeTarget)) {
    Write-Host "  i Official binary present at $LocalAppClaude (left untouched)." -ForegroundColor Cyan
    Write-Host "    Ensure $BinDir precedes it on PATH for the Cortex wrapper to take effect." -ForegroundColor Cyan
}

# Restore a binary a previous version of this installer moved aside.
$StaleBak = "$LocalAppClaude.bak"
if ((Test-Path $StaleBak) -and (-not (Test-Path $LocalAppClaude))) {
    try {
        Move-Item -Path $StaleBak -Destination $LocalAppClaude -Force -ErrorAction Stop
        Write-Host "  ✓ Restored official binary that an earlier install had moved aside." -ForegroundColor Green
    } catch {
        Write-Host "  ⚠ Found $StaleBak but could not restore it automatically." -ForegroundColor Yellow
    }
}

# ==============================================================================
# 5. INSTALL CLAUDE CORTEX COMPONENTS
# ==============================================================================
Write-Host "`n[5/7] Installing Claude Cortex wrappers, rules & cognitive engines..." -ForegroundColor Cyan

# Install the Python core. All real logic lives here; the shells are thin shims,
# so without this the wrappers have nothing to run and every command fails with
# "Cortex core not found".
$CoreDir = Join-Path $ClaudeDir "cortex-core"
$CoreTarget = Join-Path $CoreDir "cortex"
New-Item -ItemType Directory -Path $CoreDir -Force | Out-Null
if (Test-Path $CoreTarget) { Remove-Item -Path $CoreTarget -Recurse -Force }
Copy-Item -Path (Join-Path $ScriptDir "cortex") -Destination $CoreTarget -Recurse -Force
Write-Host "  ✓ Installed Cortex core to $CoreTarget" -ForegroundColor Green

# IDE process wrapper. Implements the extension's calling convention
# (wrapper <real-binary> [args...]); used only when a wrapper is configured.
$IdeWrapper = Join-Path $ScriptDir "bin\cortex-ide-wrapper.cmd"
if (Test-Path $IdeWrapper) {
    Copy-Item -Path $IdeWrapper -Destination (Join-Path $BinDir "cortex-ide-wrapper.cmd") -Force
}

# Install native launchers and wrappers
if (Test-Path (Join-Path $ScriptDir "bin\claude.exe")) {
    Copy-Item -Path (Join-Path $ScriptDir "bin\claude.exe") -Destination (Join-Path $BinDir "claude.exe") -Force
}
Copy-Item -Path (Join-Path $ScriptDir "bin\claude.ps1") -Destination (Join-Path $BinDir "claude.ps1") -Force
Copy-Item -Path (Join-Path $ScriptDir "bin\claude.cmd") -Destination (Join-Path $BinDir "claude.cmd") -Force

# The `cc` shortcut. Every document refers to `cc`, but Windows has no symlink
# equivalent that works reliably without elevation, so ship real shim files.
# Without these, `cc` simply does not exist on Windows.
$CcCmd = @"
@echo off
REM Claude Cortex - cc shortcut
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0claude.ps1" %*
"@
Set-Content -Path (Join-Path $BinDir "cc.cmd") -Value $CcCmd -Encoding ascii -Force

$CcPs1 = @"
# Claude Cortex - cc shortcut
& "`$PSScriptRoot\claude.ps1" @args
exit `$LASTEXITCODE
"@
Set-Content -Path (Join-Path $BinDir "cc.ps1") -Value $CcPs1 -Encoding utf8 -Force
Write-Host "  ✓ Created cc shortcut in $BinDir" -ForegroundColor Green
Write-Host "  ✓ Installed Windows executable, PowerShell, and CMD wrappers to $BinDir" -ForegroundColor Green

# Install Config, Rules, Commands, Skills & Cognitive Engines
$TargetRules = Join-Path $ClaudeDir "rules"
$TargetCommands = Join-Path $ClaudeDir "commands"
$TargetScripts = Join-Path $ClaudeDir "scripts"
$TargetSkills = Join-Path $ClaudeDir "skills"

New-Item -ItemType Directory -Path $TargetRules -Force | Out-Null
New-Item -ItemType Directory -Path $TargetCommands -Force | Out-Null
New-Item -ItemType Directory -Path $TargetScripts -Force | Out-Null
New-Item -ItemType Directory -Path $TargetSkills -Force | Out-Null

Copy-Item -Path (Join-Path $ScriptDir "config\CLAUDE.md") -Destination (Join-Path $ClaudeDir "CLAUDE.md") -Force
Copy-Item -Path (Join-Path $ScriptDir "config\rules\*") -Destination $TargetRules -Recurse -Force
Copy-Item -Path (Join-Path $ScriptDir "config\commands\*") -Destination $TargetCommands -Recurse -Force
Copy-Item -Path (Join-Path $ScriptDir "scripts\*") -Destination $TargetScripts -Recurse -Force
Copy-Item -Path (Join-Path $ScriptDir "skills\*") -Destination $TargetSkills -Recurse -Force
Write-Host "  ✓ Installed Core Cognition rules, Memory Palace, Dream Simulator & Skills" -ForegroundColor Green

# Merge settings.json
$TargetSettings = Join-Path $ClaudeDir "settings.json"
$SourceSettings = Join-Path $ScriptDir "config\settings.json"
if (Test-Path $TargetSettings) {
    try {
        $orig = Get-Content $TargetSettings -Raw | ConvertFrom-Json
        $newCfg = Get-Content $SourceSettings -Raw | ConvertFrom-Json
        foreach ($prop in $newCfg.PSObject.Properties) {
            $orig | Add-Member -Name $prop.Name -Value $prop.Value -MemberType NoteProperty -Force
        }
        $orig | ConvertTo-Json -Depth 5 | Set-Content $TargetSettings
    } catch {}
} else {
    Copy-Item -Path $SourceSettings -Destination $TargetSettings -Force
}

# ==============================================================================
# 6. RESTORE CORE USER DATA & RE-LINK PROFILES
# ==============================================================================
Write-Host "`n[6/7] Restoring user credentials, project context & re-linking profiles..." -ForegroundColor Cyan

# Restore authentication credentials to root .claude.json
$StagedClaudeJson = Join-Path $StagingDir ".claude.json"
if (Test-Path $StagedClaudeJson) {
    Copy-Item -Path $StagedClaudeJson -Destination $UserClaudeJson -Force
    Write-Host "  ✓ Restored user authentication state (.claude.json) - No re-login required!" -ForegroundColor Green
}

# Restore projects and conversation history
$StagedProjects = Join-Path $StagingDir "projects"
if (Test-Path $StagedProjects) {
    $TargetProjects = Join-Path $ClaudeDir "projects"
    if (-not (Test-Path $TargetProjects)) { New-Item -ItemType Directory -Path $TargetProjects -Force | Out-Null }
    Copy-Item -Path "$StagedProjects\*" -Destination $TargetProjects -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Restored conversation histories and project memory" -ForegroundColor Green
}

$StagedHistory = Join-Path $StagingDir "history.jsonl"
if (Test-Path $StagedHistory) {
    Copy-Item -Path $StagedHistory -Destination (Join-Path $ClaudeDir "history.jsonl") -Force -ErrorAction SilentlyContinue
}

$StagedFileHistory = Join-Path $StagingDir "file-history"
if (Test-Path $StagedFileHistory) {
    $TargetFileHistory = Join-Path $ClaudeDir "file-history"
    if (-not (Test-Path $TargetFileHistory)) { New-Item -ItemType Directory -Path $TargetFileHistory -Force | Out-Null }
    Copy-Item -Path "$StagedFileHistory\*" -Destination $TargetFileHistory -Recurse -Force -ErrorAction SilentlyContinue
}

# Setup Profiles
$ExistingProfiles = Get-ChildItem -Path $ProfilesDir -Directory -ErrorAction SilentlyContinue
$SharedItems = @(
    "projects", "file-history", "history.jsonl", "commands",
    "skills", "rules", "plugins", "settings.json", "mcp-configs",
    "session-env", "shell-snapshots", "ide", "palace"
)

if (-not $ExistingProfiles -or $ExistingProfiles.Count -eq 0) {
    $PrimaryProf = "main"
    $pdir = Join-Path $ProfilesDir $PrimaryProf
    New-Item -ItemType Directory -Path $pdir -Force | Out-Null
    Set-Content -Path (Join-Path $ProfilesDir "current_profile") -Value $PrimaryProf -NoNewline
    Set-Content -Path (Join-Path $pdir ".profile_mode") -Value "synced" -NoNewline

    # Copy auth state into default profile as well
    if (Test-Path $UserClaudeJson) {
        Copy-Item -Path $UserClaudeJson -Destination (Join-Path $pdir ".claude.json") -Force -ErrorAction SilentlyContinue
    }

    foreach ($item in $SharedItems) {
        $src = Join-Path $ClaudeDir $item
        $dst = Join-Path $pdir $item
        if ((Test-Path $src) -and (-not (Test-Path $dst))) {
            if (Test-Path $src -PathType Container) {
                New-Item -ItemType Junction -Path $dst -Target $src -Force -ErrorAction SilentlyContinue | Out-Null
            } else {
                Copy-Item -Path $src -Destination $dst -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Write-Host "  ✓ Initialized primary profile [$PrimaryProf] with full data sync" -ForegroundColor Green
} else {
    foreach ($profDir in $ExistingProfiles) {
        $pname = $profDir.Name
        $pmodeFile = Join-Path $profDir.FullName ".profile_mode"
        $mode = "synced"
        if (Test-Path $pmodeFile) {
            $mode = (Get-Content $pmodeFile).Trim().ToLower()
        } else {
            Set-Content -Path $pmodeFile -Value "synced" -NoNewline
        }

        if ($mode -eq "synced") {
            foreach ($item in $SharedItems) {
                $src = Join-Path $ClaudeDir $item
                $dst = Join-Path $profDir.FullName $item
                if ((Test-Path $src) -and (-not (Test-Path $dst))) {
                    if (Test-Path $src -PathType Container) {
                        New-Item -ItemType Junction -Path $dst -Target $src -Force -ErrorAction SilentlyContinue | Out-Null
                    } else {
                        Copy-Item -Path $src -Destination $dst -Force -ErrorAction SilentlyContinue
                    }
                }
            }
        }
        Write-Host "  ✓ Re-synced profile: $pname ($mode)" -ForegroundColor Green
    }
}

# ==============================================================================
# 7. CONFIGURE PATH, VS CODE EXTENSION & DESKTOP MULTI-PROFILE
# ==============================================================================
Write-Host "`n[7/7] Configuring User PATH, VS Code Extension & Claude Desktop..." -ForegroundColor Cyan

# Ensure $BinDir is at the FRONT of User PATH
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $UserPath) { $UserPath = "" }
if ($UserPath -notlike "*$BinDir*") {
    $NewPath = if ($UserPath) { "$BinDir;$UserPath" } else { $BinDir }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-Host "  ✓ Added $BinDir to the FRONT of User PATH" -ForegroundColor Green
}

# Multi-IDE Claude Code Extension Integration Wizard
$WrapperCmd = Join-Path $BinDir "claude.cmd"
$IdeConfigs = @(
    @{ Name = "VS Code"; Settings = (Join-Path $env:APPDATA "Code\User\settings.json") },
    @{ Name = "Google Antigravity"; Settings = (Join-Path $env:APPDATA "Antigravity\User\settings.json") },
    @{ Name = "Cursor"; Settings = (Join-Path $env:APPDATA "Cursor\User\settings.json") },
    @{ Name = "VSCodium"; Settings = (Join-Path $env:APPDATA "VSCodium\User\settings.json") },
    @{ Name = "Windsurf"; Settings = (Join-Path $env:APPDATA "Windsurf\User\settings.json") }
)

foreach ($ide in $IdeConfigs) {
    $sDir = Split-Path $ide.Settings -Parent
    if ((Test-Path $sDir) -or (Test-Path $ide.Settings)) {
        try {
            if (-not (Test-Path $sDir)) { New-Item -ItemType Directory -Path $sDir -Force | Out-Null }
            $cfg = if (Test-Path $ide.Settings) { Get-Content $ide.Settings -Raw | ConvertFrom-Json } else { [PSCustomObject]@{} }
            $cfg | Add-Member -Name "claudeCode.claudeProcessWrapper" -Value $WrapperCmd -MemberType NoteProperty -Force
            $cfg | ConvertTo-Json -Depth 5 | Set-Content $ide.Settings
            Write-Host "  ✓ Configured Claude Code process wrapper for $($ide.Name)" -ForegroundColor Green
        } catch {}
    }
}

# Claude Desktop App Multi-Profile & Cortex Native MCP Integration
$DesktopDirs = @(
    (Join-Path $env:APPDATA "Claude"),
    (Join-Path $env:APPDATA "Claude-profile-1"),
    (Join-Path $env:APPDATA "Claude-profile-2")
)

foreach ($profDir in (Get-ChildItem -Path $ProfilesDir -Directory -ErrorAction SilentlyContinue)) {
    $p = $profDir.Name
    $customDir = Join-Path $env:APPDATA "Claude-$p"
    if ($DesktopDirs -notcontains $customDir) { $DesktopDirs += $customDir }
}

$McpScript = Join-Path $ClaudeDir "scripts\cortex-mcp.py"

foreach ($dataDir in $DesktopDirs) {
    if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }
    $cfgFile = Join-Path $dataDir "claude_desktop_config.json"
    try {
        $desktopJson = if (Test-Path $cfgFile) { Get-Content $cfgFile -Raw | ConvertFrom-Json } else { [PSCustomObject]@{} }
        if (-not $desktopJson.mcpServers) {
            $desktopJson | Add-Member -Name "mcpServers" -Value ([PSCustomObject]@{}) -MemberType NoteProperty -Force
        }
        $cortexEntry = [PSCustomObject]@{
            command = "python"
            args = @($McpScript)
        }
        $desktopJson.mcpServers | Add-Member -Name "claude-cortex" -Value $cortexEntry -MemberType NoteProperty -Force
        $desktopJson | ConvertTo-Json -Depth 5 | Set-Content $cfgFile
        Write-Host "  ✓ Registered Cortex MCP tools in $(Split-Path $dataDir -Leaf)\claude_desktop_config.json" -ForegroundColor Green
    } catch {}
}
Write-Host "  ✓ Configured Claude Desktop multi-profile storage & native Cortex MCP tools" -ForegroundColor Green

Write-Host "`n======================================================================" -ForegroundColor Cyan
Write-Host "  ✓ Installation Complete! Claude Cortex is Ready Everywhere." -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "`nAccessible from:" -ForegroundColor Yellow
Write-Host "  • Terminal / CMD / PowerShell: claude, claude -ws, claude -vl, claude continue"
Write-Host "  • VS Code Extension:           Native extension auto-routed through wrapper"
Write-Host "  • Claude Desktop App:          claude desktop ws, claude desktop vl"
Write-Host "`nKey Commands:" -ForegroundColor Yellow
Write-Host "  claude continue        Auto-check capacity across all accounts and resume session"
Write-Host "  claude switch [prof]   Switch active default profile"
Write-Host "  claude status / quota  Display real-time capacity and rate-limit countdowns"
Write-Host "  claude -t / --turbo    High-speed output with minimal token consumption"
Write-Host "  claude palace          Inspect Cognitive Memory Palace"
Write-Host "  claude dream           Simulate counterfactual edge cases & stress-test code"
Write-Host "  claude provider        Manage fallback API keys (Anthropic, OpenRouter, Gemini)"
Write-Host "  claude docs            View comprehensive Cortex documentation"
Write-Host "======================================================================" -ForegroundColor Cyan

# Keep console window open if executed via double-click in Explorer
if ($Host.Name -eq "ConsoleHost" -and [Environment]::UserInteractive) {
    Write-Host "`nPress Enter to exit..." -ForegroundColor Gray
    [void][System.Console]::ReadLine()
}
