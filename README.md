# Claude Cortex 🚀
### Multi-Account Manager, Cognitive Memory Palace, Dream Simulation, Autonomous Rate-Limit Failover & API Proxy Suite

A unified, production-grade toolkit for **Claude Code** in terminal that unlocks:
- **Dual & Multi-Account Management**: Run `claude -ws` and `claude -vl` simultaneously or switch with `claude switch ws`.
- **Autonomous Capacity-Aware Failover**: When accounts hit rate limits, `claude continue` automatically scans all configured accounts, detects exact reset countdowns, finds an account with remaining capacity, switches to it, and resumes your session with zero context loss!
- **Cognitive Memory Palace v2.0**: Neuroscience-grounded long-term memory with inverted tag indexing, room-based storage (`blueprint`, `procedures`, `graveyard`, `decisions`, `working`), and autonomous recall before tasks.
- **Cognitive Dream Simulation Engine**: Replicates REM Sleep / Default Mode Network. Simulates counterfactual worst-case scenarios and stress tests across 4 chambers: Technical/Security, Business/Economics, Psychological/UX, and Creative leaps (`claude dream` / `/dream`).
- **Latest Model Shortcuts & Reasoning Control**: Native aliases pointing to `claude-sonnet-5` (`-s`), `claude-opus-5` (`-o`), `claude-haiku-4-5` (`-h`) and explicit thinking effort controls (`--effort <low|medium|high|max>`, `/reasoning <level>`).
- **Live Pairing & Discussion Mode**: Interactive co-pilot workflow (`/pair`, `/discuss`) that halts at architectural inflection points, debates trade-offs, auto-starts approved plans, and proactively prompts for follow-up amendments.
- **External API Providers & Fallback Proxy**: When subscriptions expire, seamlessly continue via Anthropic API, OpenRouter.ai, or Google Gemini AI Studio with streaming translation (`gemini-proxy.py`).
- **Universal Safe Pre-Install Backup**: Automatically archives all existing user configurations and profiles into timestamped archives (`~/.claude-backups/`) with zero data loss before clean reinstallation.
- **Tab Autocompletion & Interactive Menu**: Autocompletes commands, profiles, models, and flags in Bash/Zsh; includes an interactive visual menu (`claude menu`).

---

## 💻 1-Click Installation

### On Linux & macOS:
1. Extract the package:
   ```bash
   tar -xzf claude-cortex.tar.gz
   cd claude-cortex
   ```
2. Run the installer (creates automated backup first, then performs clean setup):
   ```bash
   ./install.sh
   ```
3. Restart your terminal or reload your shell:
   ```bash
   source ~/.bashrc   # (or: source ~/.zshrc)
   ```

### On Windows:
1. Extract `claude-cortex.zip`.
2. Choose ANY of the convenient installation methods:
   - **Method A (Easiest - 1-Click Executable)**: Double-click **`install.exe`**
   - **Method B (1-Click Batch Script)**: Double-click **`install.cmd`**
   - **Method C (PowerShell with Auto-Bypass)**: Open PowerShell in the folder and run:
     ```powershell
     powershell -ExecutionPolicy Bypass -File .\install.ps1
     ```
   - **Method D (Pure Python)**:
     ```powershell
     python install.py
     ```
3. Open a new PowerShell window, Command Prompt, or Windows Terminal.

> [!NOTE]
> **Automatic Official Claude Code Migration**: The Windows installer automatically detects any previous official Claude Code installations (e.g. from `irm https://claude.ai/install.ps1 | iex` or npm), cleanly creates a safe pre-install backup archive, preserves the official binary as `claude.real.exe`, removes conflicting residue, and **restores your active login session and project history** so you remain logged in with zero interruption!

---

## ⚡ Quick Start & Commands

### 1. Multi-Account Launching
```bash
claude -ws               # Launch using WS account
claude -vl               # Launch using VL account
claude -work             # Launch using custom profile (e.g. work, client)
claude -1 / claude -2    # Launch by profile index
claude                   # Launch using active default profile
```

### 2. Autonomous Rate-Limit Failover (`claude continue`)
When your active account hits an Anthropic rate limit:
```bash
claude continue
```
Claude Code automatically:
1. Scans every account in `~/.claude-profiles/`.
2. Checks 5-hour and 7-day rate limits and active quota warnings.
3. Automatically identifies an account with free capacity.
4. Switches active credentials and resumes the exact session with `--continue`!

### 3. Latest Models & Reasoning Effort
```bash
claude -s                # Launch Claude Sonnet 5 (claude-sonnet-5)
claude -o                # Launch Claude Opus 5 (claude-opus-5)
claude -h                # Launch Claude Haiku 4.5 (claude-haiku-4-5)
claude -e high           # Set reasoning effort (low, medium, high, max)
claude --think-high      # Deep reasoning effort shortcut
claude --think-off       # Disable reasoning for rapid responses
claude reasoning high    # Save default reasoning effort in settings.json
```

### 4. Cognitive Memory Palace v2.0
Human-like long-term retention of architecture, bugs, and decisions:
```bash
claude palace            # View palace status, room metrics, and indexed tags
claude palace map        # Detailed breakdown of all rooms
claude remember <room> <notes>  # Store lesson (rooms: blueprint, procedures, graveyard, decisions)
claude recall <topic>    # Search palace memories using inverted tag indexing
```

### 5. Cognitive Dream Engine (Stress Testing)
Simulate counterfactual scenarios and hunt edge cases before production:
```bash
claude dream             # Full 4-chamber simulation on current project context
claude dream --quick     # Fast 2-chamber sanity check
claude dream run --topic "multi-tenant billing" --chambers tech,security
```
Chambers:
- **Technical/Security Crucible**: Concurrency races, OOM leaks, rate limit thrashing, injection vectors.
- **Business/Economic Stress**: Churn spikes, API overuse cost explosions, pricing friction.
- **Psychological/UX Friction**: Cognitive overload, misleading CLI output, confusing error states.
- **Creative & Divergent Leaps**: 10x architectural simplifications and lateral ideas.

### 6. External API Providers & Key Setup (One-Time)
Configure fallback providers cleanly without confusing API keys and model names:
```bash
claude provider status                # Check configured providers & active endpoints
claude provider set openrouter        # Switch active provider to OpenRouter
claude provider key openrouter sk-or-v1-...  # Set API key securely
claude provider set gemini            # Switch to Google Gemini AI Studio
claude provider key gemini AIzaSy...  # Set Gemini API key
claude provider set oauth             # Return to standard Claude Code subscription
```

### 7. Interactive Keyboard TUI Model Selector & Benchmark Dossier
Navigate models seamlessly with keyboard arrows, evaluate benchmarks in real-time modals, and switch models dynamically:
```bash
claude model                          # Launch live interactive TUI model browser
claude model free                     # Launch TUI filtered to 100% FREE models (0 credits needed)
claude model list                     # Print non-interactive table of models for active provider
claude model set <model_id>           # Switch model directly (e.g. claude model set deepseek/deepseek-r1:free)
claude model info <model_id>          # Open full evaluation dossier modal (benchmarks, latency, context)
claude --free                         # Launch Claude Code immediately using the top free model
```

**TUI Keyboard Controls**:
- **`[↑] / [↓]` Arrow Keys**: Move highlight cursor across models.
- **`[Shift]` / `[Tab]` / `[i]` / `[Space]`**: Open **Evaluation Dossier Modal** showing SWE coding ratings, MMLU reasoning benchmarks, token generation latency, context limits, architecture type, and optimal task assignment.
- **`[Esc]`**: Exit modal popup or close model picker keeping current configuration.
- **`[f]`**: Instant toggle between 100% Free models (OpenRouter) and all frontier models.
- **`[Enter]`**: Select and activate the highlighted model instantly.

### 8. Claude Desktop Native MCP Integration
Claude Cortex ships with a native Model Context Protocol (MCP) server (`cortex-mcp.py`) automatically configured into `claude_desktop_config.json`:
- **Direct GUI Tool Access**: Use Claude Desktop GUI to query Cortex status, switch between work and personal profiles, switch models, consult the Cognitive Memory Palace, and run dream simulations.
- **Native Tools Available**: `cortex_status`, `cortex_switch`, `cortex_model`, `cortex_provider`, `cortex_palace`, `cortex_dream`.
- **Zero Config**: Automatically registers across default and multi-profile desktop configurations (`Claude`, `claude-profile-1`, `claude-profile-2`).

### 9. Multi-IDE Extension Auto-Configuration Wizard
During installation, Cortex automatically scans and configures the Claude Code extension (`anthropic.claude-code`) across all installed IDEs:
- **Supported Environments**: **VS Code**, **Google Antigravity**, **Cursor**, **VSCodium**, **Windsurf**.
- **Transparent Wrapping**: Automatically injects `"claudeCode.claudeProcessWrapper"` into each IDE's `settings.json` without modifying any of your custom user preferences or themes.
- **Automatic Extension Setup**: Automatically installs or verifies the extension if the IDE's CLI tool is available on PATH.

### 10. In-Session Command Execution (Inside Active Prompt `❯`)
You can run any Cortex command directly inside an active session prompt (whether typed with `claude `, with `/`, or as plain keywords):
- `claude continue vl` or `/continue vl`: Checkpoints progress to `MEMORY.md`, auto-switches account, and displays exact resume instruction.
- `claude switch ws` or `/switch ws`: Switches active account seamlessly.
- `claude model` or `/model`: Opens model catalog and benchmarks inside the session.
- `claude provider status` or `/provider`: Views or updates API keys inside the session.
- `claude status` or `/status`: Displays live capacity and rate-limit countdowns.

### 9. Account Capacity Dashboard
```bash
claude status            # Full multi-account overview with live quota & capacity
claude quota             # Alias for capacity dashboard
```

### 10. Switching Active Default Account
```bash
claude switch ws         # Sets WS as default
claude switch vl         # Sets VL as default
claude switch            # Automatically switches to the account with free capacity
```

### 11. Adding New Profiles (Synced or Isolated)
```bash
claude profile add
```
- **Synced** (Recommended): Shares project conversations, Memory Palace, custom skills, and commands. Quotas and credentials remain completely independent.
- **Isolated**: Independent sandbox for client work.

---

## 🛠️ In-Session Slash Commands

Inside any active Claude Code prompt shell:

| Command | Description |
| :--- | :--- |
| `/continue [prof]` | Scans capacity, switches account, checkpoints session memory, and prepares continuation. |
| `/model [args]` | Interactive model selector with benchmarks, context window, and Free vs Paid filters. |
| `/provider [args]`| Manages fallback API keys and endpoints (Anthropic, OpenRouter, Gemini). |
| `/quota` / `/status` | Displays real-time 5-hour and 7-day utilization and reset countdowns across all accounts. |
| `/switch [prof]` | Flushes session memory and switches the active default profile. |
| `/palace` | Displays Memory Palace room status, storage stats, and indexed tags. |
| `/remember [room]` | Stores a hard-won bugfix, architectural rule, or decision into the Palace. |
| `/recall <topic>` | Recalls lessons, architectural boundaries, or edge cases from the Palace. |
| `/dream [topic]` | Simulates counterfactual edge cases and auto-consolidates insights into the Palace. |
| `/pair` | Activates Live Pairing mode to discuss trade-offs, auto-implement, and review amendments. |
| `/discuss` | Starts interactive brainstorming on design, security, or architecture. |
| `/reasoning <lvl>`| Sets thinking effort level (`low`, `medium`, `high`, `xhigh`, `max`). |
| `/compact-smart` | Preserves key decisions in `MEMORY.md` before compacting, saving 100k+ tokens. |
| `/clean` | Cleans temporary caches, stale diffs, and dead sessions to free storage. |
| `/docs` | View the full Cortex guide directly in-session. |

---

## 🧠 Autonomous Behavioral Rules

Installed in `~/.claude/rules/`:
1. **`01-token-efficiency.md`**: Enforces high-density responses, eliminates conversational filler, and leverages precise inspections.
2. **`02-autonomous-skills.md`**: Automatically connects Spec Kit, Scrapling, and ECC without prompting.
3. **`03-project-memory-sync.md`**: Standardizes `memory/MEMORY.md` and triggers auto-failover on rate limits.
4. **`04-live-pairing.md`**: Enforces interactive co-pilot step discussions and proactive post-implementation amendment checks.
5. **`05-memory-palace.md`**: Governs dual-speed memory recall before starting complex tasks and automated storage after breakthroughs.
6. **`06-dream-simulation.md`**: Governs pre-release stress-testing, bug hunting, and counterfactual chaos simulations.

---

## 📦 Package Structure

```
claude-cortex/
├── README.md                  # Complete documentation and usage guide
├── install.exe                # 1-click Windows native executable installer
├── install.cmd                # 1-click Windows batch installer with auto-bypass
├── install.ps1                # 1-click Windows PowerShell installer with automated backup
├── install.py                 # Universal cross-platform Python installer
├── install.sh                 # 1-click installer with automated backup (Linux/macOS)
├── bin/
│   ├── claude                 # Master Bash wrapper (Linux/macOS)
│   ├── claude.ps1             # Master PowerShell wrapper (Windows)
│   └── claude.cmd             # Master CMD batch shim (Windows)
├── completion/
│   ├── claude.bash            # Bash completion script
│   └── _claude                # Zsh completion script
├── config/
│   ├── CLAUDE.md              # Global system instructions
│   ├── settings.json          # Token-optimized settings
│   ├── rules/                 # Global behavioral rules (01-07)
│   └── commands/              # Slash commands (/dream, /palace, /continue, /model, etc.)
├── scripts/
│   ├── claude-models.py       # Interactive keyboard TUI model selector & benchmark dossier
│   ├── cortex-mcp.py          # Native Model Context Protocol server for Claude Desktop App
│   ├── claude-capacity-check.py # Multi-account capacity & rate-limit failover engine
│   ├── claude-palace.py       # Cognitive Memory Palace v2 engine
│   ├── claude-dream.py        # Cognitive Dream Simulation engine
│   ├── claude-provider.py     # External API provider & key manager
│   ├── claude-research.py     # Deep research & architectural synthesis engine
│   ├── gemini-proxy.py        # Google Gemini AI Studio streaming proxy
│   ├── token-opt-clean.sh     # Linux/macOS maintenance cleaner
│   └── token-opt-clean.ps1    # Windows maintenance cleaner
└── skills/                    # Packaged skills (live-pairing, Spec Kit, Scrapling, etc.)
```
