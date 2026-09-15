# Claude Cortex v2.0.0 Release Manifest 🚀

**Release Date:** 2026-09-15  
**Upstream Parity:** Claude Code v2.1.272+  
**Target Repository:** github.com/nikhlgoel/claude-cortex.git

## Categorized Release Artifacts

| Distribution Package | Format | Size | Description |
| :--- | :--- | :--- | :--- |
| `claude-cortex-v2.0.0-full.zip` | ZIP | 486.9 KB | Complete suite: Terminal + Multi-Account Failover + Memory Palace + Dream Simulator + Desktop MCP + Multi-IDE Wizard + All Installers. |
| `claude-cortex-v2.0.0-full.tar.gz` | TAR.GZ | 388.8 KB | Complete suite for Unix / macOS with POSIX executable permissions. |
| `claude-cortex-v2.0.0-terminal-only.zip` | ZIP | 458.4 KB | Lightweight terminal edition: CLI wrapper, autonomous failover, models catalog, memory palace. Zero GUI/Desktop overhead. |
| `claude-cortex-v2.0.0-terminal-only.tar.gz` | TAR.GZ | 358.4 KB | Pure terminal edition for Linux/macOS SSH servers & workstations. |
| `claude-cortex-v2.0.0-desktop-mcp.zip` | ZIP | 48.2 KB | Desktop MCP Server edition: Direct integration with Claude Desktop App GUI and IDEs. |
| `claude-cortex-v2.0.0-windows-x64.zip` | ZIP | 486.9 KB | Windows 1-Click edition with `install.exe`, `install.cmd`, `install.ps1`, and official binary auto-migration. |
| `claude-cortex-v2.0.0-darwin-linux.tar.gz` | TAR.GZ | 365.8 KB | macOS & Linux distribution with automated pre-install backups. |

## SHA-256 Checksums
```
d35ca8e85878774af6d3679b95d22554af6137f974653818a7ca75ce9037448a  claude-cortex-v2.0.0-darwin-linux.tar.gz
2f8a92492ef414e11f14f4a40dd143b0ccfba9b87dbc19fb9a8630003039fe6b  claude-cortex-v2.0.0-desktop-mcp.tar.gz
dd627ebc31e5790f85a71219d8bcb8d30ff57134f21bfc0ea4da633618f706b8  claude-cortex-v2.0.0-desktop-mcp.zip
727a7ca60a8ff332a273f5e5e79be46ffaf313af4081ad1877a355c18f05d0e0  claude-cortex-v2.0.0-full.tar.gz
df84b24bf5240b0e638627cf19b9b691f3e1f1a366f3ae021a3bb77a59b1c9ca  claude-cortex-v2.0.0-full.zip
18f2280d483288b74d79a7d9fc3508faa772cbd7a98723550c4be3327a80aa16  claude-cortex-v2.0.0-terminal-only.tar.gz
1f7e0ca4ac98d7b25ed00e9a4db85f9f5171dacebe3e9b8ad4dd6c507f087e5e  claude-cortex-v2.0.0-terminal-only.zip
df84b24bf5240b0e638627cf19b9b691f3e1f1a366f3ae021a3bb77a59b1c9ca  claude-cortex-v2.0.0-windows-x64.zip
```

## Highlights & Upgrades in v2.0.0
1. **Interactive Keyboard TUI Model Selector**:
   - Real-time arrow navigation (`↑`/`↓`), Free vs Paid toggle (`f`).
   - Detailed Evaluation Dossier modal popup (`Shift`, `Tab`, `i`) showing SWE coding ratings, MMLU reasoning benchmarks, token generation latency, context limits, and task matching.
2. **Deep Claude Desktop Native MCP Integration**:
   - Local JSON-RPC Model Context Protocol server (`cortex-mcp.py`).
   - Auto-registered across all profile configs in `claude_desktop_config.json` with 6 native GUI tools (`cortex_status`, `cortex_switch`, `cortex_model`, `cortex_provider`, `cortex_palace`, `cortex_dream`).
3. **Multi-IDE Extension Integration Wizard**:
   - Seamlessly configures **VS Code**, **Google Antigravity**, **Cursor**, **VSCodium**, and **Windsurf**.
   - Auto-injects `"claudeCode.claudeProcessWrapper"` into each IDE's `settings.json` without touching personal themes or custom keybindings.
4. **Autonomous Rate-Limit Failover (`claude continue`)**:
   - Zero-loss multi-account capacity scanning and automatic handoff.
5. **Cognitive Memory Palace v2.5 & Dream Simulation**:
   - Dual-speed recall with inverted tag indexing across 5 architectural rooms.
   - 4-chamber REM counterfactual stress-testing engine.
6. **Universal Windows Suite**:
   - Native `install.exe`, ExecutionPolicy auto-bypass `install.cmd`, official binary auto-migration, and login state restoration.
