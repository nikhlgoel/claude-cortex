"""The ``cc offline`` session: Claude Code pointed at a local model.

The config directory lives under ``~/.claude/cortex-local/profile`` - deliberately
OUTSIDE ``~/.claude-profiles``. Everything under that folder is treated as a cloud
account by ``cc switch``, ``cc continue`` and the "first profile" fallback, so a keyless
profile there would be offered for login and could become the default session. Out here
it can never be chosen by accident, and never shares credentials with a real account.

Environment choices (each from the verified research, see docs/LOCAL_MODELS.md):

* The model alias must not start with ``claude`` and must not contain ``[1m]``;
  otherwise Claude Code assumes a Claude context window and ignores our cap.
* ``CLAUDE_CODE_MAX_CONTEXT_TOKENS`` is the server's real context minus output headroom,
  so Claude Code compacts BEFORE the model runs out of room.
* Telemetry-ish and beta-header features are switched off: a local server rejects some
  of them and none of them help.
* A cloud credential inherited from the parent shell is dropped, never forwarded.
"""

from __future__ import annotations

import os

from .. import jsonfile, launcher
from ..paths import canonical_dir
from . import serve, store

#: Removed from the inherited environment so no cloud credential or provider switch
#: from the parent shell can influence (or leak into) a local session.
DROP = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
        "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL",
        "CLAUDE_PROFILE")


def config_dir():
    return canonical_dir(os.path.join(store.home(), "profile"))


def env_for(cfg, base_url, token, model_id):
    """Environment variables for a local session (no secrets beyond the loopback token)."""
    claude = cfg["claude"]
    alias = claude["alias"]
    entry = serve.entry_for(model_id, cfg)
    installed = (cfg.get("models") or {}).get(model_id) or {}
    ctx = int(installed.get("ctx") or entry["ctx"][0])
    max_out = int(claude["max_output"])
    env = {
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": alias,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": alias,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": alias,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": alias,
        "CLAUDE_CODE_SUBAGENT_MODEL": alias,
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS": str(max(8192, ctx - max_out)),
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_out),
        "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
        "CLAUDE_CODE_TOTAL_TOKENS_REMINDER": "off",
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_GATEWAY_HINT_HEADERS": "1",
        "CLAUDE_CODE_DISABLE_WORKFLOWS": "1",
        "API_TIMEOUT_MS": "1800000",
        "NO_PROXY": "127.0.0.1,localhost,::1",
        "no_proxy": "127.0.0.1,localhost,::1",
    }
    if claude.get("lean_prompt", True):
        env["CLAUDE_CODE_SIMPLE_SYSTEM_PROMPT"] = "1"
    env.update({str(k): str(v) for k, v in (claude.get("env") or {}).items()})
    return env


def session_args(cfg, argv):
    """Append the lean tool list unless the person chose their own."""
    args = list(argv)
    claude = cfg["claude"]
    chosen = any(a in ("--tools", "--allowedTools", "--allowed-tools") or a.startswith("--tools=")
                 for a in args)
    if claude.get("tools") and not chosen:
        args += ["--tools", ",".join(claude["tools"])]
    return args


def _prepare_dir(path):
    os.makedirs(path, exist_ok=True)
    # Without this Claude Code shows its first-run wizard, which wants a cloud login.
    jsonfile.update(os.path.join(path, ".claude.json"),
                    lambda cfg: {**cfg, "hasCompletedOnboarding": True}, {})


def launch(cfg, model_id, argv, hw=None, force=False):
    """Make sure the model + gateway are up, then start Claude Code against them."""
    base_url = serve.ensure(cfg, model_id, hw=hw, force=force)
    path = config_dir()
    _prepare_dir(path)
    extra = env_for(cfg, base_url, store.token(), model_id)
    if "ultracode" in argv:
        print("cc: note - 'ultracode' fans work out across many subagent calls. A small local "
              "model usually does worse with that, not better; 'max' is the highest real level.")
    return launcher.launch_dir(path, session_args(cfg, argv), extra_env=extra, drop=DROP)
