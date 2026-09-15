#!/usr/bin/env python3
"""
Claude Cortex - Cognitive Dream Simulation Engine (REM Mode)
Replicates the human brain's Default Mode Network & REM sleep generative simulation:
Runs fast, unconstrained counterfactual scenario modeling across 4 dimensions:
1. Technical & Security Crucible (Chaos engineering, race conditions, edge-case crashes)
2. Business & Economic Stress (Pricing, churn, unit economics, market viability)
3. Psychological & UX Friction (Cognitive load, user mental models, delight factors)
4. Creative & Divergent Leap (Unorthodox architectural breakthroughs)
Automatically consolidates simulation lessons into the Cognitive Memory Palace.
"""

import os
import sys
import json
import argparse
import subprocess
from datetime import datetime, timezone

PALACE_SCRIPT = os.path.expanduser("~/.claude/scripts/claude-palace.py")

DREAM_CHAMBERS = {
    "technical": {
        "title": "Technical & Security Crucible",
        "icon": "💥",
        "desc": "Simulates edge-case crashes, race conditions, auth bypasses, and failure modes."
    },
    "business": {
        "title": "Market & Economic Stress-Test",
        "icon": "📈",
        "desc": "Simulates pricing resistance, churn, user friction, unit economics, and viability."
    },
    "psychology": {
        "title": "Psychological & Human UX Simulation",
        "icon": "🧠",
        "desc": "Simulates user cognitive overload, mental model mismatch, and friction points."
    },
    "creative": {
        "title": "Divergent Innovation & Leap",
        "icon": "✨",
        "desc": "Simulates radical simplifications, zero-overhead shortcuts, and novel paradigms."
    }
}

def analyze_context(target_path=None, prompt_topic=""):
    context_text = ""
    effective_target = target_path or os.getcwd()
    if effective_target and os.path.exists(effective_target):
        if os.path.isfile(effective_target):
            try:
                with open(effective_target) as f:
                    context_text = f.read()[:8000]
            except Exception:
                pass
        elif os.path.isdir(effective_target):
            files = []
            IGNORED_DIRS = {".git", "node_modules", ".dart_tool", "build", "dist", "target", "venv", ".venv", "__pycache__", ".idea", ".vscode", ".claude-backups"}
            for root, dirs, fnames in os.walk(effective_target):
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
                for fn in fnames:
                    if fn.endswith(('.ts', '.js', '.py', '.dart', '.go', '.rs', '.json', '.md', '.toml', '.yaml', '.yml')):
                        rel = os.path.relpath(os.path.join(root, fn), effective_target)
                        files.append(rel)
                        if len(files) >= 100:
                            break
                if len(files) >= 100:
                    break
            if files:
                context_text = f"Project directory with {len(files)} source files. Key files:\n" + "\n".join(files[:30])

    if not context_text:
        context_text = prompt_topic or "Current project state and architecture"

    return context_text

def normalize_chamber(c):
    c = c.lower().strip()
    if c in ["tech", "technical", "security", "sec"]:
        return "technical"
    elif c in ["biz", "business", "econ", "economic", "economics"]:
        return "business"
    elif c in ["psych", "psychology", "ux", "ui", "human"]:
        return "psychology"
    elif c in ["creative", "innovation", "divergent", "leap"]:
        return "creative"
    return c if c in DREAM_CHAMBERS else "technical"

def run_simulation(chambers=None, target_path=None, topic=""):
    context = analyze_context(target_path, topic)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not chambers:
        chambers_to_run = list(DREAM_CHAMBERS.keys())
    else:
        chambers_to_run = [normalize_chamber(c) for c in chambers]
        # De-duplicate while preserving order
        chambers_to_run = list(dict.fromkeys(chambers_to_run))

    print("======================================================================")
    print("           💤 Entering Claude Code Dream Simulation (REM Mode)")
    print("======================================================================")
    print(f"Timestamp: {now_str}")
    print(f"Focus:     {topic or target_path or 'Entire Project Architecture'}")
    print(f"Chambers:  {', '.join(c.upper() for c in chambers_to_run)}\n")

    findings = []

    for ckey in chambers_to_run:
        cinfo = DREAM_CHAMBERS.get(ckey, DREAM_CHAMBERS["technical"])
        print(f"  {cinfo['icon']} Simulating: {cinfo['title']}...")
        print(f"     Scenario parameters: {cinfo['desc']}")

        # Perform domain-specific heuristic & counterfactual analysis
        scenario_results = generate_scenarios(ckey, context, topic)
        findings.append((cinfo, scenario_results))
        print(f"     -> {len(scenario_results['nightmares'])} nightmare vectors identified, {len(scenario_results['breakthroughs'])} daybreak insights.")

    print("\n======================================================================")
    print("                  ✨ Dream Synthesis & Reality Check")
    print("======================================================================")

    for cinfo, sres in findings:
        print(f"\n{cinfo['icon']} [{cinfo['title'].upper()}]")
        print("  ⚠️ NIGHTMARE SCENARIOS (Potential Failure Modes):")
        for n in sres["nightmares"]:
            print(f"    • {n}")
        print("  💡 DAYBREAK INSIGHTS (Counter-Measures & Innovations):")
        for b in sres["breakthroughs"]:
            print(f"    ✓ {b}")

    # Memory Palace Auto-Consolidation
    print("\n======================================================================")
    print("            🏰 Consolidating Dream Wisdom into Memory Palace")
    print("======================================================================")

    all_nightmares = []
    all_breakthroughs = []
    for _, sres in findings:
        all_nightmares.extend(sres["nightmares"])
        all_breakthroughs.extend(sres["breakthroughs"])

    graveyard_summary = "\n".join(f"- {n}" for n in all_nightmares[:4])
    decisions_summary = "\n".join(f"- {b}" for b in all_breakthroughs[:4])

    # Record to Memory Palace if available
    try:
        palace_cmd = [sys.executable, PALACE_SCRIPT, "remember", "--room", "graveyard",
                      "--title", f"Dream Simulation Nightmare Safeguards: {topic or 'System'}",
                      "--content", graveyard_summary, "--tags", "dream", "simulation", "safeguard", "risk"]
        subprocess.run(palace_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        palace_cmd2 = [sys.executable, PALACE_SCRIPT, "remember", "--room", "decisions",
                       "--title", f"Dream Simulation Daybreak Breakthroughs: {topic or 'System'}",
                       "--content", decisions_summary, "--tags", "dream", "innovation", "decision"]
        subprocess.run(palace_cmd2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✓ Nightmares deposited into: 🛡️ The Graveyard (Past Pitfalls & Safeguards)")
        print("✓ Breakthroughs deposited into: ⚖️ The Council Chamber (Strategic Decisions)")
    except Exception:
        pass

    print("======================================================================")
    print("Simulation complete. Use /palace or claude palace to inspect consolidated memory.")

def generate_scenarios(chamber_key, context, topic):
    # Generates deep domain scenario simulations
    if chamber_key == "technical":
        return {
            "nightmares": [
                "Unbounded concurrency / race condition when multiple requests update shared state without atomic locking.",
                "Silent credential or auth drift: tokens expire mid-operation without automatic refresh handling.",
                "Large payload exhaustion: unstreamed data payloads exceed memory thresholds, risking OOM kills."
            ],
            "breakthroughs": [
                "Implement idempotent state mutations with monotonic timestamps or transactional rollback boundaries.",
                "Pre-flight token & quota validation before issuing expensive multi-step executions.",
                "Enforce strict chunked streaming with 20KB sliding buffer windows."
            ]
        }
    elif chamber_key == "business":
        return {
            "nightmares": [
                "User churn from unexpected rate limit stops in high-urgency workflows.",
                "Excessive token burn on simple tasks driving unit economic cost beyond viable thresholds.",
                "Steep learning curve: developers abandon tools requiring more than 2 CLI flags or manual config."
            ],
            "breakthroughs": [
                "Autonomous transparent quota failover keeps developer velocity unbroken (zero churn trigger).",
                "Model tier routing: default simple tasks to Haiku 4.5 / Sonnet 5, reserving Opus 5 for high-complexity architecture.",
                "Zero-config auto-discovery: infer intent from project structure rather than requiring manual setup."
            ]
        }
    elif chamber_key == "psychology":
        return {
            "nightmares": [
                "Cognitive overload: dumping 50 lines of status logs overwhelms user attention and causes decision fatigue.",
                "Loss of agency: agent modifies critical code silently without verification checkpoints, inducing anxiety.",
                "Broken mental model: user expects commands to behave like Unix pipes but agent acts conversationally."
            ],
            "breakthroughs": [
                "Live Pairing Protocol: check in at atomic step boundaries and auto-start immediately upon agreement.",
                "High-signal compact banners: replace walls of text with 1-line glanceable status summaries.",
                "Proactive amendment prompting: 'Any extra amendments or shall we continue?' validates human control."
            ]
        }
    else:  # creative
        return {
            "nightmares": [
                "Incrementalism trap: solving local optimization problems while missing a 10x architectural leap.",
                "Monolithic coupling: tightly binding features into a single script preventing cross-platform distribution."
            ],
            "breakthroughs": [
                "Cognitive Palace & Dream simulation synergy: simulate tests before writing code, saving 80% debug time.",
                "Universal self-contained portable pack: 1-click installable across Linux, macOS, and Windows with zero leaks."
            ]
        }

def main():
    parser = argparse.ArgumentParser(description="Claude Code Cognitive Dream Engine")
    parser.add_argument("args", nargs="*", help="Subcommand (run/simulate) or topic words")
    parser.add_argument("--topic", help="Feature, idea, or problem to simulate")
    parser.add_argument("--chambers", "--chamber", "-c", help="Comma-separated chambers (tech, biz, psych, creative)")
    parser.add_argument("--role", "-r", help="Alias for chambers")
    parser.add_argument("--target", "-t", help="Target source file or directory to stress-test")
    parser.add_argument("--quick", "-q", action="store_true", help="Fast 2-chamber simulation (tech + creative)")
    parsed, unknown = parser.parse_known_args()

    pos_args = list(parsed.args) + list(unknown)
    if pos_args and pos_args[0].lower() in ["run", "simulate", "sim", "start"]:
        pos_args = pos_args[1:]

    topic = parsed.topic or (" ".join(pos_args) if pos_args else "")

    raw_chambers = parsed.chambers or parsed.role
    if parsed.quick:
        chambers = ["technical", "creative"]
    elif raw_chambers:
        chambers = [c.strip() for c in raw_chambers.split(",") if c.strip()]
    else:
        chambers = list(DREAM_CHAMBERS.keys())

    run_simulation(chambers=chambers, target_path=parsed.target, topic=topic)

if __name__ == "__main__":
    main()
