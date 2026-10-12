"""``cc local doctor``: check every link between Claude Code and the local model.

Each check returns ``(level, name, detail)`` with level ``ok`` / ``warn`` / ``fail`` /
``info``. Nothing is repaired automatically and nothing is downloaded. The optional
smoke test sends one tiny request through the gateway and reports MEASURED first-token
latency and generation speed - the only honest source for tokens/second on this
machine, since an estimate would be a guess dressed as a number.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from . import plan, runtime, serve, store


def _post(url, payload, token=None, timeout=300):
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers,
                                 method="POST")
    return urllib.request.urlopen(req, timeout=timeout)


def check_config():
    cfg, status = store.load()
    path = store.config_path()
    if status == "unparseable":
        return [("fail", "config", f"{path} is not valid JSON; nothing will be changed until you fix it")]
    if status == store.NEWER_SCHEMA:
        return [("fail", "config", f"{path} was written by a newer Cortex; update Cortex")]
    problems = store.validate(cfg)
    if problems:
        return [("fail", "config", "; ".join(problems))]
    return [("ok", "config", path if status == "parsed" else "no config yet (defaults in use)")]


def check_runtime(cfg):
    exe = runtime.find(cfg)
    if not exe:
        return [("fail", "runtime", "llama-server not found. Install it: cc local install --runtime")]
    ok, first = runtime.verify(exe)
    if not ok:
        return [("fail", "runtime", f"{exe} does not run: {first}. A CUDA build needs its runtime DLLs "
                                    f"and a recent NVIDIA driver; try --backend cuda-12.4 or cpu")]
    return [("ok", "runtime", f"{exe} ({first})")]


def check_model(cfg, hw):
    model_id = cfg.get("active_model")
    if not model_id:
        return [("warn", "model", "no active model. Install one: cc local install qwen3.5-4b")]
    installed = (cfg.get("models") or {}).get(model_id)
    if not installed:
        return [("fail", "model", f"active model '{model_id}' is not installed")]
    missing = [f for f in installed.get("files", []) if not os.path.isfile(f)]
    if missing:
        return [("fail", "model", f"files missing from disk: {', '.join(missing)}")]
    out = [("ok", "model", f"{model_id} ({installed.get('size_bytes', 0) / plan.GIB:.2f} GiB)")]
    entry = serve.entry_for(model_id, cfg)
    verdict = plan.fit(entry, installed.get("size_bytes", 0) / plan.GIB, hw, installed.get("ctx"))
    level = {"gpu": "ok", "split": "warn", "no": "fail"}.get(verdict["verdict"], "info")
    out.append((level, "fit", f"{verdict['verdict']}: " + "; ".join(verdict["notes"])))
    if entry.get("tier") == "experimental":
        out.append(("warn", "model", "this model is experimental: not reported working with Claude Code"))
    return out


def check_hardware(hw):
    gpus = ", ".join(f"{g['name']} {g['total_gb']:.1f} GiB" for g in hw["gpus"]) or "no NVIDIA GPU detected"
    if hw["ram_total_gb"] is None:
        ram = "RAM unknown"
    else:
        ram = f"RAM {hw['ram_free_gb']:.1f} free of {hw['ram_total_gb']:.1f} GiB"
    return [("info", "hardware", f"{gpus}; {ram}")]


def check_token():
    path = store.token_path()
    if not os.path.isfile(path):
        return [("info", "token", "not created yet (made on first `cc local serve`)")]
    if os.name != "nt" and os.stat(path).st_mode & 0o077:
        return [("fail", "token", f"{path} is readable by other users; run: chmod 600 {path}")]
    return [("ok", "token", "present, owner-only")]


def check_processes(cfg):
    out = []
    for name, info in serve.status(cfg).items():
        if info["running"] and info["listening"]:
            out.append(("ok", name, f"running on 127.0.0.1:{info['port']} (model {info['model']})"))
        elif info["listening"]:
            out.append(("warn", name, f"port {info['port']} is in use by something Cortex did not start"))
        else:
            out.append(("info", name, "not running (it starts on demand with `cc offline`)"))
    return out


def smoke(cfg):
    """Auth + stream + speed through the gateway. Requires both processes running."""
    out = []
    base = f"http://127.0.0.1:{cfg['ports']['gateway']}"
    token = store.token(create=False)
    body = {"model": cfg["claude"]["alias"], "max_tokens": 48, "stream": True,
            "messages": [{"role": "user", "content": "Reply with the single word: ready"}]}

    try:
        _post(f"{base}/v1/messages/count_tokens", body, token=None, timeout=15)
        out.append(("fail", "auth", "the gateway answered a request with NO token - it must refuse"))
    except urllib.error.HTTPError as exc:
        exc.close()
        out.append(("ok" if exc.code == 401 else "fail", "auth",
                    "requests without the token are refused" if exc.code == 401
                    else f"expected 401 without a token, got {exc.code}"))
    except (urllib.error.URLError, OSError) as exc:
        return out + [("fail", "gateway", f"not reachable: {exc}. Start it: cc local serve")]

    started = time.monotonic()
    first = None
    events = set()
    out_tokens = 0
    try:
        with _post(f"{base}/v1/messages", body, token=token) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if line.startswith("event:"):
                    events.add(line[6:].strip())
                elif line.startswith("data:") and first is None and '"text_delta"' in line:
                    first = time.monotonic() - started
                if line.startswith("data:") and '"output_tokens"' in line:
                    try:
                        out_tokens = json.loads(line[5:]).get("usage", {}).get("output_tokens", out_tokens)
                    except ValueError:
                        pass
    except (urllib.error.URLError, OSError) as exc:
        return out + [("fail", "stream", f"request failed: {exc}")]
    total = time.monotonic() - started

    need = {"message_start", "content_block_delta", "message_stop"}
    if need <= events:
        out.append(("ok", "stream", "Anthropic-style event stream received"))
    else:
        out.append(("fail", "stream", f"missing events: {', '.join(sorted(need - events))}"))
    if first is not None:
        gen = max(total - first, 1e-6)
        rate = f"{out_tokens / gen:.1f} tok/s" if out_tokens > 1 else "n/a (too few tokens)"
        out.append(("info", "speed", f"first token after {first:.1f}s; generation {rate} "
                                     f"(measured on a tiny prompt - long prompts prefill slower)"))
    return out


def run(cfg, do_smoke=False, hw=None):
    hw = hw or plan.detect()
    results = check_config() + check_hardware(hw) + check_runtime(cfg) + check_model(cfg, hw) \
        + check_token() + check_processes(cfg)
    if do_smoke:
        results += smoke(cfg)
    return results


def render(results):
    """Return ``(text, ok)``; ``ok`` is False when any check failed."""
    marks = {"ok": "[ ok ]", "warn": "[warn]", "fail": "[FAIL]", "info": "[info]"}
    lines = [f"{marks[level]} {name:<9} {detail}" for level, name, detail in results]
    failed = any(r[0] == "fail" for r in results)
    warned = any(r[0] == "warn" for r in results)
    lines += ["", "Problems found - fix the [FAIL] lines first." if failed
              else "Usable, with warnings above." if warned else "All checks passed."]
    return "\n".join(lines), not failed
