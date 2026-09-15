# Token & Storage Optimization Cleaner for Windows v2.0
# Safe automated pruning with running process detection
param(
    [switch]$Verbose = $false
)

$ClaudeDir = Join-Path $HOME ".claude"
$LastCleanupFile = Join-Path $ClaudeDir ".last-cleanup"

if ($Verbose) { Write-Host "[token-clean] Starting Claude Code storage cleanup..." -ForegroundColor Cyan }

$CleanedFiles = 0
$CleanedBytes = 0

# Check if Claude or Node running Claude is currently active
$RunningClaude = Get-Process -Name "claude", "node" -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowTitle -like "*claude*" -or $_.CommandLine -like "*claude*"
}

# 1. Paste cache (> 7 days)
$PasteCache = Join-Path $ClaudeDir "paste-cache"
if (Test-Path $PasteCache) {
    Get-ChildItem -Path $PasteCache -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | ForEach-Object {
        $CleanedBytes += $_.Length
        $CleanedFiles++
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

# 2. Shell snapshots (> 14 days)
$Snapshots = Join-Path $ClaudeDir "shell-snapshots"
if (Test-Path $Snapshots) {
    Get-ChildItem -Path $Snapshots -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | ForEach-Object {
        $CleanedBytes += $_.Length
        $CleanedFiles++
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

# 3. Empty session transcripts
$Projects = Join-Path $ClaudeDir "projects"
if (Test-Path $Projects) {
    Get-ChildItem -Path $Projects -Filter "*.jsonl" -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Length -eq 0 } | ForEach-Object {
        $CleanedFiles++
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}

# 4. Session env (> 14 days) only if Claude is not actively running
$SessionEnv = Join-Path $ClaudeDir "session-env"
if ((Test-Path $SessionEnv) -and (-not $RunningClaude)) {
    Get-ChildItem -Path $SessionEnv -Directory -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $ClaudeDir)) {
    New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
}

Set-Content -Path $LastCleanupFile -Value ((Get-Date).ToUniversalTime().ToString("o")) -Force

$FreedStr = if ($CleanedBytes -gt 1MB) {
    "$([math]::Round($CleanedBytes / 1MB, 2)) MB"
} elseif ($CleanedBytes -gt 1KB) {
    "$([math]::Round($CleanedBytes / 1KB, 1)) KB"
} else {
    "$CleanedBytes B"
}

Write-Host "✓ Claude Code cleanup complete: removed $CleanedFiles stale items ($FreedStr freed)." -ForegroundColor Green
