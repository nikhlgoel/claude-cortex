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

if [ -z "$REAL_CLAUDE" ]; then
    if command -v npm >/dev/null 2>&1; then
        echo "Claude Code CLI binary not found. Installing via npm..."
        npm install -g @anthropic-ai/claude-code 2>&1 || true
        REAL_CLAUDE="$(command -v claude 2>/dev/null || true)"
    fi
fi

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
    cat > "$SETTINGS_FILE" << 'SETTINGS_EOF'
{
  "includeCoAuthoredBy": false,
  "enableWorkflows": true,
  "theme": "dark",
  "autoCompactEnabled": true,
  "autoCompactWindow": 85000,
  "cleanupPeriodDays": 7,
  "bashOutputMaxChars": 6000,
  "taskOutputMaxChars": 8000,
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/cortex-pretool-hook.py"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/cortex-prompt-hook.py"
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/scripts/cortex-precompact-hook.py"
          }
        ]
      }
    ]
  }
}
SETTINGS_EOF
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
