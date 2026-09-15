#!/usr/bin/env python3
"""
Claude Cortex - Interactive Model Explorer & Benchmarks Dossier v3.0
Full keyboard & mouse-driven live terminal TUI with arrow key navigation,
evaluation dossier popups (Shift/Tab/i), comprehensive token pricing breakdowns,
free vs paid filtering, and instant provider model switching.
"""

import os
import sys
import json
import argparse
import urllib.request
import time

PROVIDERS_FILE = os.path.expanduser("~/.claude/providers.json")
CACHE_FILE = os.path.expanduser("~/.claude/models_cache.json")

# ==============================================================================
# CURATED HIGH-PERFORMANCE MODEL CATALOG WITH DEEP PRICING & SPECIFICATIONS
# ==============================================================================
CURATED_MODELS = {
    "openrouter": [
        # --- 100% FREE MODELS ---
        {
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "name": "NVIDIA Nemotron 3 Ultra 550B",
            "tier": "FREE",
            "pricing": {
                "input": "$0.00 / 1M tokens (100% Free)",
                "output": "$0.00 / 1M tokens (100% Free)",
                "cache_read": "$0.00 / 1M tokens",
                "cache_write": "$0.00 / 1M tokens",
                "est_session": "$0.00 (Zero Credit Cost Unlimited)"
            },
            "context": "131k (~400 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "Supported (Synthetic CoT)",
                "budget": "Configurable (up to 16,384 tokens)"
            },
            "benchmarks": {"coding": "86.4%", "reasoning": "89.2%", "speed": "Fast (~85 tok/s, TTFT: ~350ms)"},
            "type": "Ultra-large MoE (NVIDIA NeMo)",
            "best_for": "General coding, complex multi-file logic, free prototyping"
        },
        {
            "id": "meta-llama/llama-3.3-70b-instruct:free",
            "name": "Meta Llama 3.3 70B Instruct",
            "tier": "FREE",
            "pricing": {
                "input": "$0.00 / 1M tokens (100% Free)",
                "output": "$0.00 / 1M tokens (100% Free)",
                "cache_read": "$0.00 / 1M tokens",
                "cache_write": "$0.00 / 1M tokens",
                "est_session": "$0.00 (Zero Credit Cost Unlimited)"
            },
            "context": "131k (~400 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "Instruct Tuned (Direct Deduction)",
                "budget": "N/A (Standard Latency)"
            },
            "benchmarks": {"coding": "86.1%", "reasoning": "88.6%", "speed": "Very Fast (~110 tok/s, TTFT: ~280ms)"},
            "type": "Dense Open Weights (Meta AI)",
            "best_for": "Full-stack code generation, refactoring, unit tests"
        },
        {
            "id": "deepseek/deepseek-r1:free",
            "name": "DeepSeek R1 (Reasoning)",
            "tier": "FREE",
            "pricing": {
                "input": "$0.00 / 1M tokens (100% Free)",
                "output": "$0.00 / 1M tokens (100% Free)",
                "cache_read": "$0.00 / 1M tokens",
                "cache_write": "$0.00 / 1M tokens",
                "est_session": "$0.00 (Zero Credit Cost Unlimited)"
            },
            "context": "164k (~500 pages)",
            "max_output": "16,384 tokens",
            "reasoning": {
                "support": "Pure Chain-of-Thought (Native Extended Thinking)",
                "budget": "Dynamic (up to 32,768 thinking tokens)"
            },
            "benchmarks": {"coding": "90.2%", "reasoning": "96.8%", "speed": "Deliberate (~45 tok/s, TTFT: ~1200ms)"},
            "type": "DeepSeek Sparse MoE with Native CoT RL",
            "best_for": "Deep algorithmic debugging, mathematics, intricate edge cases"
        },
        {
            "id": "qwen/qwen-2.5-coder-32b-instruct:free",
            "name": "Qwen 2.5 Coder 32B Instruct",
            "tier": "FREE",
            "pricing": {
                "input": "$0.00 / 1M tokens (100% Free)",
                "output": "$0.00 / 1M tokens (100% Free)",
                "cache_read": "$0.00 / 1M tokens",
                "cache_write": "$0.00 / 1M tokens",
                "est_session": "$0.00 (Zero Credit Cost Unlimited)"
            },
            "context": "32k (~100 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "Code Specialist Optimization",
                "budget": "N/A (Direct Code Synthesis)"
            },
            "benchmarks": {"coding": "92.8%", "reasoning": "84.5%", "speed": "Ultra-Fast (~140 tok/s, TTFT: ~210ms)"},
            "type": "Code Specialist Dense LLM",
            "best_for": "Pure code implementation, fast syntax fixes, scaffolding"
        },
        {
            "id": "google/gemini-2.0-flash-exp:free",
            "name": "Google Gemini 2.0 Flash Exp",
            "tier": "FREE",
            "pricing": {
                "input": "$0.00 / 1M tokens (100% Free)",
                "output": "$0.00 / 1M tokens (100% Free)",
                "cache_read": "$0.00 / 1M tokens",
                "cache_write": "$0.00 / 1M tokens",
                "est_session": "$0.00 (Zero Credit Cost Unlimited)"
            },
            "context": "1,048k (~3,000 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "Multimodal Flash Reasoning",
                "budget": "Adaptive"
            },
            "benchmarks": {"coding": "84.2%", "reasoning": "86.1%", "speed": "Ultra-Fast (~150 tok/s, TTFT: ~200ms)"},
            "type": "Multimodal Flash Transformer",
            "best_for": "Huge codebases, 1M context analysis, high velocity"
        },
        {
            "id": "mistralai/mistral-small-24b-instruct-2501:free",
            "name": "Mistral Small 24B Instruct",
            "tier": "FREE",
            "pricing": {
                "input": "$0.00 / 1M tokens (100% Free)",
                "output": "$0.00 / 1M tokens (100% Free)",
                "cache_read": "$0.00 / 1M tokens",
                "cache_write": "$0.00 / 1M tokens",
                "est_session": "$0.00 (Zero Credit Cost Unlimited)"
            },
            "context": "32k (~100 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "Instruct Tuned",
                "budget": "N/A (Minimal Latency)"
            },
            "benchmarks": {"coding": "81.5%", "reasoning": "83.0%", "speed": "Ultra-Fast (~130 tok/s, TTFT: ~220ms)"},
            "type": "Compact Instruct Transformer",
            "best_for": "Quick CLI tasks, low overhead scripting, quick queries"
        },
        # --- PAID FRONTIER MODELS ---
        {
            "id": "anthropic/claude-3.7-sonnet",
            "name": "Claude 3.7 Sonnet (Hybrid Thinking)",
            "tier": "PAID",
            "pricing": {
                "input": "$3.00 / 1M tokens",
                "output": "$15.00 / 1M tokens",
                "cache_read": "$0.30 / 1M tokens (90% discount on cache hit)",
                "cache_write": "$3.75 / 1M tokens",
                "est_session": "$0.12 - $0.35 (Cortex OT-ACR Optimized)"
            },
            "context": "200k (~600 pages)",
            "max_output": "64,000 tokens",
            "reasoning": {
                "support": "Extended Hybrid Thinking (effort: low, med, high, max)",
                "budget": "Configurable (up to 64,000 tokens)"
            },
            "benchmarks": {"coding": "96.2%", "reasoning": "95.4%", "speed": "Fast (~75 tok/s, TTFT: ~420ms)"},
            "type": "Anthropic Frontier Hybrid Autoregressive Transformer",
            "best_for": "Production software engineering, architecture, critical systems"
        },
        {
            "id": "anthropic/claude-3.5-haiku",
            "name": "Claude 3.5 Haiku",
            "tier": "PAID",
            "pricing": {
                "input": "$0.80 / 1M tokens",
                "output": "$4.00 / 1M tokens",
                "cache_read": "$0.08 / 1M tokens (90% discount on cache hit)",
                "cache_write": "$1.00 / 1M tokens",
                "est_session": "$0.03 - $0.08 (Cortex OT-ACR Optimized)"
            },
            "context": "200k (~600 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "High Velocity (Direct Generation)",
                "budget": "N/A (Sub-second responses)"
            },
            "benchmarks": {"coding": "88.4%", "reasoning": "85.2%", "speed": "Ultra-Fast (~140 tok/s, TTFT: ~190ms)"},
            "type": "High Velocity Dense Transformer",
            "best_for": "Lightning-fast iteration, linting, minimal token cost"
        },
        {
            "id": "deepseek/deepseek-chat",
            "name": "DeepSeek V3 (Chat)",
            "tier": "PAID",
            "pricing": {
                "input": "$0.14 / 1M tokens",
                "output": "$0.28 / 1M tokens",
                "cache_read": "$0.014 / 1M tokens (90% discount)",
                "cache_write": "$0.14 / 1M tokens",
                "est_session": "$0.01 - $0.03 (Ultra Value)"
            },
            "context": "64k (~200 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "Instruct Multi-Head Latent Attention",
                "budget": "Standard"
            },
            "benchmarks": {"coding": "90.1%", "reasoning": "90.0%", "speed": "Fast (~70 tok/s, TTFT: ~320ms)"},
            "type": "Ultra-Value Frontier MoE (DeepSeek V3)",
            "best_for": "Near-frontier performance at 1/10th the cost"
        },
        {
            "id": "openai/gpt-4o",
            "name": "OpenAI GPT-4o",
            "tier": "PAID",
            "pricing": {
                "input": "$2.50 / 1M tokens",
                "output": "$10.00 / 1M tokens",
                "cache_read": "$1.25 / 1M tokens (50% discount)",
                "cache_write": "$2.50 / 1M tokens",
                "est_session": "$0.15 - $0.40 (Standard API)"
            },
            "context": "128k (~400 pages)",
            "max_output": "16,384 tokens",
            "reasoning": {
                "support": "Omni Multimodal Autoregressive",
                "budget": "Configurable"
            },
            "benchmarks": {"coding": "90.2%", "reasoning": "91.8%", "speed": "Fast (~80 tok/s, TTFT: ~360ms)"},
            "type": "Omni Multimodal Transformer",
            "best_for": "Multimodal analysis, cross-language parity, general tools"
        }
    ],
    "gemini": [
        {
            "id": "gemini-2.5-pro",
            "name": "Google Gemini 2.5 Pro",
            "tier": "FREE / PAID",
            "pricing": {
                "input": "Free Tier (Google AI Studio) / $1.25 per 1M",
                "output": "Free Tier (Google AI Studio) / $5.00 per 1M",
                "cache_read": "$0.31 / 1M tokens",
                "cache_write": "$1.25 / 1M tokens",
                "est_session": "$0.00 (Free Quota) or ~$0.08 / session"
            },
            "context": "2,097k (~6,000 pages - Massive Codebases)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "Thinking / System Reasoning Pro",
                "budget": "Automatic / Configurable"
            },
            "benchmarks": {"coding": "89.4%", "reasoning": "93.1%", "speed": "Balanced (~60 tok/s, TTFT: ~550ms)"},
            "type": "Google DeepMind Multimodal Sparse MoE",
            "best_for": "Huge repository analysis (entire repos up to 2M tokens), architecture"
        },
        {
            "id": "gemini-2.0-flash",
            "name": "Google Gemini 2.0 Flash",
            "tier": "FREE / PAID",
            "pricing": {
                "input": "Free Tier (Google AI Studio) / $0.10 per 1M",
                "output": "Free Tier (Google AI Studio) / $0.40 per 1M",
                "cache_read": "$0.025 / 1M tokens",
                "cache_write": "$0.10 / 1M tokens",
                "est_session": "$0.00 (Free Quota) or ~$0.01 / session"
            },
            "context": "1,048k (~3,000 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "High-Throughput Flash (Sub-second)",
                "budget": "N/A"
            },
            "benchmarks": {"coding": "84.2%", "reasoning": "86.4%", "speed": "Ultra-Fast (~160 tok/s, TTFT: ~180ms)"},
            "type": "High-Throughput Multimodal Flash",
            "best_for": "Rapid automated workflows, high-frequency queries, script generation"
        },
        {
            "id": "gemini-2.0-flash-thinking-exp",
            "name": "Gemini 2.0 Flash Thinking Exp",
            "tier": "FREE",
            "pricing": {
                "input": "$0.00 (Google AI Studio Experimental)",
                "output": "$0.00 (Google AI Studio Experimental)",
                "cache_read": "$0.00",
                "cache_write": "$0.00",
                "est_session": "$0.00 (Free Experimental)"
            },
            "context": "1,048k (~3,000 pages)",
            "max_output": "65,536 tokens",
            "reasoning": {
                "support": "Deep Flash Chain-of-Thought (Visible Thinking Process)",
                "budget": "Dynamic (up to 64,000 thinking tokens)"
            },
            "benchmarks": {"coding": "88.6%", "reasoning": "94.2%", "speed": "Fast (~80 tok/s, TTFT: ~450ms)"},
            "type": "Reasoning Flash with Native CoT",
            "best_for": "Deep mathematical deduction and algorithmic checks at zero cost"
        }
    ],
    "anthropic": [
        {
            "id": "claude-sonnet-5",
            "name": "Claude Sonnet 5",
            "tier": "PAID",
            "pricing": {
                "input": "$3.00 / 1M tokens",
                "output": "$15.00 / 1M tokens",
                "cache_read": "$0.30 / 1M tokens (90% discount on cache hit)",
                "cache_write": "$3.75 / 1M tokens",
                "est_session": "$0.15 - $0.35 (Cortex Lean System Prompt)"
            },
            "context": "200k (~600 pages)",
            "max_output": "64,000 tokens",
            "reasoning": {
                "support": "Adaptive Extended Thinking (effort: low, med, high, max)",
                "budget": "Up to 64,000 thinking tokens"
            },
            "benchmarks": {"coding": "97.1%", "reasoning": "96.4%", "speed": "Fast (~75 tok/s, TTFT: ~400ms)"},
            "type": "Anthropic Frontier SWE Transformer",
            "best_for": "Production software engineering and refactoring"
        },
        {
            "id": "claude-opus-5",
            "name": "Claude Opus 5",
            "tier": "PAID",
            "pricing": {
                "input": "$15.00 / 1M tokens",
                "output": "$75.00 / 1M tokens",
                "cache_read": "$1.50 / 1M tokens (90% discount on cache hit)",
                "cache_write": "$18.75 / 1M tokens",
                "est_session": "$0.75 - $1.80 (Cortex Managed)"
            },
            "context": "200k (~600 pages)",
            "max_output": "32,000 tokens",
            "reasoning": {
                "support": "Deep System Architectural Reasoner",
                "budget": "Configurable (up to 32,000 tokens)"
            },
            "benchmarks": {"coding": "98.2%", "reasoning": "98.0%", "speed": "Deliberate (~35 tok/s, TTFT: ~800ms)"},
            "type": "Ultra-Large Frontier Reasoning Model",
            "best_for": "Large-scale system design, critical invariant verification"
        },
        {
            "id": "claude-haiku-4-5",
            "name": "Claude Haiku 4.5",
            "tier": "PAID",
            "pricing": {
                "input": "$0.80 / 1M tokens",
                "output": "$4.00 / 1M tokens",
                "cache_read": "$0.08 / 1M tokens (90% discount)",
                "cache_write": "$1.00 / 1M tokens",
                "est_session": "$0.03 - $0.06 (High Velocity)"
            },
            "context": "200k (~600 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "High Velocity Direct Output",
                "budget": "N/A"
            },
            "benchmarks": {"coding": "89.2%", "reasoning": "86.1%", "speed": "Ultra-Fast (~140 tok/s, TTFT: ~190ms)"},
            "type": "High Velocity Dense Transformer",
            "best_for": "Low token consumption, fast single-step edits, turbo mode"
        }
    ],
    "oauth": [
        {
            "id": "claude-sonnet-5",
            "name": "Claude Sonnet 5",
            "tier": "SUBSCRIPTION",
            "pricing": {
                "input": "Claude Pro / Team Subscription Quota",
                "output": "Claude Pro / Team Subscription Quota",
                "cache_read": "Server-side KV-Cache (90% quota discount)",
                "cache_write": "Standard Quota",
                "est_session": "Included in Flat Monthly Subscription"
            },
            "context": "200k (~600 pages)",
            "max_output": "64,000 tokens",
            "reasoning": {
                "support": "Adaptive Extended Thinking (effort: low, med, high, max)",
                "budget": "Up to 64,000 thinking tokens"
            },
            "benchmarks": {"coding": "97.1%", "reasoning": "96.4%", "speed": "Fast (~75 tok/s, TTFT: ~400ms)"},
            "type": "Standard Official Subscription Model",
            "best_for": "Standard interactive development, everyday coding"
        },
        {
            "id": "claude-opus-5",
            "name": "Claude Opus 5",
            "tier": "SUBSCRIPTION",
            "pricing": {
                "input": "Claude Pro / Team Subscription Quota (Higher Burn Rate)",
                "output": "Claude Pro / Team Subscription Quota",
                "cache_read": "Server-side KV-Cache (90% quota discount)",
                "cache_write": "Standard Quota",
                "est_session": "Included in Subscription (Consumes Quota ~3x Faster)"
            },
            "context": "200k (~600 pages)",
            "max_output": "32,000 tokens",
            "reasoning": {
                "support": "Deep Architectural Reasoning",
                "budget": "Configurable (up to 32,000 tokens)"
            },
            "benchmarks": {"coding": "98.2%", "reasoning": "98.0%", "speed": "Deliberate (~35 tok/s, TTFT: ~800ms)"},
            "type": "Architect Model",
            "best_for": "Complex reasoning tasks and architectural invariants"
        },
        {
            "id": "claude-haiku-4-5",
            "name": "Claude Haiku 4.5",
            "tier": "SUBSCRIPTION",
            "pricing": {
                "input": "Claude Pro / Team Subscription Quota (Minimal Burn Rate)",
                "output": "Claude Pro / Team Subscription Quota",
                "cache_read": "Server-side KV-Cache (90% quota discount)",
                "cache_write": "Standard Quota",
                "est_session": "Included in Subscription (Virtually Unlimited Usage)"
            },
            "context": "200k (~600 pages)",
            "max_output": "8,192 tokens",
            "reasoning": {
                "support": "Fast Direct Generation",
                "budget": "N/A"
            },
            "benchmarks": {"coding": "89.2%", "reasoning": "86.1%", "speed": "Ultra-Fast (~140 tok/s, TTFT: ~190ms)"},
            "type": "Fast Mode",
            "best_for": "High-velocity token-efficient sessions, turbo mode"
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

def save_config(data):
    os.makedirs(os.path.dirname(PROVIDERS_FILE), exist_ok=True)
    with open(PROVIDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_active_provider():
    cfg = load_config()
    return cfg.get("active_provider", "oauth")

def get_active_model(provider_name=None):
    cfg = load_config()
    prov = provider_name or cfg.get("active_provider", "oauth")
    pinfo = cfg.get("providers", {}).get(prov, {})
    return pinfo.get("model", "claude-sonnet-5")

def set_model(model_id, provider_name=None):
    cfg = load_config()
    prov = provider_name or cfg.get("active_provider", "oauth")
    if prov not in cfg.get("providers", {}):
        cfg.setdefault("providers", {})[prov] = {}
    cfg["providers"][prov]["model"] = model_id
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
# UNBUFFERED POSIX RAW INPUT ENGINE WITH SGR MOUSE TRACKING
# ==============================================================================
def get_key():
    """
    Reads keypress or escape sequence cross-platform using unbuffered OS read.
    Eliminates TextIOWrapper chunk-buffering bugs and supports full SGR mouse events.
    """
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getch()
        if ch in [b"\x00", b"\xe0"]:
            ch2 = msvcrt.getch()
            if ch2 == b"H": return "UP"
            if ch2 == b"P": return "DOWN"
            if ch2 == b"K": return "LEFT"
            if ch2 == b"M": return "RIGHT"
            if ch2 in [b"I", b"G"]: return "PAGE_UP"
            if ch2 in [b"Q", b"O"]: return "PAGE_DOWN"
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
        seq = os.read(fd, 1)
        if not seq:
            return None

        if seq == b"\x1b":
            # Check for escape sequence trailing bytes
            r, _, _ = select.select([fd], [], [], 0.08)
            if r:
                more = os.read(fd, 63)
                seq += more
            else:
                return "ESC"

        # Arrow keys: CSI (\x1b[) and SS3 (\x1bO) sequences
        if b"[A" in seq or b"OA" in seq: return "UP"
        if b"[B" in seq or b"OB" in seq: return "DOWN"
        if b"[C" in seq or b"OC" in seq: return "RIGHT"
        if b"[D" in seq or b"OD" in seq: return "LEFT"
        if b"[5~" in seq or b"[5" in seq: return "PAGE_UP"
        if b"[6~" in seq or b"[6" in seq: return "PAGE_DOWN"
        if b"[H" in seq or b"[1~" in seq: return "HOME"
        if b"[F" in seq or b"[4~" in seq: return "END"
        if b"[Z" in seq: return "INSPECT"  # Shift + Tab

        # SGR Extended Mouse Mode: \x1b[<btn;col;rowM (press) or \x1b[<btn;col;rowm (release)
        m = re.search(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])", seq)
        if m:
            btn = int(m.group(1))
            col = int(m.group(2))
            row = int(m.group(3))
            is_press = (m.group(4) == b"M")
            if btn == 64: return "SCROLL_UP"
            if btn == 65: return "SCROLL_DOWN"
            if btn == 0 and is_press: return ("MOUSE_CLICK", col, row)
            if btn == 2 and is_press: return "INSPECT"
            return "MOUSE_EVENT"

        if seq == b"\x1b": return "ESC"
        if seq in (b"\r", b"\n"): return "ENTER"
        if seq == b"\t": return "INSPECT"
        if seq in (b" ", b"i", b"I"): return "INSPECT"
        if seq in (b"j", b"J"): return "DOWN"
        if seq in (b"k", b"K"): return "UP"
        if seq in (b"l", b"L"): return "INSPECT"
        if seq in (b"h", b"H"): return "LEFT"
        if seq in (b"f", b"F"): return "TOGGLE_FREE"
        if seq in (b"q", b"Q"): return "QUIT"
        if seq == b"\x03": return "QUIT"  # Ctrl + C

        return seq.decode("utf-8", errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

# ==============================================================================
# EVALUATION DOSSIER MODAL POPUP WITH DEEP PRICING & SPECIFICATIONS
# ==============================================================================
def render_dossier_modal(m, current_index=1, total_count=1):
    """Renders a comprehensive evaluation popup modal for the hovered model."""
    name = m.get("name", m["id"])
    mid = m["id"]
    tier = m.get("tier", "N/A")
    ctx = m.get("context", "N/A")
    max_out = m.get("max_output", "8,192 tokens")
    arch = m.get("type", "N/A")
    bm = m.get("benchmarks", {})
    code_score = bm.get("coding", "N/A")
    reas_score = bm.get("reasoning", "N/A")
    speed = bm.get("speed", "N/A")
    best = m.get("best_for", "General software engineering")

    pricing = m.get("pricing", {})
    p_in = pricing.get("input", m.get("cost", "N/A"))
    p_out = pricing.get("output", "N/A")
    p_cache = pricing.get("cache_read", "N/A")
    p_sess = pricing.get("est_session", "N/A")

    reasoning_info = m.get("reasoning", {})
    r_supp = reasoning_info.get("support", "Standard")
    r_budg = reasoning_info.get("budget", "Configurable")

    # Clear screen and draw structured dossier
    sys.stdout.write("\033[2J\033[H")
    box_w = 80
    sys.stdout.write("\033[1;36m" + "┌" + "─" * box_w + "┐\n" + "\033[0m")
    header_title = f"📊 MODEL EVALUATION DOSSIER [{current_index}/{total_count}]: {name}"[:box_w - 2]
    sys.stdout.write(f"\033[1;36m│\033[0m \033[1;37m{header_title:<{box_w - 2}}\033[0m \033[1;36m│\033[0m\n")
    sys.stdout.write("\033[1;36m" + "├" + "─" * box_w + "┤\n" + "\033[0m")

    # General Identity
    sys.stdout.write(f"\033[1;36m│\033[0m  • \033[1mModel Identifier:\033[0m   {mid:<60} \033[1;36m│\033[0m\n")
    tier_color = "\033[1;32m" if "FREE" in tier else "\033[1;36m" if "SUB" in tier else "\033[1;33m"
    tier_label = f"{tier_color}[{tier}]\033[0m {arch}"[:70]
    sys.stdout.write(f"\033[1;36m│\033[0m  • \033[1mArchitecture/Tier:\033[0m  {tier_label:<70} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * box_w}\033[1;36m│\033[0m\n")

    # Section 1: Deep Pricing & Token Economy
    sys.stdout.write(f"\033[1;36m│\033[0m  \033[1;33m💰 COMPREHENSIVE PRICING & TOKEN ECONOMY:\033[0m{' ' * (box_w - 42)}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    ┌──────────────────────┬─────────────────────────────────────────────────┐ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    │ \033[1mToken Metric\033[0m         │ \033[1mRate / Cost Assessment\033[0m                          │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    ├──────────────────────┼─────────────────────────────────────────────────┤ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    │ Prompt / Input:      │ {p_in:<47} │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    │ Completion / Output: │ {p_out:<47} │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    │ Cache Read Hit Rate: │ {p_cache:<47} │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    │ 100-Turn Session Est:│ \033[1;32m{p_sess:<47}\033[0m │ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    └──────────────────────┴─────────────────────────────────────────────────┘ \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * box_w}\033[1;36m│\033[0m\n")

    # Section 2: Context Window & Generation Limits
    sys.stdout.write(f"\033[1;36m│\033[0m  \033[1;33m📏 CONTEXT WINDOW & CAPACITY:\033[0m{' ' * (box_w - 30)}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    • \033[1mInput Context Window:\033[0m  {ctx:<55} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    • \033[1mMax Single Generation:\033[0m {max_out:<55} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * box_w}\033[1;36m│\033[0m\n")

    # Section 3: Reasoning & Extended Thinking
    sys.stdout.write(f"\033[1;36m│\033[0m  \033[1;33m🧠 REASONING & EXTENDED THINKING PROFILE:\033[0m{' ' * (box_w - 42)}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    • \033[1mThinking Capability:\033[0m   {r_supp:<55} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    • \033[1mThinking Budget Cap:\033[0m   {r_budg:<55} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * box_w}\033[1;36m│\033[0m\n")

    # Section 4: Verified Benchmarks & Inference Speed
    sys.stdout.write(f"\033[1;36m│\033[0m  \033[1;33m⚡ FRONTIER BENCHMARKS & INFERENCE SPEED:\033[0m{' ' * (box_w - 42)}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    • \033[1mCoding (SWE-bench):\033[0m    \033[1;32m{code_score:<55}\033[0m \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    • \033[1mLogic (MATH/MMLU):\033[0m     \033[1;32m{reas_score:<55}\033[0m \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    • \033[1mInference Velocity:\033[0m    {speed:<55} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * box_w}\033[1;36m│\033[0m\n")

    # Section 5: Optimal Task Assignment
    sys.stdout.write(f"\033[1;36m│\033[0m  \033[1;33m🎯 OPTIMAL USE CASE:\033[0m{' ' * (box_w - 22)}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    ✓ {best[:box_w - 8]:<{box_w - 8}} \033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m    ✓ Protected by Claude Cortex OT-ACR Token Optimization{' ' * (box_w - 61)}\033[1;36m│\033[0m\n")
    sys.stdout.write(f"\033[1;36m│\033[0m{' ' * box_w}\033[1;36m│\033[0m\n")

    # Controls Footer
    sys.stdout.write("\033[1;36m" + "├" + "─" * box_w + "┤\n" + "\033[0m")
    footer_text = " [↑/↓/Wheel] Browse  •  [Enter] Select  •  [Esc/Tab/q] Close Dossier"
    sys.stdout.write(f"\033[1;36m│\033[0m\033[1;37m{footer_text:<{box_w}}\033[0m\033[1;36m│\033[0m\n")
    sys.stdout.write("\033[1;36m" + "└" + "─" * box_w + "┘\n" + "\033[0m")
    sys.stdout.flush()

# ==============================================================================
# INTERACTIVE KEYBOARD & MOUSE TUI SELECTOR
# ==============================================================================
def interactive_tui(initial_free_only=False):
    prov = get_active_provider()
    cur_model = get_active_model(prov)
    free_only = initial_free_only

    active_prov_for_models = prov
    if free_only and prov == "oauth":
        active_prov_for_models = "openrouter"

    all_models = CURATED_MODELS.get(active_prov_for_models, CURATED_MODELS["openrouter"])

    if not sys.stdin.isatty():
        list_models(prov, filter_tier="FREE" if free_only else None)
        return

    cursor = 0
    in_dossier = False

    for idx, m in enumerate(all_models):
        if m["id"] == cur_model:
            cursor = idx
            break

    # Enable alternate screen, hide cursor, and enable SGR mouse tracking
    sys.stdout.write("\033[?25l\033[?1000h\033[?1006h")
    sys.stdout.flush()

    try:
        while True:
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
                render_dossier_modal(selected_m, current_index=cursor + 1, total_count=len(models))
                key = get_key()
                if key in ["UP", "LEFT", "SCROLL_UP"]:
                    cursor = (cursor - 1) % len(models)
                    continue
                elif key in ["DOWN", "RIGHT", "SCROLL_DOWN"]:
                    cursor = (cursor + 1) % len(models)
                    continue
                elif key in ["ESC", "INSPECT", "q", "Q"]:
                    in_dossier = False
                    continue
                elif key == "ENTER":
                    sys.stdout.write("\033[2J\033[H")
                    set_model(selected_m["id"], prov)
                    return
                elif isinstance(key, tuple) and key[0] == "MOUSE_CLICK":
                    # Clicking anywhere in footer area closes or selects
                    row = key[2]
                    if row >= 22:
                        in_dossier = False
                    continue
                continue

            # Render Main TUI Table
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write("\033[1;36m" + "=" * 96 + "\n" + "\033[0m")
            mode_tag = "\033[1;32m[100% FREE MODELS ONLY]\033[0m" if free_only else "[ALL MODELS]"
            sys.stdout.write(f"  \033[1;37m⚡ CLAUDE CORTEX - INTERACTIVE MODEL EXPLORER\033[0m | Provider: \033[1;33m{prov.upper()}\033[0m {mode_tag}\n")
            sys.stdout.write("\033[1;36m" + "=" * 96 + "\n" + "\033[0m")
            sys.stdout.write("  \033[1;30mNav:\033[0m [↑/↓/Mouse] Browse  •  \033[1;32m[Enter/Click]\033[0m Select  •  \033[1;33m[Shift/Tab/i]\033[0m Inspect  •  \033[1;36m[f]\033[0m Free  •  \033[1;31m[Esc]\033[0m Exit\n")
            sys.stdout.write("\033[1;36m" + "─" * 96 + "\n" + "\033[0m")
            sys.stdout.write(f"  {'':<2} {'TIER':<8} {'MODEL ID':<42} {'CONTEXT':<8} {'CODE':<7} {'REAS':<7} {'SPEED'}\n")
            sys.stdout.write("\033[1;36m" + "─" * 96 + "\n" + "\033[0m")

            table_start_row = 7

            for i, m in enumerate(models):
                is_cur = (m["id"] == cur_model)
                is_selected = (i == cursor)
                tier = m.get("tier", "PAID")
                tier_str = "\033[1;32m[FREE]\033[0m" if "FREE" in tier else "\033[1;33m[PAID]\033[0m"
                if tier == "SUBSCRIPTION": tier_str = "\033[1;36m[SUB]\033[0m"

                bm = m.get("benchmarks", {})
                code_score = bm.get("coding", "-")[:6]
                reas_score = bm.get("reasoning", "-")[:6]
                speed = bm.get("speed", "Fast")[:9]
                ctx = m.get("context", "128k")[:8]

                cur_tag = " \033[1;34m(CURRENT)\033[0m" if is_cur else ""

                if is_selected:
                    line = f"\033[1;44;37m > {tier_str:<16} {m['id']:<42} {ctx:<8} {code_score:<7} {reas_score:<7} {speed:<9}{cur_tag}\033[0m"
                else:
                    line = f"   {tier_str:<16} {m['id']:<42} {ctx:<8} {code_score:<7} {reas_score:<7} {speed:<9}{cur_tag}"

                sys.stdout.write(line + "\n")

            sys.stdout.write("\033[1;36m" + "─" * 96 + "\n" + "\033[0m")
            pricing_brief = selected_m.get("pricing", {}).get("est_session", selected_m.get("cost", ""))
            sys.stdout.write(f"  \033[1;37mHovered:\033[0m \033[1;32m{selected_m['name']}\033[0m | \033[1;33m{pricing_brief}\033[0m\n")
            sys.stdout.write("  \033[1;33m💡 Tip: Press [Shift/Tab/i] or Click to view deep pricing, token economy & benchmarks!\033[0m\n")
            sys.stdout.write("\033[1;36m" + "=" * 96 + "\n" + "\033[0m")
            sys.stdout.flush()

            # Read keyboard or mouse input
            key = get_key()

            if key in ["UP", "SCROLL_UP"]:
                cursor = (cursor - 1) % len(models)
            elif key in ["DOWN", "SCROLL_DOWN"]:
                cursor = (cursor + 1) % len(models)
            elif key in ["PAGE_UP", "HOME"]:
                cursor = 0
            elif key in ["PAGE_DOWN", "END"]:
                cursor = max(0, len(models) - 1)
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
            elif isinstance(key, tuple) and key[0] == "MOUSE_CLICK":
                col, row = key[1], key[2]
                # Check if click is on a model row
                row_idx = row - table_start_row
                if 0 <= row_idx < len(models):
                    if row_idx == cursor:
                        # Double click on selected model opens dossier
                        in_dossier = True
                    else:
                        cursor = row_idx
                # Check if clicking footer controls
                elif row >= table_start_row + len(models) + 1:
                    if col < 25:
                        # Select
                        sys.stdout.write("\033[2J\033[H")
                        set_model(selected_m["id"], prov)
                        return
                    elif col < 50:
                        # Inspect
                        in_dossier = True
                    elif col < 75:
                        # Free toggle
                        free_only = not free_only
                        cursor = 0
                    else:
                        # Exit
                        sys.stdout.write("\033[2J\033[H")
                        print("Model selection closed. Kept current configuration.")
                        return

    finally:
        # Restore cursor and disable mouse tracking
        sys.stdout.write("\033[?1000l\033[?1006l\033[?25h")
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
    print(f"  {'#':<4} {'TIER':<9} {'MODEL ID':<42} {'CONTEXT':<9} {'BENCHMARKS':<16} {'PRICING / BEST FOR'}")
    print(f"  {'-'*4} {'-'*9} {'-'*42} {'-'*9} {'-'*16} {'-'*35}")

    for i, m in enumerate(models, 1):
        is_cur = (m["id"] == cur_model)
        tier_tag = "[FREE]" if "FREE" in m.get("tier", "") else "[PAID]"
        if m.get("tier") == "SUBSCRIPTION": tier_tag = "[SUB]"
        ctx = m.get("context", "128k")
        bm = m.get("benchmarks", {})
        code = bm.get("coding", "-")
        reas = bm.get("reasoning", "-")
        p_brief = m.get("pricing", {}).get("est_session", m.get("best_for", ""))[:35]
        cur_tag = " <-- CURRENT" if is_cur else ""
        print(f"  [{i:>2}] {tier_tag:<9} {m['id']:<42} Ctx:{ctx:<5} Code:{code:<4} Reas:{reas:<4} {p_brief}{cur_tag}")

    print("\nActions:")
    print("  claude model                      Launch interactive keyboard & mouse model explorer")
    print("  claude model free                 List only 100% free models")
    print("  claude model set <model_id>       Set active model directly")
    print("  claude model info <model_id>      View comprehensive benchmarks, token pricing & dossier")
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
        print(f"Error: Model '{model_id}' not found in catalog.")
        print("Run 'claude model list' to see all supported models.")
        return

    render_dossier_modal(found, 1, 1)

def main():
    parser = argparse.ArgumentParser(description="Claude Cortex Model Explorer & Selector v3.0")
    parser.add_argument("action", nargs="?", default="tui",
                        choices=["tui", "list", "free", "set", "use", "info", "search"])
    parser.add_argument("model_id", nargs="?", default=None, help="Model ID for set / info commands")
    parser.add_argument("--provider", "-p", help="Filter by provider")
    args = parser.parse_args()

    if args.action == "tui":
        interactive_tui(initial_free_only=False)
    elif args.action == "free":
        interactive_tui(initial_free_only=True)
    elif args.action == "list":
        list_models(provider=args.provider)
    elif args.action in ["set", "use"]:
        if not args.model_id:
            interactive_tui()
            return
        set_model(args.model_id, provider_name=args.provider)
    elif args.action == "info":
        if not args.model_id:
            interactive_tui()
            return
        show_model_info(args.model_id)
    elif args.action == "search":
        list_models(provider=args.provider, search_query=args.model_id)

if __name__ == "__main__":
    main()
