#!/usr/bin/env bash
# ==============================================================================
# Claude Cortex - Uninstaller (Cortex artifacts ONLY)
#
# SAFETY CONTRACT - this script will NEVER touch:
#   * The official Claude Code binary or ~/.local/share/claude
#   * Any IDE extension (VS Code / Antigravity / Cursor / Windsurf / VSCodium)
#   * Claude Desktop or ~/.config/Claude
#   * ~/.claude.json (sign-in session, MCP servers, folder-trust decisions)
#   * Your own ~/.claude content: CLAUDE.md, agents/, skills/, projects/, history
#
# It removes only files this repository's installer created.
#
# Usage:
#   ./uninstall.sh                        # DRY RUN - prints what would be removed
#   ./uninstall.sh --yes                  # actually remove Cortex artifacts
#   ./uninstall.sh --yes --purge-profiles # also remove ~/.claude-profiles
# ==============================================================================

set -euo pipefail

# `set -u` catches an unset HOME but not an empty one; with HOME empty every
# "${HOME}/..." target below would resolve to a path under "/".
if [ -z "${HOME:-}" ] || [ ! -d "${HOME}" ]; then
    echo "error: HOME is not set to an existing directory; refusing to continue." >&2
    exit 1
fi

DRY_RUN=1
PURGE_PROFILES=0

for arg in "$@"; do
    case "$arg" in
        --yes|-y)         DRY_RUN=0 ;;
        --purge-profiles) PURGE_PROFILES=1 ;;
        --help|-h)        sed -n '2,19p' "$0"; exit 0 ;;
        *)
            echo "Unknown option: $arg" >&2
            echo "Run '$0 --help' for usage." >&2
            exit 2
            ;;
    esac
done

if [ -z "${HOME:-}" ]; then
    echo "FATAL: HOME is not set. Refusing to run." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED_DIR="${HOME}/.claude"
BIN_DIR="${HOME}/.local/bin"
PROFILES_DIR="${HOME}/.claude-profiles"
APPS_DIR="${HOME}/.local/share/applications"

REMOVED=0
SKIPPED=0

say()  { printf '%s\n' "$*"; }
note() { printf '  %s\n' "$*"; }

# Remove a path only if it exists. Honors DRY_RUN.
drop() {
    local target="$1"
    local label="${2:-$1}"
    if [ ! -e "$target" ] && [ ! -L "$target" ]; then
        return 0
    fi
    if [ "$DRY_RUN" -eq 1 ]; then
        note "would remove: ${label}"
    else
        rm -rf -- "$target"
        note "removed: ${label}"
    fi
    REMOVED=$((REMOVED + 1))
}

keep() {
    note "PRESERVED (not ours): $1"
    SKIPPED=$((SKIPPED + 1))
}

say "======================================================================"
if [ "$DRY_RUN" -eq 1 ]; then
    say "   Claude Cortex - Uninstaller  [DRY RUN - nothing will be changed]"
else
    say "   Claude Cortex - Uninstaller  [LIVE]"
fi
say "======================================================================"
say ""

# --------------------------------------------------------------------------
# 1. Cortex wrapper + shortcuts in ~/.local/bin
# --------------------------------------------------------------------------
say "[1/6] Cortex wrapper and shortcuts"

# Only remove ~/.local/bin/claude if it is OUR wrapper, never a real binary.
if [ -e "${BIN_DIR}/claude" ]; then
    if grep -qs "Claude Cortex" "${BIN_DIR}/claude" 2>/dev/null; then
        drop "${BIN_DIR}/claude" "~/.local/bin/claude (Cortex wrapper)"
    else
        keep "~/.local/bin/claude (not a Cortex wrapper - left in place)"
    fi
fi

# claude.real is a symlink we created pointing at the official binary.
# Removing the symlink never removes the official binary it points to.
if [ -L "${BIN_DIR}/claude.real" ]; then
    drop "${BIN_DIR}/claude.real" "~/.local/bin/claude.real (symlink only; target untouched)"
elif [ -e "${BIN_DIR}/claude.real" ]; then
    keep "~/.local/bin/claude.real (a real file, not our symlink)"
fi

drop "${BIN_DIR}/cc" "~/.local/bin/cc"
for tool in models palace dream research cognition provider capacity-check update; do
    drop "${BIN_DIR}/claude-${tool}" "~/.local/bin/claude-${tool}"
done

# --------------------------------------------------------------------------
# 2. Cortex payload inside ~/.claude  (user content is preserved)
# --------------------------------------------------------------------------
say ""
say "[2/6] Cortex payload in ~/.claude"

for f in cortex-prompt-hook.py cortex-pretool-hook.py cortex-precompact-hook.py \
         cortex-gateway.py cortex-mcp.py gemini-proxy.py \
         claude-capacity-check.py claude-cognition.py claude-dream.py \
         claude-models.py claude-palace.py claude-provider.py \
         claude-research.py claude-update.py \
         token-opt-clean.sh token-opt-clean.ps1; do
    drop "${SHARED_DIR}/scripts/${f}" "~/.claude/scripts/${f}"
done

# Slash commands: remove only files this repo ships, matched by name.
if [ -d "${SHARED_DIR}/commands" ]; then
    if [ -d "${REPO_DIR}/config/commands" ]; then
        for src in "${REPO_DIR}/config/commands"/*.md; do
            [ -e "$src" ] || continue
            drop "${SHARED_DIR}/commands/$(basename "$src")" "~/.claude/commands/$(basename "$src")"
        done
    else
        keep "~/.claude/commands (repo command list unavailable - left intact)"
    fi
fi

# Rules: same approach, matched by name.
if [ -d "${SHARED_DIR}/rules" ]; then
    if [ -d "${REPO_DIR}/config/rules" ]; then
        for src in "${REPO_DIR}/config/rules"/*.md; do
            [ -e "$src" ] || continue
            drop "${SHARED_DIR}/rules/$(basename "$src")" "~/.claude/rules/$(basename "$src")"
        done
    else
        keep "~/.claude/rules (repo rule list unavailable - left intact)"
    fi
fi

drop "${SHARED_DIR}/cortex-core"     "~/.claude/cortex-core (Cortex Python core)"
drop "${SHARED_DIR}/palace"          "~/.claude/palace"
drop "${SHARED_DIR}/tests"           "~/.claude/tests"
drop "${SHARED_DIR}/providers.json"  "~/.claude/providers.json"
drop "${SHARED_DIR}/.last-cleanup"   "~/.claude/.last-cleanup"

keep "~/.claude.json (sign-in session, MCP servers, folder trust)"
keep "~/.claude/CLAUDE.md, agents/, skills/, projects/, history.jsonl"
keep "~/.local/share/claude (official Claude Code binaries)"
keep "IDE extensions (VS Code / Antigravity / Cursor / Windsurf)"
keep "~/.config/Claude (Claude Desktop)"

# --------------------------------------------------------------------------
# 3. Hooks written into ~/.claude/settings.json
# --------------------------------------------------------------------------
say ""
say "[3/6] Cortex hooks in ~/.claude/settings.json"
SETTINGS_FILE="${SHARED_DIR}/settings.json"
if [ -f "$SETTINGS_FILE" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
        note "would strip Cortex hook entries (settings.json otherwise untouched)"
    else
        cp -p "$SETTINGS_FILE" "${SETTINGS_FILE}.cortex-uninstall.bak"
        python3 "${REPO_DIR}/scripts/cortex-strip-hooks.py" "$SETTINGS_FILE" || \
            note "! hook strip skipped (helper unavailable); settings.json untouched"
    fi
else
    note "no settings.json present"
fi

# --------------------------------------------------------------------------
# 4. Shell completions
# --------------------------------------------------------------------------
say ""
say "[4/6] Shell completions"
drop "${HOME}/.local/share/bash-completion/completions/claude" "bash completion: claude"
drop "${HOME}/.local/share/bash-completion/completions/cc"     "bash completion: cc"
drop "${HOME}/.local/share/zsh/site-functions/_claude"         "zsh completion: _claude"
drop "${HOME}/.local/share/zsh/site-functions/_cc"             "zsh completion: _cc"

# --------------------------------------------------------------------------
# 5. Desktop launcher entries created per profile
# --------------------------------------------------------------------------
say ""
say "[5/6] Desktop launcher entries"
if [ -d "$APPS_DIR" ]; then
    for f in "${APPS_DIR}"/claude-*.desktop; do
        [ -e "$f" ] || continue
        if grep -qs "Claude Cortex" "$f" 2>/dev/null; then
            drop "$f" "$(basename "$f")"
        else
            keep "$(basename "$f") (not created by Cortex)"
        fi
    done

    # Earlier versions of this script left behind a NoDisplay/Hidden .desktop that
    # masked Claude Desktop from the application launcher. Remove that masking file
    # so the launcher entry reappears.
    MASK="${APPS_DIR}/claude-desktop-unofficial.desktop"
    if [ -f "$MASK" ] && grep -qs "NoDisplay=true" "$MASK" 2>/dev/null; then
        drop "$MASK" "stale launcher mask (restores Claude Desktop visibility)"
    fi

    if [ "$DRY_RUN" -eq 0 ] && command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
    fi
fi

# --------------------------------------------------------------------------
# 6. Profiles (opt-in only - these hold your logins)
# --------------------------------------------------------------------------
say ""
say "[6/6] Profiles"
if [ "$PURGE_PROFILES" -eq 1 ]; then
    drop "$PROFILES_DIR" "~/.claude-profiles (ALL profile logins)"
else
    keep "~/.claude-profiles (use --purge-profiles to remove)"
fi

# --------------------------------------------------------------------------
say ""
say "======================================================================"
if [ "$DRY_RUN" -eq 1 ]; then
    say "  DRY RUN complete - ${REMOVED} item(s) would be removed, ${SKIPPED} preserved."
    say "  Re-run with --yes to apply."
else
    say "  Uninstall complete - ${REMOVED} item(s) removed, ${SKIPPED} preserved."
fi
say "======================================================================"

if [ "$DRY_RUN" -eq 0 ] && [ ! -e "${BIN_DIR}/claude" ]; then
    say ""
    say "  NOTE: ~/.local/bin/claude was the Cortex wrapper and has been removed."
    say "  If the official Claude Code is no longer on your PATH, restore it from"
    say "  ~/.local/share/claude/versions/ or reinstall from https://claude.ai/download"
fi
