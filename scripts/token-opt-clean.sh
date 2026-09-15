#!/usr/bin/env bash
# Token & Storage Optimization Cleaner for Claude Code v2.0
# Safe automated pruning of temporary caches, dead sessions, and aged snapshots.
# Cross-platform compatible (Linux, macOS, BSD).
set -euo pipefail

CLAUDE_DIR="${HOME}/.claude"
LAST_CLEANUP_FILE="${CLAUDE_DIR}/.last-cleanup"
VERBOSE="false"

for arg in "$@"; do
  case "$arg" in
    -v|--verbose|true) VERBOSE="true" ;;
  esac
done

log() {
  if [ "$VERBOSE" = "true" ]; then
    echo "[token-clean] $*"
  fi
}

get_file_size() {
  local f="$1"
  local s=""
  s="$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null || true)"
  if [ -n "$s" ]; then
    echo "$s"
    return
  fi
  wc -c < "$f" 2>/dev/null | tr -d ' ' || echo 0
}

format_bytes() {
  local b="$1"
  if command -v numfmt >/dev/null 2>&1; then
    local formatted
    formatted="$(numfmt --to=iec-i --suffix=B "$b" 2>/dev/null || true)"
    if [ -n "$formatted" ]; then
      echo "$formatted"
      return
    fi
  fi
  if [ "$b" -ge 1048576 ]; then
    echo "$((b / 1048576)) MB"
  elif [ "$b" -ge 1024 ]; then
    echo "$((b / 1024)) KB"
  else
    echo "${b} B"
  fi
}

is_claude_running() {
  pgrep -f "claude.real" >/dev/null 2>&1 || pgrep -f "node.*claude" >/dev/null 2>&1
}

log "Starting Claude Code storage and token optimization cleanup..."

cleaned_files=0
cleaned_bytes=0

# 1. Prune paste-cache older than 7 days
if [ -d "${CLAUDE_DIR}/paste-cache" ]; then
  while IFS= read -r -d '' file; do
    size=$(get_file_size "$file")
    cleaned_bytes=$((cleaned_bytes + size))
    cleaned_files=$((cleaned_files + 1))
    rm -f "$file"
  done < <(find "${CLAUDE_DIR}/paste-cache" -type f -mtime +7 -print0 2>/dev/null || true)
fi

# 2. Prune shell snapshots older than 14 days
if [ -d "${CLAUDE_DIR}/shell-snapshots" ]; then
  while IFS= read -r -d '' file; do
    size=$(get_file_size "$file")
    cleaned_bytes=$((cleaned_bytes + size))
    cleaned_files=$((cleaned_files + 1))
    rm -f "$file"
  done < <(find "${CLAUDE_DIR}/shell-snapshots" -type f -mtime +14 -print0 2>/dev/null || true)
fi

# 3. Prune empty or corrupted session jsonl files (size 0) across all projects
if [ -d "${CLAUDE_DIR}/projects" ]; then
  while IFS= read -r -d '' file; do
    cleaned_files=$((cleaned_files + 1))
    rm -f "$file"
  done < <(find "${CLAUDE_DIR}/projects" -name "*.jsonl" -size 0 -print0 2>/dev/null || true)
fi

# 4. Prune stale session-env subdirectories older than 14 days (only if Claude is not active)
if [ -d "${CLAUDE_DIR}/session-env" ]; then
  if is_claude_running; then
    log "Active Claude process detected. Skipping session-env pruning to protect running session."
  else
    find "${CLAUDE_DIR}/session-env" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} + 2>/dev/null || true
  fi
fi

# Record cleanup timestamp (ISO 8601 UTC)
mkdir -p "${CLAUDE_DIR}"
date -u +"%Y-%m-%dT%H:%M:%S.000Z" > "$LAST_CLEANUP_FILE" 2>/dev/null || true

human_bytes="$(format_bytes "$cleaned_bytes")"
echo "✓ Claude Code token & storage optimization complete: removed ${cleaned_files} stale items (${human_bytes} freed)."
