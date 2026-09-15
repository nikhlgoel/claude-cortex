# Changelog

All notable changes to **Claude Cortex** will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - 2026-09-15

### Added
- **Keyboard-Driven Interactive Model Selector (`claude-models.py`)**:
  - Live TUI with arrow navigation (`↑`/`↓`) to browse and switch models without typing IDs.
  - Evaluation Dossier modal popup (`Shift`, `Tab`, `i`, `Space`) displaying SWE coding benchmarks, MMLU reasoning ratings, token latency, context window limits, and optimal task matching.
  - Quick toggle between 100% Free models (OpenRouter 0-credit tier) and frontier models (`f` key).
  - Clear separation between one-time provider/key configuration (`claude provider key <p> <key>`) and frequent model selection (`claude model set <m>`).
- **Claude Desktop App Native MCP Integration (`cortex-mcp.py`)**:
  - Pure Python stdio JSON-RPC Model Context Protocol server exposing Cortex cognitive tools directly to the Claude Desktop GUI.
  - Exposes 6 native tools: `cortex_status`, `cortex_switch`, `cortex_model`, `cortex_provider`, `cortex_palace`, `cortex_dream`.
  - Automatically registered into `claude_desktop_config.json` for default and multi-profile installations.
- **Multi-IDE Extension Integration Wizard**:
  - Scans and automatically configures the Claude Code extension (`anthropic.claude-code`) across **VS Code**, **Google Antigravity**, **Cursor**, **VSCodium**, and **Windsurf**.
  - Safely injects `"claudeCode.claudeProcessWrapper"` into each IDE's `settings.json` without modifying personal preferences or themes.
- **In-Session Command Interception (`07-cortex-in-session-commands.md`)**:
  - Direct execution of management commands (`continue`, `switch`, `model`, `provider`, `status`, `palace`, `dream`) inside active prompt sessions without leaving Claude Code.
- **Categorized Release Packaging Pipeline (`scripts/build-releases.py`)**:
  - Generates Full, Terminal-Only, Desktop MCP, Windows, and Unix release distributions with SHA-256 checksums and automated manifests.

### Changed
- Refactored master wrapper (`bin/claude` and `bin/claude.ps1`) to automatically inject `--model "$ANTHROPIC_MODEL"` for OpenRouter and third-party models, preventing 404 endpoint mismatch errors.
- Improved Windows installer suite with automatic official Claude Code migration and session restoration.

---

## [1.5.0] - 2026-09-14

### Added
- **Cognitive Memory Palace v2.5 (`claude-palace.py`)**:
  - Neuroscience-grounded 5-room long-term architectural retention (`blueprint`, `procedures`, `graveyard`, `decisions`, `working`).
  - Inverted tag indexing for sub-second associative recall (`claude recall <topic>`).
  - Cooperative file-locking concurrency and deduplication guards.
- **Neuroscience Dream Simulation Engine (`claude-dream.py`)**:
  - REM / Default Mode Network simulation engine across 4 chambers: Technical/Security Crucible, Business/Economic Stress, Psychological/UX Friction, Creative Leaps.
  - Automated post-simulation insight consolidation into Memory Palace.
- **Token Efficiency & High-Velocity Modes**:
  - Behavioral rule `01-token-efficiency.md` eliminating filler text and conversational fluff.
  - Compact smart memory snapshotting before session compaction.

---

## [1.0.0] - 2026-09-13

### Added
- **Multi-Account Manager & Architecture**:
  - Dual and multi-profile support (`-ws`, `-vl`, `-1`, `-2`, `-work`) with isolated credentials and synchronized projects.
- **Autonomous Capacity-Aware Failover (`claude continue`)**:
  - Scans 5-hour and 7-day rate-limit countdowns across all configured accounts.
  - Automatically identifies available capacity, checkpoints session progress to `memory/MEMORY.md`, and resumes work with zero loss.
- **External API Fallback Proxy (`gemini-proxy.py`, `claude-provider.py`)**:
  - Fallback streaming proxy for Google Gemini AI Studio and OpenRouter API endpoints.
- **Universal Shell Completion & Packaging**:
  - Bash and Zsh auto-completion scripts.
  - Automated pre-installation backup system in `~/.claude-backups/`.
