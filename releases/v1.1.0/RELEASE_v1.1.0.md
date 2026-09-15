# Claude Cortex v1.1.0 Release Manifest 🚀

**Release Date:** 2026-09-15  
**Upstream Parity:** Claude Code v2.1.272+  
**Target Repository:** github.com/nikhlgoel/claude-cortex.git

## Categorized Release Artifacts

| Distribution Package | Format | Size | Description |
| :--- | :--- | :--- | :--- |
| `claude-cortex-v1.1.0-full.zip` | ZIP | 486.9 KB | Complete suite: Terminal + Multi-Account Failover + Memory Palace + Dream Simulator + Desktop MCP + Multi-IDE Wizard + All Installers. |
| `claude-cortex-v1.1.0-full.tar.gz` | TAR.GZ | 388.8 KB | Complete suite for Unix / macOS with POSIX executable permissions. |
| `claude-cortex-v1.1.0-terminal-only.zip` | ZIP | 458.4 KB | Lightweight terminal edition: CLI wrapper, autonomous failover, models catalog, memory palace. Zero GUI/Desktop overhead. |
| `claude-cortex-v1.1.0-terminal-only.tar.gz` | TAR.GZ | 358.4 KB | Pure terminal edition for Linux/macOS SSH servers & workstations. |
| `claude-cortex-v1.1.0-desktop-mcp.zip` | ZIP | 48.2 KB | Desktop MCP Server edition: Direct integration with Claude Desktop App GUI and IDEs. |
| `claude-cortex-v1.1.0-windows-x64.zip` | ZIP | 486.9 KB | Windows 1-Click edition with `install.exe`, `install.cmd`, `install.ps1`, and official binary auto-migration. |
| `claude-cortex-v1.1.0-darwin-linux.tar.gz` | TAR.GZ | 365.8 KB | macOS & Linux distribution with automated pre-install backups. |

## SHA-256 Checksums
```
1682e910e85feeabef67fcf1d356947068c1af2f4eb008f50f280070f03770af  claude-cortex-v1.1.0-darwin-linux.tar.gz
c0aab437446aed7b93ac23e717f9238caa67b7f75f5b4a40773b6afa44d2a195  claude-cortex-v1.1.0-desktop-mcp.tar.gz
ee85c78e21324bb0cf175c4d686463bf0696108332c447e004655059686a5ba7  claude-cortex-v1.1.0-desktop-mcp.zip
7993c7837a022d495b9063ae5f66c1e24e55399660c13b6097b30673eba49dea  claude-cortex-v1.1.0-full.tar.gz
eec68271a48026c6386cf13e3d523bb7af11b2c5b0d6ef2e37c3a73c00366e8b  claude-cortex-v1.1.0-full.zip
f2d2e535808d7ed1e33fdf3587f56451384f80d7d7bb6b9c3f5b6c0aa2fe3e6a  claude-cortex-v1.1.0-terminal-only.tar.gz
1dc3d1cd9b61ad1cb100c5a9e9f232380e0454c54b804bbcab00aba0ccf60b4b  claude-cortex-v1.1.0-terminal-only.zip
eec68271a48026c6386cf13e3d523bb7af11b2c5b0d6ef2e37c3a73c00366e8b  claude-cortex-v1.1.0-windows-x64.zip
```

## Highlights & Upgrades in v1.1.0
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
