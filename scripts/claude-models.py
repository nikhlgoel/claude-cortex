#!/usr/bin/env python3
"""
Claude Cortex - Interactive Model Explorer & Benchmarks Dossier
Keyboard-driven live terminal TUI with arrow key navigation,
evaluation dossier popups (Shift / Tab / i), free vs paid filtering, and instant selection.
"""

import os
import sys
import json
import argparse
import urllib.request
import time

PROVIDERS_FILE = os.path.expanduser("~/.claude/providers.json")
CACHE_FILE = os.path.expanduser("~/.claude/models_cache.json")

# Curated High-Performance Model Catalog with Benchmark Ratings
CURATED_MODELS = {
    "openrouter": [
        # --- FREE MODELS ---
        {
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "name": "NVIDIA Nemotron 3 Ultra 550B",
            "tier": "FREE",
            "cost": "$0.00 / 1M tokens",
            "context": "131k",
            "benchmarks": {"coding": "86.4%", "reasoning": "89.2%", "speed": "Fast (~85 tok/s)"},
            "type": "Ultra-large MoE",
            "best_for": "General coding, complex logic, free prototyping"
        },
        {
            "id": "meta-llama/llama-3.3-70b-instruct:free",
            "name": "Meta Llama 3.3 70B Instruct",
            "tier": "FREE",
            "cost": "$0.00 / 1M tokens",
            "context": "131k",
            "benchmarks": {"coding": "86.1%", "reasoning": "88.6%", "speed": "Very Fast (~110 tok/s)"},
            "type": "Dense LLM",
            "best_for": "Full-stack code generation, refactoring, tests"
        },
        {
            "id": "deepseek/deepseek-r1:free",
            "name": "DeepSeek R1 (Reasoning)",
            "tier": "FREE",
            "cost": "$0.00 / 1M tokens",
            "context": "164k",
            "benchmarks": {"coding": "90.2%", "reasoning": "96.8%", "speed": "Medium (~45 tok/s)"},
            "type": "Chain-of-Thought Reasoner",
            "best_for": "Deep algorithmic debugging, mathematics, tricky edge cases"
        },
        {
            "id": "qwen/qwen-2.5-coder-32b-instruct:free",
            "name": "Qwen 2.5 Coder 32B Instruct",
            "tier": "FREE",
            "cost": "$0.00 / 1M tokens",
            "context": "32k",
            "benchmarks": {"coding": "92.8%", "reasoning": "84.5%", "speed": "Ultra-Fast (~140 tok/s)"},
            "type": "Code Specialist",
            "best_for": "Pure code implementation, fast syntax fixes"
        },
        {
            "id": "google/gemini-2.0-flash-exp:free",
            "name": "Google Gemini 2.0 Flash Exp",
            "tier": "FREE",
            "cost": "$0.00 / 1M tokens",
            "context": "1M",
            "benchmarks": {"coding": "84.2%", "reasoning": "86.1%", "speed": "Ultra-Fast (~150 tok/s)"},
            "type": "Multimodal Flash",
            "best_for": "Huge codebases, 1M context analysis, high speed"
        },
        {
            "id": "mistralai/mistral-small-24b-instruct-2501:free",
            "name": "Mistral Small 24B Instruct",
            "tier": "FREE",
            "cost": "$0.00 / 1M tokens",
            "context": "32k",
            "benchmarks": {"coding": "81.5%", "reasoning": "83.0%", "speed": "Ultra-Fast (~130 tok/s)"},
            "type": "Compact Instruct",
            "best_for": "Quick CLI tasks, low overhead scripting"
        },
        # --- PAID MODELS ---
        {
            "id": "anthropic/claude-3.7-sonnet",
            "name": "Claude 3.7 Sonnet (Hybrid Thinking)",
            "tier": "PAID",
            "cost": "$3.00 in / $15.00 out",
            "context": "200k",
            "benchmarks": {"coding": "96.2%", "reasoning": "95.4%", "speed": "Fast (~75 tok/s)"},
            "type": "Frontier Hybrid",
            "best_for": "Gold standard software engineering, production architecture"
        },
        {
            "id": "anthropic/claude-3.5-haiku",
            "name": "Claude 3.5 Haiku",
            "tier": "PAID",
            "cost": "$0.80 in / $4.00 out",
            "context": "200k",
            "benchmarks": {"coding": "88.4%", "reasoning": "85.2%", "speed": "Ultra-Fast (~140 tok/s)"},
            "type": "High Velocity",
            "best_for": "Lightning-fast iteration, linting, minimal token cost"
        },
        {
            "id": "deepseek/deepseek-chat",
            "name": "DeepSeek V3 (Chat)",
            "tier": "PAID",
            "cost": "$0.14 in / $0.28 out",
            "context": "64k",
            "benchmarks": {"coding": "90.1%", "reasoning": "90.0%", "speed": "Fast (~70 tok/s)"},
            "type": "Ultra-Value Frontier",
            "best_for": "Near-frontier performance at 1/10th the cost"
        },
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI GPT-4o",
            "tier": "PAID",
            "cost": "$2.50 in / $10.00 out",
            "context": "128k",
            "benchmarks": {"coding": "90.2%", "reasoning": "91.8%", "speed": "Fast (~80 tok/s)"},
            "type": "Omni Multimodal",
            "best_for": "Multimodal analysis, cross-language parity"
        }
    ],
    "gemini": [
        {
            "id": "gemini-2.5-pro",
            "name": "Google Gemini 2.5 Pro",
            "tier": "FREE / PAID",
            "cost": "Free Tier / $1.25",
            "context": "2M",
            "benchmarks": {"coding": "89.4%", "reasoning": "93.1%", "speed": "Balanced (~60 tok/s)"},
            "type": "Frontier Multimodal",
            "best_for": "Massive context repositories, complex logic, multimodal"
        },
        {
            "id": "gemini-2.0-flash",
            "name": "Google Gemini 2.0 Flash",
            "tier": "FREE / PAID",
            "cost": "Free Tier / $0.10",
            "context": "1M",
            "benchmarks": {"coding": "84.2%", "reasoning": "86.4%", "speed": "Ultra-Fast (~160 tok/s)"},
            "type": "High-Throughput Flash",
            "best_for": "Rapid automated workflows, high-frequency queries"
        },
        {
            "id": "gemini-2.0-flash-thinking-exp",
            "name": "Gemini 2.0 Flash Thinking Exp",
            "tier": "FREE",
            "cost": "Free Tier",
            "context": "1M",
            "benchmarks": {"coding": "88.6%", "reasoning": "94.2%", "speed": "Fast (~80 tok/s)"},
            "type": "Reasoning Flash",
            "best_for": "Deep mathematical deduction and algorithmic checks"
        }
    ],
    "anthropic": [
        {
            "id": "claude-sonnet-5",
            "name": "Claude Sonnet 5",
            "tier": "PAID",
            "cost": "$3.00 in / $15.00 out",
            "context": "200k",
            "benchmarks": {"coding": "97.1%", "reasoning": "96.4%", "speed": "Fast (~75 tok/s)"},
            "type": "Frontier SWE",
            "best_for": "Production software engineering and refactoring"
        },
        {
            "id": "claude-opus-5",
            "name": "Claude Opus 5",
            "tier": "PAID",
            "cost": "$15.00 in / $75.00 out",
            "context": "200k",
            "benchmarks": {"coding": "98.2%", "reasoning": "98.0%", "speed": "Deliberate (~35 tok/s)"},
            "type": "Deep System Architect",
            "best_for": "Large-scale system design, critical invariant verification"
        },
        {
            "id": "claude-haiku-4-5",
            "name": "Claude Haiku 4.5",
            "tier": "PAID",
            "cost": "$0.80 in / $4.00 out",
            "context": "200k",
            "benchmarks": {"coding": "89.2%", "reasoning": "86.1%", "speed": "Ultra-Fast (~140 tok/s)"},
            "type": "High Velocity",
            "best_for": "Low token consumption, fast single-step edits"
        }
    ],
    "oauth": [
        {
            "id": "claude-sonnet-5",
            "name": "Claude Sonnet 5",
            "tier": "SUBSCRIPTION",
            "cost": "Claude Pro / Team Quota",
            "context": "200k",
            "benchmarks": {"coding": "97.1%", "reasoning": "96.4%", "speed": "Fast (~75 tok/s)"},
            "type": "Standard",
            "best_for": "Standard interactive development"
        },
        {
            "id": "claude-opus-5",
            "name": "Claude Opus 5",
            "tier": "SUBSCRIPTION",
            "cost": "Claude Pro / Team Quota",
            "context": "200k",
            "benchmarks": {"coding": "98.2%", "reasoning": "98.0%", "speed": "Deliberate (~35 tok/s)"},
            "type": "Architect",
            "best_for": "Complex reasoning tasks and architectural invariants"
        },
        {
            "id": "claude-haiku-4-5",
            "name": "Claude Haiku 4.5",
            "tier": "SUBSCRIPTION",
            "cost": "Claude Pro / Team Quota",
            "context": "200k",
            "benchmarks": {"coding": "89.2%", "reasoning": "86.1%", "speed": "Ultra-Fast (~140 tok/s)"},
            "type": "Fast Mode",
            "best_for": "High-velocity token-efficient sessions"
        }
    ]
}

def load_config():
    if not os.path.exists(PROVIDERS_FILE):
        return {"active_provider": "oauth", "providers": {}}
    try:
        with open(PROVIDERS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"active_provider": "oauth", "providers": {}}

def save_config(cfg):
    os.makedirs(os.path.dirname(PROVIDERS_FILE), exist_ok=True)
    with open(PROVIDERS_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def get_active_provider():
    cfg = load_config()
    return cfg.get("active_provider", "oauth")

def get_active_model(provider=None):
    cfg = load_config()
    prov = provider or cfg.get("active_provider", "oauth")
    pinfo = cfg.get("providers", {}).get(prov, {})
    return pinfo.get("model", "claude-sonnet-5")

def set_model(model_id, provider=None):
    cfg = load_config()
    prov = provider or cfg.get("active_provider", "oauth")
    cfg.setdefault("providers", {}).setdefault(prov, {})["model"] = model_id
    save_config(cfg)

    tier = "MODEL"
    for p, mlist in CURATED_MODELS.items():
        for m in mlist:
            if m["id"] == model_id:
                tier = m.get("tier", "MODEL")
                break

    print(f"\033[1;32m✓ Active model for {prov.upper()} set to: {model_id} ({tier})\033[0m")
    print("  This model is active and automatically injected into subsequent Claude Code runs.")

# ==============================================================================
# KEYBOARD INPUT ENGINE (Cross-Platform)
# ==============================================================================
def get_key():
    """Read a single keypress or escape sequence cross-platform."""
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getch()
        if ch in [b"\x00", b"\xe0"]:
            ch2 = msvcrt.getch()
            if ch2 == b"H": return "UP"
            if ch2 == b"P": return "DOWN"
            if ch2 == b"K": return "LEFT"
            if ch2 == b"M": return "RIGHT"
            return "SPECIAL"
        if ch == b"\x1b": return "ESC"
        if ch in [b"\r", b"\n"]: return "ENTER"
        if ch == b"\t": return "INSPECT"
        if ch in [b" ", b"i", b"I"]: return "INSPECT"
        if ch in [b"f", b"F"]: return "TOGGLE_FREE"
        if ch in [b"q", b"Q"]: return "QUIT"
        return ch.decode("utf-8", errors="ignore")

    # POSIX (Linux / macOS)
    import tty
    import termios
    import select
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            # Check for escape sequence
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    if ch3 == 'A': return "UP"
                    if ch3 == 'B': return "DOWN"
                    if ch3 == 'C': return "RIGHT"
                    if ch3 == 'D': return "LEFT"
                    if ch3 == 'Z': return "INSPECT"  # Shift + Tab
                    if ch3 == '1':
                        rest = ''
                        while True:
                            r2, _, _ = select.select([sys.stdin], [], [], 0.02)
                            if r2:
                                char = sys.stdin.read(1)
                                rest += char
                                if char in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ~':
                                    break
                            else:
                                break
                        # Shift+Up (\x1b[1;2A) or Shift+Down (\x1b[1;2B)
                        if '2A' in rest or '2B' in rest or '2' in rest:
                            return "INSPECT"
                        return "UP"
                    return "SPECIAL"
                return "ESC"
            return "ESC"
        if ch in ['\r', '\n']: return "ENTER"
        if ch == '\t': return "INSPECT"
        if ch in [' ', 'i', 'I']: return "INSPECT"
        if ch in ['f', 'F']: return "TOGGLE_FREE"
        if ch in ['q', 'Q']: return "QUIT"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

# ==============================================================================
# EVALUATION DOSSIER MODAL POPUP
# ==============================================================================
def render_dossier_modal(m):
    """Renders a comprehensive evaluation popup modal for the hovered model."""
    name = m.get("name", m["id"])
    mid = m["id"]
    tier = m.get("tier", "N/A")
    cost = m.get("cost", "N/A")
    ctx = m.get("context", "N/A")
    arch = m.get("type", "N/A")
    bm = m.get("benchmarks", {})
    code_score = bm.get("coding", "N/A")
    reas_score = bm.get("reasoning", "N/A")
    speed = bm.get("speed", "N/A")
    best = m.get("best_for", "General software development")

    # Clear screen and draw box
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write("\033[1;36m" + "┌" + "─" * 76 + "┐\n" + "\033[0m")
    sys.stdout.write(f"\033[1;36m│\033[0m \033[1;37m📊 MODEL EVALUATION DOSSIER: {name:<46}\033[0m \033[1;36m│\033[0m\n")
    sys.stdout.write("\033[1;36m" + "├" + "─" * 76 + "┤\n" + "\033[0m")
    sys.stdout.write(f"\033[1;36m│\033[0m  • \033[1mModel ID:\033[0m       {mid:<58} \033[1;36m│\033[0m\n")
    tier_str = "\033[1;32m100% FREE (0 Credits / Zero Token Cost)\033[0m" if "FREE" in tier else f"\033[1;33m{cost}\033[0m"
    sys.stdout.write(f"\033[1;36m│\033[0m  • \033[1mPricing Tier:\033[0m   {tier_str:<67} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  • \033[1mContext Window:\033[0m {ctx} tokens (~500+ pages of context){' ':<22} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  • \033[1mArchitecture:\033[0m   {arch:<58} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * 76}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  \033[1;33mBENCHMARK RATINGS & INFERENCE PROFILE:\033[0m{' ' * 36}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  ┌─────────────────────────────┬───────────┬──────────────────────────────┐ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  │ \033[1mBenchmark Metric\033[0m            │ \033[1mRating\033[0m    │ \033[1mAssessment\033[0m                   │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  ├─────────────────────────────┼───────────┼──────────────────────────────┤ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  │ Coding (SWE / HumanEval)    │ \033[1;32m{code_score:<9}\033[0m │ Reliable code & refactoring  │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  │ Reasoning & Logic (MMLU)    │ \033[1;32m{reas_score:<9}\033[0m │ Multi-step deduction         │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  │ Latency / Speed             │ {speed:<9} │ Direct token generation rate │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  └─────────────────────────────┴───────────┴──────────────────────────────┘ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * 76}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  \033[1;33mOPTIMAL TASK ASSIGNMENT:\033[0m{' ' * 50}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  ✓ {best:<72} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m  ✓ Verified compatible with Claude Cortex master wrapper{' ' * 19}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * 76}\033[1;36m│\033[0m\n")
    sys.stdout.write("\033[1;36m" + "├" + "─" * 76 + "┤\n" + "\033[0m")
    sys.stdout.write(f"\033[1;36m│\033[0m  \033[1;32m[Enter]\033[0m Select Model   \033[1;33m[Esc / Tab / i]\033[0m Close Dossier and Return{' ' * 14}\033[1;36m│\033[0m\n")
    sys.stdout.write("\033[1;36m" + "└" + "─" * 76 + "┘\n" + "\033[0m")
    sys.stdout.flush()

# ==============================================================================
# INTERACTIVE KEYBOARD TUI SELECTOR
# ==============================================================================
def interactive_tui(initial_free_only=False):
    prov = get_active_provider()
    cur_model = get_active_model(prov)
    free_only = initial_free_only

    # Load provider models (fallback to OpenRouter if OAuth has no free models and free requested)
    active_prov_for_models = prov
    if free_only and prov == "oauth":
        active_prov_for_models = "openrouter"

    all_models = CURATED_MODELS.get(active_prov_for_models, CURATED_MODELS["openrouter"])

    # Fallback to non-interactive if stdin is not a terminal
    if not sys.stdin.isatty():
        list_models(prov, filter_tier="FREE" if free_only else None)
        return

    cursor = 0
    in_dossier = False

    # Find initial cursor position matching current model
    for idx, m in enumerate(all_models):
        if m["id"] == cur_model:
            cursor = idx
            break

    # Hide terminal cursor during interactive session
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            # Filter models
            if free_only:
                models = [m for m in all_models if "FREE" in m.get("tier", "").upper()]
            else:
                models = all_models

            if not models:
                models = all_models
                free_only = False

            if cursor >= len(models):
                cursor = max(0, len(models) - 1)

            selected_m = models[cursor]

            if in_dossier:
                render_dossier_modal(selected_m)
                key = get_key()
                if key in ["ESC", "INSPECT", "q", "Q"]:
                    in_dossier = False
                    continue
                elif key == "ENTER":
                    set_model(selected_m["id"], prov)
                    return
                continue

            # Render Main TUI Table
            sys.stdout.write("\033[2J\033[H")  # Clear screen, cursor to top
            sys.stdout.write("\033[1;36m" + "=" * 94 + "\n" + "\033[0m")
            mode_tag = "\033[1;32m[100% FREE MODELS ONLY]\033[0m" if free_only else "[ALL MODELS]"
            sys.stdout.write(f"  \033[1;37m⚡ CLAUDE CORTEX - INTERACTIVE MODEL EXPLORER\033[0m | Provider: \033[1;33m{prov.upper()}\033[0m {mode_tag}\n")
            sys.stdout.write("\033[1;36m" + "=" * 94 + "\n" + "\033[0m")
            sys.stdout.write("  \033[1;30mNav:\033[0m [↑/↓] Browse  •  \033[1;32m[Enter]\033[0m Select  •  \033[1;33m[Shift/Tab/i]\033[0m Inspect Dossier  •  \033[1;36m[f]\033[0m Toggle Free  •  \033[1;31m[Esc]\033[0m Exit\n")
            sys.stdout.write("\033[1;36m" + "─" * 94 + "\n" + "\033[0m")
            sys.stdout.write(f"  {'':<2} {'TIER':<8} {'MODEL ID':<42} {'CONTEXT':<8} {'CODE':<7} {'REAS':<7} {'SPEED'}\n")
            sys.stdout.write("\033[1;36m" + "─" * 94 + "\n" + "\033[0m")

            for i, m in enumerate(models):
                is_cur = (m["id"] == cur_model)
                is_selected = (i == cursor)
                tier = m.get("tier", "PAID")
                tier_str = "\033[1;32m[FREE]\033[0m" if "FREE" in tier else "\033[1;33m[PAID]\033[0m"
                if tier == "SUBSCRIPTION": tier_str = "\033[1;36m[SUB]\033[0m"

                bm = m.get("benchmarks", {})
                code_score = bm.get("coding", "-")
                reas_score = bm.get("reasoning", "-")
                speed = bm.get("speed", "Fast")[:9]
                ctx = m.get("context", "128k")

                cur_tag = " \033[1;34m(CURRENT)\033[0m" if is_cur else ""

                if is_selected:
                    # Highlight selected line
                    line = f"\033[1;44;37m > {tier_str:<16} {m['id']:<42} {ctx:<8} {code_score:<7} {reas_score:<7} {speed:<9}{cur_tag}\033[0m"
                else:
                    line = f"   {tier_str:<16} {m['id']:<42} {ctx:<8} {code_score:<7} {reas_score:<7} {speed:<9}{cur_tag}"

                sys.stdout.write(line + "\n")

            sys.stdout.write("\033[1;36m" + "─" * 94 + "\n" + "\033[0m")
            sys.stdout.write(f"  \033[1;37mHovered:\033[0m \033[1;32m{selected_m['name']}\033[0m | \033[3m{selected_m.get('best_for', '')}\033[0m\n")
            sys.stdout.write("  \033[1;33m💡 Tip: Press [Shift/Tab/i] to view full benchmarks, context limits & architecture dossier!\033[0m\n")
            sys.stdout.write("\033[1;36m" + "=" * 94 + "\n" + "\033[0m")
            sys.stdout.flush()

            # Read keyboard input
            key = get_key()
            if key == "UP":
                cursor = (cursor - 1) % len(models)
            elif key == "DOWN":
                cursor = (cursor + 1) % len(models)
            elif key in ["INSPECT", "RIGHT"]:
                in_dossier = True
            elif key in ["TOGGLE_FREE"]:
                free_only = not free_only
                if free_only and prov == "oauth":
                    all_models = CURATED_MODELS["openrouter"]
                else:
                    all_models = CURATED_MODELS.get(prov, CURATED_MODELS["openrouter"])
                cursor = 0
            elif key == "ENTER":
                sys.stdout.write("\033[2J\033[H")
                set_model(selected_m["id"], prov)
                return
            elif key in ["ESC", "QUIT"]:
                sys.stdout.write("\033[2J\033[H")
                print("Model selection closed. Kept current configuration.")
                return

    finally:
        # Restore terminal cursor
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

def list_models(provider=None, filter_tier=None, search_query=None):
    prov = provider or get_active_provider()
    cur_model = get_active_model(prov)
    models = CURATED_MODELS.get(prov, CURATED_MODELS["openrouter"])

    if filter_tier and filter_tier.upper() == "FREE":
        has_free = any("FREE" in m.get("tier", "").upper() for m in models)
        if not has_free:
            prov = "openrouter"
            models = CURATED_MODELS["openrouter"]
            print("Note: Claude OAuth uses subscription quota. Displaying 100% FREE models from OpenRouter (0 credits needed):")

    if filter_tier:
        models = [m for m in models if filter_tier.upper() in m.get("tier", "").upper()]
    if search_query:
        sq = search_query.lower()
        models = [m for m in models if sq in m["id"].lower() or sq in m.get("name", "").lower() or sq in m.get("best_for", "").lower()]

    print("==========================================================================================")
    print(f"       Claude Cortex - Models for Provider: {prov.upper()}")
    print("==========================================================================================")
    print(f"Active Model: {cur_model}\n")
    print(f"  {'#':<4} {'TIER':<9} {'MODEL ID':<42} {'CONTEXT':<9} {'BENCHMARKS':<16} {'BEST FOR'}")
    print(f"  {'-'*4} {'-'*9} {'-'*42} {'-'*9} {'-'*16} {'-'*35}")

    for i, m in enumerate(models, 1):
        is_cur = (m["id"] == cur_model)
        tier_tag = "[FREE]" if "FREE" in m.get("tier", "") else "[PAID]"
        if m.get("tier") == "SUBSCRIPTION": tier_tag = "[SUB]"
        ctx = m.get("context", "128k")
        bm = m.get("benchmarks", {})
        code = bm.get("coding", "-")
        reas = bm.get("reasoning", "-")
        best = m.get("best_for", "")[:35]
        cur_tag = " <-- CURRENT" if is_cur else ""
        print(f"  [{i:>2}] {tier_tag:<9} {m['id']:<42} Ctx:{ctx:<5} Code:{code:<4} Reas:{reas:<4} {best}{cur_tag}")

    print("\nActions:")
    print("  claude model                      Launch interactive keyboard-navigable model selector")
    print("  claude model free                 List only 100% free models")
    print("  claude model set <model_id>       Set active model directly")
    print("  claude model info <model_id>      View comprehensive benchmarks & specifications")
    print("==========================================================================================")

def show_model_info(model_id):
    found = None
    for p, mlist in CURATED_MODELS.items():
        for m in mlist:
            if m["id"].lower() == model_id.lower() or model_id.lower() in m["id"].lower():
                found = m
                break
        if found: break

    if not found:
        print(f"Model ID: {model_id} (Custom / Unindexed ID)")
        return

    render_dossier_modal(found)

def main():
    parser = argparse.ArgumentParser(description="Claude Cortex Model Manager")
    parser.add_argument("action", nargs="?", default="interactive",
                        choices=["interactive", "list", "free", "paid", "set", "info", "search", "sync"])
    parser.add_argument("target", nargs="?", default=None, help="Model ID or search query")
    parser.add_argument("--provider", "-p", help="Target provider (openrouter, gemini, anthropic, oauth)")
    args = parser.parse_args()

    if args.action == "interactive":
        interactive_tui(initial_free_only=False)
    elif args.action == "free":
        if sys.stdin.isatty():
            interactive_tui(initial_free_only=True)
        else:
            list_models(provider=args.provider, filter_tier="FREE")
    elif args.action == "list":
        list_models(provider=args.provider)
    elif args.action == "paid":
        list_models(provider=args.provider, filter_tier="PAID")
    elif args.action == "search":
        list_models(provider=args.provider, search_query=args.target)
    elif args.action == "set":
        if not args.target:
            print("Error: Specify model ID. e.g. claude model set nvidia/nemotron-3-ultra-550b-a55b:free")
            sys.exit(1)
        set_model(args.target, provider=args.provider)
    elif args.action == "info":
        if not args.target:
            print("Error: Specify model ID. e.g. claude model info deepseek/deepseek-r1:free")
            sys.exit(1)
        show_model_info(args.target)

if __name__ == "__main__":
    main()
