#!/usr/bin/env bash
# ==============================================================================
# Claude Cortex — Complete Uninstaller
# Removes all Claude Code, Cortex, Desktop, VS Code extension, and data.
# ==============================================================================

set -euo pipefail

echo "======================================================================"
echo "        🧹 Claude Cortex — Complete Uninstaller"
echo "======================================================================"
echo ""
echo "This will remove:"
echo "  • Claude Code CLI binary and Cortex wrapper"
echo "  • Claude Code VS Code extensions"
echo "  • Claude Desktop application (if installed)"
echo "  • All Claude data (~/.claude, ~/.claude-profiles, ~/.claude.json)"
echo "  • Shell completions"
echo "  • Convenience symlinks"
echo ""
read -r -p "Are you sure? Type YES to confirm: " confirm
if [ "$confirm" != "YES" ]; then
    echo "Aborted."
    exit 0
fi

echo ""

# --------------------------------------------------------------------------
# 1. Remove Claude Code CLI binaries and symlinks
# --------------------------------------------------------------------------
echo "[1/7] Removing CLI binaries and symlinks..."
rm -f "${HOME}/.local/bin/claude"
rm -f "${HOME}/.local/bin/claude.real"
rm -f "${HOME}/.local/bin/cc"
rm -f "${HOME}/.local/bin/claude-models"
rm -f "${HOME}/.local/bin/claude-palace"
rm -f "${HOME}/.local/bin/claude-dream"
rm -f "${HOME}/.local/bin/claude-research"
rm -f "${HOME}/.local/bin/claude-cognition"
rm -f "${HOME}/.local/bin/claude-provider"
rm -f "${HOME}/.local/bin/claude-capacity-check"
rm -f "${HOME}/.local/bin/claude-update"
echo "  ✓ Removed CLI binaries"

# --------------------------------------------------------------------------
# 2. Remove Claude Code versioned binaries
# --------------------------------------------------------------------------
echo "[2/7] Removing Claude Code versioned binaries..."
rm -rf "${HOME}/.local/share/claude"
echo "  ✓ Removed ${HOME}/.local/share/claude"

# --------------------------------------------------------------------------
# 3. Remove VS Code extensions
# --------------------------------------------------------------------------
echo "[3/7] Removing VS Code Claude Code extensions..."
rm -rf "${HOME}/.vscode/extensions/anthropic.claude-code-"*
echo "  ✓ Removed VS Code Claude Code extensions"

# --------------------------------------------------------------------------
# 4. Remove Claude Desktop
# --------------------------------------------------------------------------
echo "[4/7] Removing Claude Desktop..."
if command -v claude-desktop-unofficial >/dev/null 2>&1; then
    if command -v npm >/dev/null 2>&1; then
        npm uninstall -g claude-desktop-unofficial 2>/dev/null || true
    fi
    if command -v pip3 >/dev/null 2>&1; then
        pip3 uninstall -y claude-desktop-unofficial 2>/dev/null || true
    fi
fi
rm -rf "${HOME}/.config/claude-desktop"*
rm -rf "${HOME}/.config/Claude"
echo "  ✓ Removed Claude Desktop"

# --------------------------------------------------------------------------
# 5. Remove all Claude data
# --------------------------------------------------------------------------
echo "[5/7] Removing Claude data directories..."
rm -rf "${HOME}/.claude"
rm -rf "${HOME}/.claude-profiles"
rm -f  "${HOME}/.claude.json"
echo "  ✓ Removed ~/.claude, ~/.claude-profiles, ~/.claude.json"

# --------------------------------------------------------------------------
# 6. Remove shell completions
# --------------------------------------------------------------------------
echo "[6/7] Removing shell completions..."
rm -f "${HOME}/.local/share/bash-completion/completions/claude"
rm -f "${HOME}/.local/share/bash-completion/completions/cc"
rm -f "${HOME}/.local/share/zsh/site-functions/_claude"
rm -f "${HOME}/.local/share/zsh/site-functions/_cc"
echo "  ✓ Removed shell completions"

# --------------------------------------------------------------------------
# 7. Remove VS Code user settings for Claude
# --------------------------------------------------------------------------
echo "[7/7] Cleaning VS Code user settings..."
VSCODE_SETTINGS="${HOME}/.config/Code/User/settings.json"
if [ -f "$VSCODE_SETTINGS" ]; then
    # Remove claudeCode entries from VS Code settings
    python3 -c "
import json
try:
    with open('$VSCODE_SETTINGS') as f:
        d = json.load(f)
    keys_to_remove = [k for k in d if k.startswith('claudeCode')]
    for k in keys_to_remove:
        del d[k]
    with open('$VSCODE_SETTINGS', 'w') as f:
        json.dump(d, f, indent=4)
    if keys_to_remove:
        print(f'  ✓ Removed {len(keys_to_remove)} claudeCode settings from VS Code')
    else:
        print('  ✓ No claudeCode settings found in VS Code')
except Exception as e:
    print(f'  ⚠ Could not clean VS Code settings: {e}')
" 2>/dev/null || echo "  ⚠ VS Code settings cleanup skipped"
fi

echo ""
echo "======================================================================"
echo "  ✅ Complete uninstall finished!"
echo "======================================================================"
echo ""
echo "  To reinstall, extract the Cortex zip and run:"
echo "    chmod +x install.sh && ./install.sh"
echo ""
echo "  Note: You will need to reinstall Claude Code CLI first:"
echo "    npm install -g @anthropic-ai/claude-code"
echo "======================================================================"
