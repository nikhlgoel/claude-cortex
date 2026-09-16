#!/usr/bin/env bash
# ==============================================================================
# Claude Cortex v1.2.0 — One-Shot Installer
# Installs the Cortex wrapper, lifecycle hooks, slash commands, Memory Palace,
# shell completions, and all scripts onto a fresh machine.
#
# Prerequisites:
#   • Claude Code CLI already installed (npm i -g @anthropic-ai/claude-code
#     or binary from https://claude.ai/download)
#   • Python 3.10+
#   • bash or zsh shell
#
# Usage:
#   chmod +x install.sh && ./install.sh
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED_DIR="${HOME}/.claude"
BIN_DIR="${HOME}/.local/bin"
PROFILES_DIR="${HOME}/.claude-profiles"

# ==============================================================================
# SANDBOX GUARD
#
# This installer modifies a live Claude Code installation: it replaces the
# `claude` command on PATH, writes lifecycle hooks into ~/.claude/settings.json,
# and installs rules that change model behavior. Running it by accident on a
# working machine is disruptive and not trivially reversible.
#
# It therefore refuses to run unless one of these is true:
#   * CORTEX_SANDBOX=1   - running inside a container or throwaway environment
#   * --yes / -y         - operator has explicitly opted in
#   * an interactive terminal, where it asks for confirmation
# ==============================================================================
ASSUME_YES=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) ASSUME_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
    esac
done
DRY_RUN="${DRY_RUN:-0}"

if [ "${CORTEX_SANDBOX:-0}" != "1" ] && [ "$ASSUME_YES" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    echo "======================================================================"
    echo "  Claude Cortex installer - CONFIRMATION REQUIRED"
    echo "======================================================================"
    echo "  This will modify your live Claude Code installation:"
    echo "    * replace ${BIN_DIR}/claude with the Cortex wrapper"
    echo "    * write lifecycle hooks into ${SHARED_DIR}/settings.json"
    echo "    * install rules into ${SHARED_DIR}/rules/ that change model behavior"
    echo ""
    echo "  Set CORTEX_SANDBOX=1 to run in a container, or pass --dry-run first."
    echo "======================================================================"
    if [ -t 0 ]; then
        printf "  Type INSTALL to continue: "
        read -r _confirm
        # Exit code 3 = "safety guard stopped this run" (see install.py).
        if [ "$_confirm" != "INSTALL" ]; then
            echo "  Aborted. Nothing was changed."
            exit 3
        fi
    else
        echo "  Refusing to run non-interactively without --yes or CORTEX_SANDBOX=1."
        exit 3
    fi
fi

if [ "$DRY_RUN" -eq 1 ]; then
    echo "[DRY RUN] Would install Claude Cortex with:"
    echo "  wrapper   -> ${BIN_DIR}/claude"
    echo "  scripts   -> ${SHARED_DIR}/scripts/"
    echo "  commands  -> ${SHARED_DIR}/commands/"
    echo "  rules     -> ${SHARED_DIR}/rules/"
    echo "  settings  -> ${SHARED_DIR}/settings.json (hooks)"
    echo "  profiles  -> ${PROFILES_DIR}/"
    echo "[DRY RUN] No changes made."
    exit 0
fi

echo "======================================================================"
echo "        ⚡ Claude Cortex v1.2.0 — Installer"
echo "======================================================================"

# --------------------------------------------------------------------------
# 1. Locate the real Claude Code binary
# --------------------------------------------------------------------------
REAL_CLAUDE=""
for candidate in \
    "${BIN_DIR}/claude.real" \
    "$(command -v claude 2>/dev/null || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        REAL_CLAUDE="$candidate"
        break
    fi
done

# Check npm global installs and versioned directories
if [ -z "$REAL_CLAUDE" ]; then
    LATEST_VER=$(ls -v "${HOME}/.local/share/claude/versions/" 2>/dev/null | tail -n 1 || true)
    if [ -n "$LATEST_VER" ] && [ -x "${HOME}/.local/share/claude/versions/${LATEST_VER}" ]; then
        REAL_CLAUDE="${HOME}/.local/share/claude/versions/${LATEST_VER}"
    fi
fi

# Deliberately NOT auto-running `npm install -g`. Installing a global package is
# a system-wide change the operator did not ask this script for, and it can shadow
# or conflict with an existing native install. We report and stop instead.

if [ -z "$REAL_CLAUDE" ]; then
    echo ""
    echo "⚠  Claude Code CLI binary not found."
    echo "   Please install it first:"
    echo "     npm install -g @anthropic-ai/claude-code"
    echo "   Or download from: https://claude.ai/download"
    echo ""
    echo "   After installing, re-run this script."
    exit 1
fi

echo "✓ Found Claude Code binary: ${REAL_CLAUDE}"

# --------------------------------------------------------------------------
# 2. Create directory structure
# --------------------------------------------------------------------------
mkdir -p "${SHARED_DIR}/scripts"
mkdir -p "${SHARED_DIR}/commands"
mkdir -p "${SHARED_DIR}/rules"
mkdir -p "${SHARED_DIR}/palace/rooms"
mkdir -p "${SHARED_DIR}/tests"
mkdir -p "${BIN_DIR}"
mkdir -p "${PROFILES_DIR}"

echo "✓ Created directory structure"

# --------------------------------------------------------------------------
# 3. Save reference to the real binary (backup original if our wrapper exists)
# --------------------------------------------------------------------------
if [ -x "${BIN_DIR}/claude" ] && [ ! -L "${BIN_DIR}/claude.real" ]; then
    # The current claude in PATH is the real binary, not our wrapper
    if ! grep -q "Claude Cortex" "${BIN_DIR}/claude" 2>/dev/null; then
        ln -sf "$REAL_CLAUDE" "${BIN_DIR}/claude.real"
        echo "✓ Saved real binary reference: ${BIN_DIR}/claude.real → ${REAL_CLAUDE}"
    fi
elif [ ! -e "${BIN_DIR}/claude.real" ]; then
    ln -sf "$REAL_CLAUDE" "${BIN_DIR}/claude.real"
    echo "✓ Saved real binary reference: ${BIN_DIR}/claude.real → ${REAL_CLAUDE}"
fi

# --------------------------------------------------------------------------
# 4. Install scripts
# --------------------------------------------------------------------------
cp -r "${SCRIPT_DIR}/scripts/"*.py "${SHARED_DIR}/scripts/" 2>/dev/null || true
cp -r "${SCRIPT_DIR}/scripts/"*.sh "${SHARED_DIR}/scripts/" 2>/dev/null || true
chmod +x "${SHARED_DIR}/scripts/"* 2>/dev/null || true
echo "✓ Installed scripts to ${SHARED_DIR}/scripts/"

# --------------------------------------------------------------------------
# 5. Install slash commands
# --------------------------------------------------------------------------
cp -r "${SCRIPT_DIR}/config/commands/"*.md "${SHARED_DIR}/commands/"
echo "✓ Installed $(ls "${SHARED_DIR}/commands/"*.md 2>/dev/null | wc -l) slash command definitions"

# --------------------------------------------------------------------------
# 6. Install rules
# --------------------------------------------------------------------------
if [ -d "${SCRIPT_DIR}/config/rules" ]; then
    cp -r "${SCRIPT_DIR}/config/rules/"*.md "${SHARED_DIR}/rules/" 2>/dev/null || true
    echo "✓ Installed cognitive rules"
fi

# --------------------------------------------------------------------------
# 7. Install wrapper binary
# --------------------------------------------------------------------------
# Install the Python core. All real logic lives here; the shells are shims.
CORE_DIR="${SHARED_DIR}/cortex-core"
mkdir -p "${CORE_DIR}"
rm -rf "${CORE_DIR}/cortex"
cp -r "${SCRIPT_DIR}/cortex" "${CORE_DIR}/cortex"
echo "✓ Installed Cortex core → ${CORE_DIR}/cortex"

# IDE process wrappers. These implement the extension's calling convention
# (wrapper <real-binary> [args...]) and are only used when a wrapper is
# explicitly configured; profile selection normally uses environmentVariables.
cp "${SCRIPT_DIR}/bin/cortex-ide-wrapper.sh" "${BIN_DIR}/cortex-ide-wrapper.sh"
chmod +x "${BIN_DIR}/cortex-ide-wrapper.sh"
if [ -f "${SCRIPT_DIR}/bin/cortex-ide-wrapper.cmd" ]; then
    cp "${SCRIPT_DIR}/bin/cortex-ide-wrapper.cmd" "${BIN_DIR}/cortex-ide-wrapper.cmd"
fi

cp "${SCRIPT_DIR}/bin/claude" "${BIN_DIR}/claude"
chmod +x "${BIN_DIR}/claude"
echo "✓ Installed Cortex wrapper → ${BIN_DIR}/claude"

# Create cc symlink
ln -sf "${BIN_DIR}/claude" "${BIN_DIR}/cc"
echo "✓ Created cc shortcut → ${BIN_DIR}/cc"

# Create convenience symlinks for sub-tools
for tool in models palace dream research cognition provider capacity-check update; do
    script="${SHARED_DIR}/scripts/claude-${tool}.py"
    link="${BIN_DIR}/claude-${tool}"
    if [ -f "$script" ]; then
        ln -sf "$script" "$link"
    fi
done
echo "✓ Created tool symlinks"

# --------------------------------------------------------------------------
# 8. Install tests
# --------------------------------------------------------------------------
cp -r "${SCRIPT_DIR}/tests/"*.py "${SHARED_DIR}/tests/" 2>/dev/null || true
echo "✓ Installed test suite to ${SHARED_DIR}/tests/"

# --------------------------------------------------------------------------
# 9. Configure settings.json with lifecycle hooks
# --------------------------------------------------------------------------
SETTINGS_FILE="${SHARED_DIR}/settings.json"
if [ ! -f "$SETTINGS_FILE" ]; then
    # Copied from config/settings.json rather than duplicated inline: an
    # embedded copy drifts from the real one, which is how the invalid
    # autoCompactWindow survived as long as it did.
    cp "${SCRIPT_DIR}/config/settings.json" "$SETTINGS_FILE"
    echo "✓ Created settings.json with lifecycle hooks"
else
    echo "✓ Existing settings.json preserved (hooks may need manual merge)"
fi

# --------------------------------------------------------------------------
# 10. Initialize Memory Palace
# --------------------------------------------------------------------------
if [ ! -f "${SHARED_DIR}/palace/index.json" ]; then
    python3 "${SHARED_DIR}/scripts/claude-palace.py" init 2>/dev/null || true
    echo "✓ Initialized Memory Palace"
else
    echo "✓ Existing Memory Palace preserved"
fi

# --------------------------------------------------------------------------
# 11. Shell completions
# --------------------------------------------------------------------------
COMP_DIR="${SCRIPT_DIR}/config/completions"
if [ -d "$COMP_DIR" ]; then
    # Bash completions
    BASH_COMP_DIR="${HOME}/.local/share/bash-completion/completions"
    mkdir -p "$BASH_COMP_DIR"
    if [ -f "${COMP_DIR}/claude.bash" ]; then
        cp "${COMP_DIR}/claude.bash" "${BASH_COMP_DIR}/claude"
        cp "${COMP_DIR}/claude.bash" "${BASH_COMP_DIR}/cc"
        echo "✓ Installed bash completions"
    fi

    # Zsh completions
    ZSH_COMP_DIR="${HOME}/.local/share/zsh/site-functions"
    mkdir -p "$ZSH_COMP_DIR"
    if [ -f "${COMP_DIR}/claude.zsh" ]; then
        cp "${COMP_DIR}/claude.zsh" "${ZSH_COMP_DIR}/_claude"
        cp "${COMP_DIR}/claude.zsh" "${ZSH_COMP_DIR}/_cc"
        echo "✓ Installed zsh completions"
    fi
fi

# --------------------------------------------------------------------------
# 12. Setup Profiles & Application Launcher Entries
# --------------------------------------------------------------------------
PROFILES_TO_ADD=()

for arg in "$@"; do
    case "$arg" in
        --profiles=*)
            IFS=',' read -ra ADDR <<< "${arg#*=}"
            for p in "${ADDR[@]}"; do PROFILES_TO_ADD+=("$p"); done
            ;;
        --profiles|-p)
            ;;
        *)
            if [[ "$arg" != -* ]]; then
                IFS=',' read -ra ADDR <<< "$arg"
                for p in "${ADDR[@]}"; do PROFILES_TO_ADD+=("$p"); done
            fi
            ;;
    esac
done

if [ ${#PROFILES_TO_ADD[@]} -gt 0 ]; then
    echo ""
    echo "Setting up initial profiles and application launcher entries..."
    first=true
    for prof in "${PROFILES_TO_ADD[@]}"; do
        prof_clean=$(echo "$prof" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')
        if [ -n "$prof_clean" ]; then
            if [ "$first" = true ]; then
                "${BIN_DIR}/claude" profile add "$prof_clean" synced yes 2>/dev/null || true
                first=false
            else
                "${BIN_DIR}/claude" profile add "$prof_clean" synced no 2>/dev/null || true
            fi
        fi
    done
fi

# --------------------------------------------------------------------------
# 13. PATH check
# --------------------------------------------------------------------------
if ! echo "$PATH" | grep -q "${BIN_DIR}"; then
    echo ""
    echo "⚠  ${BIN_DIR} is not in your PATH."
    echo "   Add this to your ~/.bashrc or ~/.zshrc:"
    echo "     export PATH=\"\${HOME}/.local/bin:\${PATH}\""
fi

echo ""
echo "======================================================================"
echo "  ✅ Claude Cortex v1.2.0 installed successfully!"
echo "======================================================================"
echo ""
echo "  Quick Start:"
echo "    cc                     Launch Claude Code with Cortex enhancements"
echo "    cc menu                Interactive command palette"
echo "    cc status              Multi-account capacity dashboard"
echo "    cc model list          Browse available models"
echo "    cc test                Run comprehensive test suite"
echo "    cc docs                Full documentation"
echo ""
echo "  First-Time Setup:"
echo "    cc profile add         Add your first account"
echo "    cc login               Authenticate via browser"
echo ""
echo "======================================================================"
