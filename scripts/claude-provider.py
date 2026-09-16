#!/usr/bin/env python3
"""
Claude Cortex - API Provider Manager
Allows seamless fallback and switching between:
1. Claude Web OAuth Subscription (Default)
2. Direct Anthropic API Key (ANTHROPIC_API_KEY)
3. OpenRouter API Key (OpenRouter Anthropic-compatible endpoint)
4. Google Gemini AI Studio (via local adapter proxy)
"""

import os
import sys
import json
import argparse
import subprocess
import time

PROVIDERS_FILE = os.path.expanduser("~/.claude/providers.json")
SHARED_CLAUDE_DIR = os.path.expanduser("~/.claude")

DEFAULT_CONFIG = {
    "active_provider": "oauth",
    "providers": {
        "oauth": {
            "name": "Claude AI Subscription (OAuth)",
            "type": "oauth",
            "model": "claude-sonnet-5",
            "description": "Claude Code subscription quota, per configured profile"
        },
        "anthropic": {
            "name": "Direct Anthropic API Key",
            "type": "api_key",
            "api_key": "",
            "base_url": "https://api.anthropic.com",
            "model": "claude-sonnet-5",
            "description": "Pay-as-you-go Anthropic API console credits"
        },
        "openrouter": {
            "name": "OpenRouter.ai",
            "type": "api_key",
            "api_key": "",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "description": "Access Claude, Gemini, DeepSeek, and Free OpenRouter models"
        },
        "gemini": {
            "name": "Google Gemini AI Studio",
            "type": "gemini_proxy",
            "api_key": "",
            "base_url": "http://127.0.0.1:8088",
            "model": "gemini-2.5-pro",
            "proxy_port": 8088,
            "description": "Direct Google AI Studio free/paid API key via local adapter"
        }
    }
}

def load_providers():
    if not os.path.exists(PROVIDERS_FILE):
        save_providers(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(PROVIDERS_FILE) as f:
            data = json.load(f)
            for k, v in DEFAULT_CONFIG["providers"].items():
                if k not in data.get("providers", {}):
                    data.setdefault("providers", {})[k] = v
            return data
    except Exception:
        return DEFAULT_CONFIG

def save_providers(data):
    os.makedirs(os.path.dirname(PROVIDERS_FILE), exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(PROVIDERS_FILE, flags, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    try:
        os.chmod(PROVIDERS_FILE, 0o600)
    except Exception:
        pass

# Programmatic API & Testing Aliases
load_config = load_providers
save_config = save_providers

def get_active_provider():
    cfg = load_providers()
    return cfg.get("active_provider", "oauth")

def set_active_provider(provider_name):
    cfg = load_providers()
    if provider_name in cfg.get("providers", {}):
        cfg["active_provider"] = provider_name
        save_providers(cfg)
        return True
    return False

def is_proxy_running(port=8088):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False

def start_cortex_gateway(port=8088):
    if is_proxy_running(port):
        return True
    gateway_script = os.path.join(SHARED_CLAUDE_DIR, "scripts", "cortex-gateway.py")
    if not os.path.exists(gateway_script):
        # Fallback to gemini-proxy if cortex-gateway is not yet installed in shared dir
        gateway_script = os.path.join(SHARED_CLAUDE_DIR, "scripts", "gemini-proxy.py")
    if not os.path.exists(gateway_script):
        return False

    env = os.environ.copy()
    env["CORTEX_GATEWAY_PORT"] = str(port)

    subprocess.Popen(
        [sys.executable, gateway_script, "--port", str(port)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    time.sleep(0.4)
    return is_proxy_running(port)

def show_status():
    cfg = load_providers()
    active = cfg.get("active_provider", "oauth")

    print("======================================================================")
    print("              Claude Cortex - Model & API Providers")
    print("======================================================================")
    print(f"Current Active Provider: {active.upper()}\n")
    print(f"  {'PROVIDER':<14} {'KEY STATUS':<22} {'ACTIVE MODEL':<38} {'ENDPOINT'}")
    print(f"  {'-'*14} {'-'*22} {'-'*38} {'-'*28}")

    for pkey, pinfo in cfg["providers"].items():
        is_act = " <-- ACTIVE" if pkey == active else ""
        if pkey == "oauth":
            status_str = "[Subscription Quota]"
            model_str = pinfo.get("model", "claude-sonnet-5")
            # Show the profiles that actually exist rather than the two names
            # this file happened to be written with.
            try:
                import os as _os
                _root = _os.path.expanduser("~/.claude-profiles")
                _names = sorted(n for n in _os.listdir(_root)
                                if _os.path.isdir(_os.path.join(_root, n)))
            except OSError:
                _names = []
            endpoint_str = (", ".join(_names) if _names
                            else "no profiles configured")
        else:
            k = pinfo.get("api_key", "")
            if k:
                masked = k[:8] + "..." + k[-4:] if len(k) > 16 else "[Configured]"
                status_str = f"[✓ Key Set: {masked}]"
            else:
                status_str = "[✗ Key Not Set]"
            model_str = pinfo.get("model", "default")
            endpoint_str = pinfo.get("base_url", "")

        print(f"  {pkey.upper():<14} {status_str:<22} {model_str:<38} {endpoint_str}{is_act}")

    print("")
    print("Provider Commands (One-time Setup):")
    print("  claude provider set <oauth|anthropic|openrouter|gemini>  Switch active provider")
    print("  claude provider key <provider> <api_key>                 Set API key securely")
    print("")
    print("Model Commands (Frequent Switching):")
    print("  claude model                                             Interactive model selector")
    print("  claude model list                                        List models & benchmarks")
    print("  claude model free                                        List 100% free models")
    print("  claude model set <model_id>                              Set active model directly")
    print("======================================================================")

def get_env_for_provider(provider_name=None):
    cfg = load_providers()
    target = provider_name or cfg.get("active_provider", "oauth")
    pinfo = cfg.get("providers", {}).get(target, {})

    if target == "oauth":
        return {}

    api_key = pinfo.get("api_key", "")
    if not api_key:
        print(f"Error: No API key configured for provider '{target}'.", file=sys.stderr)
        print(f"Run: claude provider key {target} <your_api_key>", file=sys.stderr)
        sys.exit(1)

    env_vars = {}
    model = pinfo.get("model", "")
    if target == "anthropic":
        env_vars["ANTHROPIC_API_KEY"] = api_key
        if model:
            env_vars["ANTHROPIC_MODEL"] = model
    elif target == "openrouter":
        port = pinfo.get("proxy_port", 8088)
        start_cortex_gateway(port=port)
        # Route through Cortex Gateway for OT-ACR token optimization & stream keep-alive
        env_vars["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        env_vars["ANTHROPIC_API_KEY"] = api_key
        env_vars["OPENROUTER_API_KEY"] = api_key
        if model:
            env_vars["ANTHROPIC_MODEL"] = model
    elif target == "gemini":
        port = pinfo.get("proxy_port", 8088)
        model = model or "gemini-2.5-pro"
        start_cortex_gateway(port=port)
        env_vars["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        env_vars["ANTHROPIC_API_KEY"] = api_key
        env_vars["GEMINI_API_KEY"] = api_key
        env_vars["ANTHROPIC_MODEL"] = model

    return env_vars

def main():
    parser = argparse.ArgumentParser(description="Claude Cortex Provider Manager")
    parser.add_argument("action", nargs="?", default="status",
                        choices=["status", "list", "set", "use", "key", "model", "config", "env", "reset"])
    parser.add_argument("provider", nargs="?", default=None)
    parser.add_argument("extra", nargs="*", help="Key or parameters")
    parser.add_argument("--key", help="API key to configure")
    parser.add_argument("--model", help="Default model name")
    parser.add_argument("--url", help="Custom base URL")
    args = parser.parse_args()

    cfg = load_providers()

    if args.action == "reset":
        cfg["active_provider"] = "oauth"
        save_providers(cfg)
        print("✓ Reset active provider to default: CLAUDE AI OAUTH SUBSCRIPTION")
        return

    if args.action in ["status", "list"]:
        show_status()
        return

    target = (args.provider or "").lower().strip()
    if not target and args.extra:
        target = args.extra[0].lower().strip()
        args.extra = args.extra[1:]

    if not target:
        target = cfg.get("active_provider", "oauth")

    # Helper: resolve provider or fallback to active
    if target not in cfg["providers"] and target not in ["oauth", "anthropic", "openrouter", "gemini"]:
        # User might have done: claude provider key <key>
        if args.action == "key" and target.startswith("sk-") or target.startswith("AIza"):
            # Target is the key itself!
            key = target
            target = cfg.get("active_provider", "openrouter")
            cfg["providers"][target]["api_key"] = key
            save_providers(cfg)
            print(f"✓ Saved API key for active provider {target.upper()}")
            return
        else:
            print(f"Error: Unknown provider '{target}'. Valid providers: {list(cfg['providers'].keys())}")
            sys.exit(1)

    if args.action in ["set", "use"]:
        cfg["active_provider"] = target
        # If an optional key was passed along with set
        if args.key or (args.extra and (args.extra[0].startswith("sk-") or args.extra[0].startswith("AIza"))):
            k = args.key or args.extra[0]
            cfg["providers"][target]["api_key"] = k
            print(f"✓ Saved API key for {target.upper()}")
        save_providers(cfg)
        print(f"✓ Active provider set to: {target.upper()}")
        if target != "oauth" and not cfg["providers"][target].get("api_key"):
            print(f"⚠️  Note: No API key configured yet for {target.upper()}. Run: claude provider key {target} <key>")

    elif args.action == "key":
        key = args.key or (args.extra[0] if args.extra else None)
        if not key:
            try:
                import getpass
                key = getpass.getpass(f"Enter API key for {target.upper()}: ").strip()
            except Exception:
                pass
        if not key:
            print(f"Error: No key provided. Usage: claude provider key {target} <api_key>")
            sys.exit(1)
        cfg["providers"][target]["api_key"] = key
        save_providers(cfg)
        masked = key[:8] + "..." + key[-4:] if len(key) > 16 else "[Saved]"
        print(f"✓ Configured API key for {target.upper()} ({masked})")

    elif args.action == "model":
        model_name = args.model or (args.extra[0] if args.extra else None)
        if not model_name:
            print(f"Error: No model provided. Usage: claude provider model {target} <model_name>")
            sys.exit(1)
        cfg["providers"][target]["model"] = model_name
        save_providers(cfg)
        print(f"✓ Configured default model for {target.upper()}: {model_name}")

    elif args.action == "config":
        # Smart handler that distinguishes between key and model!
        param1 = args.key or (args.extra[0] if len(args.extra) > 0 else None)
        param2 = args.model or (args.extra[1] if len(args.extra) > 1 else None)

        # If only 1 param was passed
        if param1 and not param2:
            # Check if param1 looks like a model ID (contains / or :free or matches common model prefixes)
            if "/" in param1 or ":free" in param1 or param1.startswith("gemini-") or param1.startswith("claude-") or param1.startswith("gpt-"):
                cfg["providers"][target]["model"] = param1
                print(f"✓ Configured model for {target.upper()}: {param1}")
                print(f"  (Tip: You can also use 'claude model set {param1}' to switch models easily)")
            else:
                cfg["providers"][target]["api_key"] = param1
                masked = param1[:8] + "..." + param1[-4:] if len(param1) > 16 else "[Saved]"
                print(f"✓ Configured API key for {target.upper()}: {masked}")
        elif param1 and param2:
            # First is key, second is model
            if "/" in param1 and not ("/" in param2):
                param1, param2 = param2, param1
            cfg["providers"][target]["api_key"] = param1
            cfg["providers"][target]["model"] = param2
            print(f"✓ Configured {target.upper()} API key and model: {param2}")
        else:
            show_status()

        if args.url:
            cfg["providers"][target]["base_url"] = args.url

        save_providers(cfg)

    elif args.action == "env":
        env_map = get_env_for_provider(target)
        for k, v in env_map.items():
            print(f"export {k}='{v}'")

if __name__ == "__main__":
    main()
