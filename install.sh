#!/usr/bin/env bash
# ==============================================================================
# Claude Cortex: 1-Click Installer (Linux & macOS)
# Multi-Account Manager, Capacity Auto-Failover, Cognitive Memory Palace,
# Neuroscience Dream Simulation, Models & Reasoning Control, API Fallback Proxy
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
CLAUDE_DIR="${HOME}/.claude"
PROFILES_DIR="${HOME}/.claude-profiles"
BACKUP_DIR="${HOME}/.claude-backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

echo "======================================================================"
echo "          Installing Claude Cortex (Linux / macOS)"
echo "======================================================================"

# 0. Detect OS & Platform Architecture
OS_TYPE="$(uname -s)"
ARCH_TYPE="$(uname -m)"
echo "Platform: ${OS_TYPE} (${ARCH_TYPE})"

# 1. Automated Safe Pre-Installation Backup
mkdir -p "${BACKUP_DIR}"
BACKUP_FILE="${BACKUP_DIR}/claude-backup-${TIMESTAMP}.tar.gz"
BACKUP_TARGETS=()

[ -d "${CLAUDE_DIR}" ] && BACKUP_TARGETS+=("${CLAUDE_DIR}")
[ -d "${PROFILES_DIR}" ] && BACKUP_TARGETS+=("${PROFILES_DIR}")
[ -f "${HOME}/.claude.json" ] && BACKUP_TARGETS+=("${HOME}/.claude.json")
[ -f "${BIN_DIR}/claude" ] && BACKUP_TARGETS+=("${BIN_DIR}/claude")

if [ ${#BACKUP_TARGETS[@]} -gt 0 ]; then
  echo "Backing up existing Claude Code data to safe archive..."
  tar -czf "${BACKUP_FILE}" \
    --exclude="*.sock" \
    --exclude="*.pid" \
    --exclude="*node_modules*" \
    "${BACKUP_TARGETS[@]}" 2>/dev/null || true

  if [ -f "${BACKUP_FILE}" ] && tar -tzf "${BACKUP_FILE}" >/dev/null 2>&1; then
    BACKUP_SIZE="$(du -h "${BACKUP_FILE}" | cut -f1)"
    ln -sf "${BACKUP_FILE}" "${BACKUP_DIR}/latest.tar.gz"
    echo "✓ Safe pre-installation backup created: ${BACKUP_FILE} (${BACKUP_SIZE})"
  else
    echo "⚠ Backup verification returned non-zero code, continuing safely."
  fi

  # Automatic backup retention: keep last 5 archives to preserve disk space
  (
    cd "${BACKUP_DIR}" 2>/dev/null || exit 0
    ls -1t claude-backup-*.tar.gz 2>/dev/null | tail -n +6 | while read -r old_bk; do
      [ -f "$old_bk" ] && rm -f "$old_bk"
    done
  ) || true
fi

# 2. Verify / Install Official Claude Code
if ! command -v claude >/dev/null 2>&1 && [ ! -f "${BIN_DIR}/claude" ] && [ ! -f "${BIN_DIR}/claude.real" ]; then
  echo "Official Claude Code not found. Installing official binary..."
  curl -fsSL https://claude.ai/install.sh | bash || true
fi

mkdir -p "${BIN_DIR}" "${CLAUDE_DIR}" "${PROFILES_DIR}"

# 3. Preserve Original Binary
REAL_CLAUDE="${BIN_DIR}/claude.real"
CURRENT_CLAUDE="$(command -v claude || echo "${BIN_DIR}/claude")"

if [ -f "$CURRENT_CLAUDE" ] && [ ! -f "$REAL_CLAUDE" ]; then
  if [ -L "$CURRENT_CLAUDE" ]; then
    TARGET=""
    if command -v realpath >/dev/null 2>&1; then
      TARGET="$(realpath "$CURRENT_CLAUDE" 2>/dev/null || true)"
    fi
    if [ -z "$TARGET" ]; then
      TARGET="$(python3 -c "import os, sys; print(os.path.realpath(sys.argv[1]))" "$CURRENT_CLAUDE" 2>/dev/null || true)"
    fi
    if [ -z "$TARGET" ]; then
      TARGET="$(readlink "$CURRENT_CLAUDE" 2>/dev/null || echo "$CURRENT_CLAUDE")"
    fi
    if [ -n "$TARGET" ] && [ "$TARGET" != "$REAL_CLAUDE" ]; then
      ln -sf "$TARGET" "$REAL_CLAUDE"
    fi
  else
    cp "$CURRENT_CLAUDE" "$REAL_CLAUDE"
  fi
  echo "✓ Preserved official Claude binary at ${REAL_CLAUDE}"
elif [ ! -f "$REAL_CLAUDE" ]; then
  LATEST_VER="$(ls -v "${HOME}/.local/share/claude/versions/" 2>/dev/null | tail -n 1 || true)"
  if [ -n "$LATEST_VER" ] && [ -x "${HOME}/.local/share/claude/versions/${LATEST_VER}" ]; then
    ln -sf "${HOME}/.local/share/claude/versions/${LATEST_VER}" "$REAL_CLAUDE"
    echo "✓ Linked official Claude binary from versions: ${LATEST_VER}"
  fi
fi

# 4. Install Master Wrapper Script
cp "${SCRIPT_DIR}/bin/claude" "${BIN_DIR}/claude"
chmod +x "${BIN_DIR}/claude"
echo "✓ Installed master wrapper to ${BIN_DIR}/claude"

# 5. Install Global Instructions, Rules, Commands & Helper Engines
mkdir -p "${CLAUDE_DIR}/rules" "${CLAUDE_DIR}/commands" "${CLAUDE_DIR}/scripts" "${CLAUDE_DIR}/skills" "${CLAUDE_DIR}/completion"

cp "${SCRIPT_DIR}/config/CLAUDE.md" "${CLAUDE_DIR}/CLAUDE.md"
cp "${SCRIPT_DIR}/config/rules/"*.md "${CLAUDE_DIR}/rules/"
cp "${SCRIPT_DIR}/config/commands/"*.md "${CLAUDE_DIR}/commands/"
cp "${SCRIPT_DIR}/scripts/token-opt-clean.sh" "${CLAUDE_DIR}/scripts/token-opt-clean.sh"
chmod +x "${CLAUDE_DIR}/scripts/token-opt-clean.sh"

# Copy python cognitive, orchestration, and MCP engines
for py_script in claude-capacity-check.py claude-palace.py claude-dream.py claude-provider.py claude-models.py gemini-proxy.py claude-research.py claude-cognition.py cortex-mcp.py; do
  if [ -f "${SCRIPT_DIR}/scripts/${py_script}" ]; then
    cp "${SCRIPT_DIR}/scripts/${py_script}" "${CLAUDE_DIR}/scripts/${py_script}"
    chmod +x "${CLAUDE_DIR}/scripts/${py_script}"
    bin_name="${py_script%.py}"
    if [ "$bin_name" != "gemini-proxy" ]; then
      ln -sf "${CLAUDE_DIR}/scripts/${py_script}" "${BIN_DIR}/${bin_name}"
    fi
  fi
done
echo "✓ Installed Memory Palace, Dream Simulation, Frontier Research, Models Catalog, and Cortex MCP Engine"

# Merge settings.json cleanly
if [ -f "${CLAUDE_DIR}/settings.json" ]; then
  python3 -c "
import json
try:
    with open('${CLAUDE_DIR}/settings.json') as f:
        orig = json.load(f)
except Exception:
    orig = {}
try:
    with open('${SCRIPT_DIR}/config/settings.json') as f:
        new_cfg = json.load(f)
except Exception:
    new_cfg = {}
orig.update(new_cfg)
with open('${CLAUDE_DIR}/settings.json', 'w') as f:
    json.dump(orig, f, indent=2)
" 2>/dev/null || true
else
  cp "${SCRIPT_DIR}/config/settings.json" "${CLAUDE_DIR}/settings.json"
fi

# 6. Install Skills
cp -r "${SCRIPT_DIR}/skills/"* "${CLAUDE_DIR}/skills/"
echo "✓ Installed productivity and cognitive skills"

# 7. Install Shell Autocompletion
if [ -f "${SCRIPT_DIR}/completion/claude.bash" ]; then
  cp "${SCRIPT_DIR}/completion/claude.bash" "${CLAUDE_DIR}/completion/claude.bash"
  if [ -d "${HOME}/.bashrc.d" ]; then
    ln -sf "${CLAUDE_DIR}/completion/claude.bash" "${HOME}/.bashrc.d/claude-completion.bash"
  fi
fi
if [ -f "${SCRIPT_DIR}/completion/_claude" ]; then
  cp "${SCRIPT_DIR}/completion/_claude" "${CLAUDE_DIR}/completion/_claude"
fi
echo "✓ Installed shell autocompletion (Bash & Zsh)"

# 8. Re-Sync and Re-Link Profiles (Clean Reset without Data Corruption)
SHARED_ITEMS=(
  "projects" "file-history" "history.jsonl" "commands"
  "skills" "rules" "plugins" "settings.json" "mcp-configs"
  "session-env" "shell-snapshots" "ide" "palace"
)

EXISTING_PROFILES="$(ls -1 "${PROFILES_DIR}" 2>/dev/null | grep -v 'current_profile' || true)"

if [ -z "$EXISTING_PROFILES" ]; then
  PRIMARY_PROF="main"
  mkdir -p "${PROFILES_DIR}/${PRIMARY_PROF}"
  echo "$PRIMARY_PROF" > "${PROFILES_DIR}/current_profile"
  echo "synced" > "${PROFILES_DIR}/${PRIMARY_PROF}/.profile_mode"

  if [ -f "${CLAUDE_DIR}/.credentials.json" ]; then
    cp "${CLAUDE_DIR}/.credentials.json" "${PROFILES_DIR}/${PRIMARY_PROF}/.credentials.json"
  fi
  if [ -f "${HOME}/.claude.json" ]; then
    cp "${HOME}/.claude.json" "${PROFILES_DIR}/${PRIMARY_PROF}/.claude.json"
  fi

  for item in "${SHARED_ITEMS[@]}"; do
    src="${CLAUDE_DIR}/${item}"
    dst="${PROFILES_DIR}/${PRIMARY_PROF}/${item}"
    if [ ! -e "$dst" ] && [ -e "$src" ]; then
      ln -sf "$src" "$dst"
    fi
  done
  echo "✓ Initialized primary profile [${PRIMARY_PROF}] with full data synchronization"
else
  echo "Re-syncing existing profiles cleanly..."
  for prof in $EXISTING_PROFILES; do
    prof_dir="${PROFILES_DIR}/${prof}"
    [ -d "$prof_dir" ] || continue

    # Default to synced mode if not set
    if [ ! -f "${prof_dir}/.profile_mode" ]; then
      echo "synced" > "${prof_dir}/.profile_mode"
    fi
    mode="$(cat "${prof_dir}/.profile_mode" 2>/dev/null | tr -d ' \n\r' || echo "synced")"

    if [ "$mode" = "synced" ]; then
      for item in "${SHARED_ITEMS[@]}"; do
        src="${CLAUDE_DIR}/${item}"
        dst="${prof_dir}/${item}"
        # If dst is a broken link or doesn't exist, re-link
        if [ -L "$dst" ] && [ ! -e "$dst" ]; then
          rm -f "$dst"
        fi
        if [ ! -e "$dst" ] && [ -e "$src" ]; then
          ln -sf "$src" "$dst"
        fi
      done
    fi
    echo "  ✓ Re-synced profile: ${prof} (${mode})"
  done
fi

# Ensure default profile is active
if [ ! -f "${PROFILES_DIR}/current_profile" ]; then
  first_prof="$(ls -1 "${PROFILES_DIR}" 2>/dev/null | grep -v 'current_profile' | head -n 1 || echo "main")"
  echo "$first_prof" > "${PROFILES_DIR}/current_profile"
fi

# 9. Configure Shell Environment
SHELL_RC=""
if [ -n "${BASH_VERSION:-}" ] || [ -f "${HOME}/.bashrc" ]; then
  SHELL_RC="${HOME}/.bashrc"
elif [ -f "${HOME}/.zshrc" ]; then
  SHELL_RC="${HOME}/.zshrc"
fi

if [ -n "$SHELL_RC" ]; then
  if ! grep -q '\.local/bin' "$SHELL_RC" 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_RC"
    echo "✓ Added ~/.local/bin to ${SHELL_RC}"
  fi
  if [ ! -d "${HOME}/.bashrc.d" ] && ! grep -q 'claude.bash' "$SHELL_RC" 2>/dev/null; then
    echo '[ -f "$HOME/.claude/completion/claude.bash" ] && source "$HOME/.claude/completion/claude.bash"' >> "$SHELL_RC"
    echo "✓ Added tab completion to ${SHELL_RC}"
  fi
fi

# 10. Multi-IDE Claude Code Extension Integration Wizard
echo "Scanning and configuring installed IDEs (VS Code, Antigravity, Cursor, VSCodium, Windsurf)..."
IDE_CONFIGS=(
  "VS Code|${HOME}/.config/Code/User/settings.json|code"
  "VS Code (macOS)|${HOME}/Library/Application Support/Code/User/settings.json|code"
  "Google Antigravity|${HOME}/.config/Antigravity/User/settings.json|antigravity"
  "Google Antigravity (macOS)|${HOME}/Library/Application Support/Antigravity/User/settings.json|antigravity"
  "Cursor|${HOME}/.config/Cursor/User/settings.json|cursor"
  "Cursor (macOS)|${HOME}/Library/Application Support/Cursor/User/settings.json|cursor"
  "VSCodium|${HOME}/.config/VSCodium/User/settings.json|codium"
  "VSCodium (macOS)|${HOME}/Library/Application Support/VSCodium/User/settings.json|codium"
  "Windsurf|${HOME}/.config/Windsurf/User/settings.json|windsurf"
  "Windsurf (macOS)|${HOME}/Library/Application Support/Windsurf/User/settings.json|windsurf"
)

for ide_spec in "${IDE_CONFIGS[@]}"; do
  IFS="|" read -r ide_name settings_path ide_cli <<< "$ide_spec"
  settings_dir="$(dirname "$settings_path")"
  if [ -d "$settings_dir" ] || [ -f "$settings_path" ]; then
    mkdir -p "$settings_dir"
    python3 -c "
import json, os
p = '$settings_path'
try:
    if os.path.exists(p):
        with open(p) as f: d = json.load(f)
    else:
        d = {}
except Exception:
    d = {}
d['claudeCode.claudeProcessWrapper'] = '${BIN_DIR}/claude'
with open(p, 'w') as f: json.dump(d, f, indent=4)
" 2>/dev/null || true
    echo "  ✓ Configured Claude Code process wrapper for ${ide_name}"

    # Check / install extension if IDE CLI is available
    if command -v "$ide_cli" >/dev/null 2>&1; then
      if ! "$ide_cli" --list-extensions 2>/dev/null | grep -iq "anthropic.claude-code"; then
        echo "    Installing anthropic.claude-code extension for ${ide_name}..."
        "$ide_cli" --install-extension anthropic.claude-code >/dev/null 2>&1 || true
      fi
    fi
  fi
done

# 11. Configure Claude Desktop Multi-Profile & Cortex Native MCP Integration
DESKTOP_APPS_DIR="${HOME}/.local/share/applications"
mkdir -p "$DESKTOP_APPS_DIR"

DESKTOP_CONFIG_DIRS=(
  "${HOME}/.config/Claude"
  "${HOME}/.config/claude-profile-1"
  "${HOME}/.config/claude-profile-2"
  "${HOME}/Library/Application Support/Claude"
)

for prof in $(ls -1 "${PROFILES_DIR}" 2>/dev/null | grep -v 'current_profile' || echo "vl ws"); do
  case "$prof" in
    ws|1) prof_label="Claude WS"; udir="${HOME}/.config/claude-profile-1" ;;
    vl|2) prof_label="Claude VL"; udir="${HOME}/.config/claude-profile-2" ;;
    *) prof_label="Claude $(echo "$prof" | tr '[:lower:]' '[:upper:]')"; udir="${HOME}/.config/claude-${prof}" ;;
  esac
  mkdir -p "$udir"
  DESKTOP_CONFIG_DIRS+=("$udir")
  dfile="${DESKTOP_APPS_DIR}/claude-${prof}.desktop"
  cat > "$dfile" <<EOF
[Desktop Entry]
Name=${prof_label}
Comment=Claude Desktop Profile (${prof})
Exec=claude-desktop-unofficial --user-data-dir=${udir} %U
Icon=claude-desktop-unofficial
Type=Application
Terminal=false
Categories=Utility;Development;
StartupWMClass=Claude
EOF
  chmod +x "$dfile" 2>/dev/null || true
done

# Register Cortex MCP server in Claude Desktop configurations
for cdir in "${DESKTOP_CONFIG_DIRS[@]}"; do
  cfg_file="${cdir}/claude_desktop_config.json"
  if [ -d "$cdir" ] || [ -f "$cfg_file" ]; then
    mkdir -p "$cdir"
    python3 -c "
import json, os
p = '$cfg_file'
try:
    if os.path.exists(p):
        with open(p) as f: cfg = json.load(f)
    else:
        cfg = {}
except Exception:
    cfg = {}

cfg.setdefault('mcpServers', {})
cfg['mcpServers']['claude-cortex'] = {
    'command': 'python3',
    'args': ['${CLAUDE_DIR}/scripts/cortex-mcp.py']
}
with open(p, 'w') as f:
    json.dump(cfg, f, indent=2)
" 2>/dev/null || true
    echo "  ✓ Registered Cortex MCP tools in: ${cfg_file}"
  fi
done
echo "✓ Configured Claude Desktop multi-profile launchers & native Cortex MCP tools"

echo ""
echo "======================================================================"
echo "  ✓ Installation Complete! Claude Cortex is Ready Everywhere."
echo "======================================================================"
echo ""
echo "Accessible from:"
echo "  • Terminal:             claude, claude -ws, claude -vl, claude continue"
echo "  • VS Code Extension:    Native Claude Code extension auto-routed through wrapper"
echo "  • Claude Desktop App:   claude desktop ws, claude desktop vl, or application menu"
echo ""
echo "Core Commands:"
echo "  claude continue         Auto-check capacity across all accounts and resume session"
echo "  claude switch [prof]    Switch default active profile (or toggle with claude switch)"
echo "  claude status / quota   Display real-time capacity and rate-limit countdowns"
echo "  claude -t / --turbo     High-speed output with minimal token consumption"
echo "  claude desktop [prof]   Launch Claude Desktop with specific account"
echo "  claude vscode [prof]    Launch VS Code configured with specific account"
echo "  claude palace           Cognitive Memory Palace status and rooms"
echo "  claude dream            Simulate counterfactual scenarios and stress-test code"
echo "  claude provider         Manage fallback API keys (Anthropic, OpenRouter, Gemini)"
echo "  claude docs             View comprehensive Cortex documentation"
echo "======================================================================"
