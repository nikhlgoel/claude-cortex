"""Local models for Claude Code: ``cc local ...`` and ``cc offline``.

See docs/LOCAL_MODELS.md. The rules this package keeps:

* Nothing is downloaded, installed or deleted without the person seeing the source,
  size and destination and saying yes (``store.confirm``) - and never from inside a
  Claude Code session.
* Everything is bound to 127.0.0.1 behind a bearer token.
* "Unknown stays unknown": speed is measured by ``doctor --smoke``, never estimated, and
  a model is not called "proven" because a list says so.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date

from ..profiles import CortexError
from . import catalog, doctor, hub, plan, profile, runtime, serve, store

USAGE = """\
cc local - run Claude Code against a model on this machine

  cc local status                    Hardware, runtime, models, what is running
  cc local search <text>             Find GGUF models on Hugging Face (search only)
  cc local install --runtime         Install llama.cpp (asks first, shows size + hash)
  cc local install <id|owner/repo>   Download a model (asks first, shows size + hash)
        [--quant Q4_K_M] [--file NAME] [--dir PATH] [--yes]
  cc local list                      Installed models
  cc local use <id>                  Choose the active model
  cc local serve [id] [--force]      Start the model server + gateway
  cc local stop                      Stop both and free VRAM/RAM
  cc local doctor [--smoke]          Check every link; --smoke measures real speed
  cc local logs [server|gateway]     Last log lines
  cc local env                       Show the session environment (token hidden)
  cc local runtime [--path EXE]      Show or set the llama-server to use
  cc local rm <id> [--yes]           Delete a model's files (asks first)
  cc offline [claude args...]        Start Claude Code on the active local model
        [--local-model ID] [--force]

Downloads need a person at a terminal: they are refused inside a Claude Code session,
even with --yes.
"""

VALUE_FLAGS = ("--quant", "--file", "--dir", "--backend", "--path", "--limit", "--local-model")


# ----------------------------------------------------------------------- helpers

def _take(args, name, takes_value=False):
    """Remove ``name`` (or ``name=value``) from ``args``. Returns ``(value_or_bool, rest)``."""
    rest = list(args)
    for i, arg in enumerate(rest):
        if arg == name:
            if takes_value:
                value = rest[i + 1] if i + 1 < len(rest) else None
                del rest[i:i + 2]
                return value, rest
            del rest[i]
            return True, rest
        if takes_value and arg.startswith(name + "="):
            del rest[i]
            return arg.split("=", 1)[1], rest
    return (None if takes_value else False), rest


def _positional(args):
    out, skip = [], False
    for arg in args:
        if skip:
            skip = False
        elif arg in VALUE_FLAGS:
            skip = True
        elif not arg.startswith("-"):
            out.append(arg)
    return out


def _yes(args):
    return "--yes" in args or "-y" in args


def _slug(text):
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-")


def _cfg():
    cfg, status = store.load()
    if status in ("unparseable", store.NEWER_SCHEMA):
        raise CortexError(f"{store.config_path()} cannot be used ({status}); run: cc local doctor")
    return cfg


def _gb(n):
    return f"{n / plan.GIB:.2f} GiB"


def _inside(root, path):
    root, path = os.path.abspath(root), os.path.abspath(path)
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:                      # different drives
        return False


def _progress():
    last = {"pct": -1}

    def show(done, want):
        if not want:
            return
        pct = int(done * 100 / want) // 5 * 5
        if pct != last["pct"]:
            last["pct"] = pct
            print(f"    {pct:3d}%  {_gb(done)} / {_gb(want)}", flush=True)
    return show


# ------------------------------------------------------------------------ commands

def cmd_status(_args):
    cfg = _cfg()
    hw = plan.detect()
    for _level, name, detail in doctor.check_hardware(hw):
        print(f"{name}: {detail}")
    print(f"runtime: {runtime.find(cfg) or 'not installed (cc local install --runtime)'}")
    print(f"active model: {cfg.get('active_model') or 'none'}")
    for name, info in serve.status(cfg).items():
        print(f"{name}: {'running' if info['running'] else 'stopped'} (127.0.0.1:{info['port']})")
    print("\nCatalog (suggestions only; sizes are approximate until you install):")
    for model_id, entry in catalog.CATALOG.items():
        verdict = plan.fit(entry, entry["approx_gb"], hw)
        mark = {"gpu": "fits GPU", "split": "needs RAM+GPU", "no": "does not fit now",
                "unknown": "unknown"}[verdict["verdict"]]
        have = " [installed]" if model_id in cfg.get("models", {}) else ""
        print(f"  {model_id:<22} {entry['approx_gb']:>5.1f} GB  {entry['tier']:<12} {mark}{have}")
    print("\nNot offered on this class of machine:")
    for name, why in catalog.NOT_OFFERED.items():
        print(f"  {name}: {why}")
    return 0


def cmd_search(args):
    query = " ".join(_positional(args))
    if not query:
        print("Usage: cc local search <text>", file=sys.stderr)
        return 2
    cfg = _cfg()
    limit, _rest = _take(args, "--limit", True)
    results = hub.search(query, int(limit or 10), cfg["hf"]["endpoint"],
                         publishers=cfg["hf"]["publishers"])
    if not results:
        print("No GGUF repositories matched.")
        return 0
    for item in results:
        flags = ("trusted publisher" if item["trusted"] else "unknown publisher: read the card first") \
            + (", gated" if item["gated"] else "")
        print(f"  {item['id']:<55} {item['downloads']:>9,} downloads  {flags}")
    print("\nThis was a search only; nothing was downloaded.\n"
          "Install with: cc local install <owner/repo> --quant <Q4_K_M>")
    return 0


def cmd_runtime(args):
    path, _rest = _take(args, "--path", True)
    if "--path" in args or any(a.startswith("--path=") for a in args):
        if not path or not os.path.isfile(path):
            print("cc: --path needs the full path to an existing llama-server executable", file=sys.stderr)
            return 2
        ok, first = runtime.verify(path)
        if not ok:
            print(f"cc: that file did not run: {first}", file=sys.stderr)
            return 1
        store.update(lambda c: c["runtime"].update({"kind": "external", "path": os.path.abspath(path)}))
        print(f"Using {path} ({first})")
        return 0
    exe = runtime.find(_cfg())
    print(exe or "llama-server is not installed. Run: cc local install --runtime")
    return 0 if exe else 1


def _install_runtime(args):
    backend, _rest = _take(args, "--backend", True)
    exe = runtime.install(plan.detect(), assume_yes=_yes(args), backend=backend, progress=_progress())
    if not exe:
        print("Nothing was installed.")
        return 1
    ok, first = runtime.verify(exe)
    print(f"Installed: {exe}\n{'OK' if ok else 'PROBLEM'}: {first}")
    return 0 if ok else 1


def _models_root(cfg, hw, need_gb):
    """Folder for model files and the reason, or raises CortexError."""
    configured = cfg.get("data_dir")
    root, why = plan.choose_data_dir(need_gb, hw["disks"], configured)
    if root is None:
        raise CortexError(f"cannot place the model: {why}. Free space or use --dir <folder>.")
    return (root if configured else os.path.join(root, "cortex-models")), why


def cmd_install(args):
    if "--runtime" in args:
        return _install_runtime(args)
    target = (_positional(args) or [None])[0]
    if not target:
        print("Usage: cc local install <id|owner/repo> [--quant Q] [--file NAME] [--dir PATH] [--yes]\n"
              "       cc local install --runtime", file=sys.stderr)
        return 2
    cfg = _cfg()
    quant, _r = _take(args, "--quant", True)
    filename, _r = _take(args, "--file", True)
    chosen_dir, _r = _take(args, "--dir", True)

    known = catalog.get(target)
    if known:
        repo, quant, model_id, entry = known["repo"], quant or known["quant"], target, known
    else:
        if "/" not in target:
            print(f"cc: '{target}' is not a catalog id ({', '.join(catalog.ids())}) or an owner/repo.",
                  file=sys.stderr)
            return 2
        repo, model_id, entry = hub.validate_repo(target), None, None
        if not quant and not filename:
            print("cc: for a repository that is not in the catalog, choose a file with --quant or --file.",
                  file=sys.stderr)
            return 2

    files = hub.list_files(repo, cfg["hf"]["endpoint"])
    group = hub.select(files, quant, filename)
    total = sum(f["size"] for f in group)
    if not model_id:
        base = re.sub(r"-gguf$", "", repo.split("/")[1], flags=re.I)
        model_id = _slug(f"{base}-{group[0]['quant'] or 'gguf'}")
    if model_id in cfg["models"]:
        print(f"'{model_id}' is already installed ({_gb(cfg['models'][model_id]['size_bytes'])}).")
        return 0

    hw = plan.detect()
    if chosen_dir:
        cfg["data_dir"] = os.path.abspath(chosen_dir)
    models_root, why = _models_root(cfg, hw, total / plan.GIB)
    entry = entry or serve.entry_for(model_id, {"models": {model_id: {"size_bytes": total}}})
    verdict = plan.fit(entry, total / plan.GIB, hw)

    trusted = repo.split("/")[0].lower() in {p.lower() for p in cfg["hf"]["publishers"]}
    facts = [f"Source:      {cfg['hf']['endpoint']}/{repo}"
             + ("" if trusted else "   (NOT on your trusted-publisher list - read its model card)"),
             f"Install to:  {models_root}  ({why})"]
    for f in group:
        digest = f"{f['sha256'][:16]}..." if f["sha256"] else "not listed (size check only)"
        facts.append(f"File:        {f['path']}  {_gb(f['size'])}  sha256 {digest}")
    facts.append(f"Total:       {_gb(total)}")
    facts.append(f"Fit here:    {verdict['verdict']} - " + "; ".join(verdict["notes"]))
    if os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        facts.append("Token:       your HF_TOKEN from the environment is sent to huggingface.co only")
    print(f"About to download {model_id}:")
    if not store.confirm("Download these files?", facts, assume_yes=_yes(args)):
        print("Nothing was downloaded.")
        return 1

    paths = []
    for f in group:
        print(f"  {f['path']}")
        paths.append(hub.download(repo, f, hub.safe_dest(models_root, repo, f["path"]),
                                  cfg["hf"]["endpoint"], progress=_progress()))

    def register(c):
        c["data_dir"] = c.get("data_dir") or models_root
        c["models"][model_id] = {"repo": repo, "quant": group[0]["quant"], "files": paths,
                                 "size_bytes": total, "sha256": [f["sha256"] for f in group],
                                 "installed": date.today().isoformat()}
        c["active_model"] = c.get("active_model") or model_id
    store.update(register)
    print(f"Installed '{model_id}'. Verified size" + (" and sha256." if all(f["sha256"] for f in group) else "."))
    print("Next: cc local doctor   then   cc offline")
    return 0


def cmd_list(_args):
    cfg = _cfg()
    models = cfg.get("models") or {}
    if not models:
        print("No models installed. Try: cc local install qwen3.5-4b")
        return 0
    for model_id, info in models.items():
        mark = "*" if model_id == cfg.get("active_model") else " "
        ok = all(os.path.isfile(f) for f in info.get("files", []))
        print(f" {mark} {model_id:<28} {_gb(info.get('size_bytes', 0)):>10}  {info.get('repo', '?')}"
              f"{'' if ok else '  [FILES MISSING]'}")
    print("\n* = active")
    return 0


def cmd_use(args):
    model_id = (_positional(args) or [None])[0]
    cfg = _cfg()
    if not model_id or model_id not in cfg["models"]:
        print(f"cc: pick an installed model: {', '.join(cfg['models']) or '(none installed)'}", file=sys.stderr)
        return 2
    store.update(lambda c: c.update({"active_model": model_id}))
    print(f"Active model: {model_id}")
    return 0


def cmd_serve(args):
    cfg = _cfg()
    model_id = (_positional(args) or [cfg.get("active_model")])[0]
    if not model_id:
        print("cc: no model installed. Try: cc local install qwen3.5-4b", file=sys.stderr)
        return 1
    url = serve.ensure(cfg, model_id, force="--force" in args)
    print(f"Ready: {url}  (model {model_id}; 127.0.0.1 only)")
    return 0


def cmd_stop(_args):
    for name, stopped in serve.stop_all().items():
        print(f"{name}: {'stopped' if stopped else 'was not running'}")
    return 0


def cmd_doctor(args):
    text, ok = doctor.render(doctor.run(_cfg(), do_smoke="--smoke" in args))
    print(text)
    return 0 if ok else 1


def cmd_logs(args):
    which = (_positional(args) or ["server"])[0]
    name = {"server": "llama-server", "gateway": "gateway"}.get(which)
    if not name:
        print("Usage: cc local logs [server|gateway]", file=sys.stderr)
        return 2
    print(serve.tail(serve.log_path(name), 40) or "(no log yet)")
    return 0


def cmd_env(_args):
    cfg = _cfg()
    model_id = cfg.get("active_model")
    if not model_id:
        print("cc: no active model", file=sys.stderr)
        return 1
    env = profile.env_for(cfg, f"http://127.0.0.1:{cfg['ports']['gateway']}", "<token hidden>", model_id)
    for key in sorted(env):
        print(f"{key}={env[key]}")
    return 0


def cmd_rm(args):
    model_id = (_positional(args) or [None])[0]
    cfg = _cfg()
    info = cfg["models"].get(model_id or "")
    if not info:
        print("Usage: cc local rm <installed id>", file=sys.stderr)
        return 2
    root = cfg.get("data_dir")
    files = info.get("files", [])
    if not root or not all(_inside(root, f) for f in files):
        print("cc: those files are outside the Cortex models folder, so Cortex will not delete them. "
              "Remove them yourself.", file=sys.stderr)
        return 1
    facts = [f"Delete:      {f}" for f in files] + [f"Frees:       {_gb(info.get('size_bytes', 0))}"]
    if not store.confirm(f"Permanently delete '{model_id}'?", facts, assume_yes=_yes(args)):
        print("Nothing was deleted.")
        return 1
    if serve.read_state("server").get("model") == model_id:
        serve.stop_all()
    for f in files:
        for suffix in ("", ".part"):
            try:
                os.unlink(f + suffix)
            except OSError:
                pass

    def forget(c):
        c["models"].pop(model_id, None)
        if c.get("active_model") == model_id:
            c["active_model"] = None
    store.update(forget)
    print(f"Removed '{model_id}'.")
    return 0


def cmd_offline(args):
    chosen, argv = _take(args, "--local-model", True)
    force, argv = _take(argv, "--force")
    cfg = _cfg()
    model_id = chosen or cfg.get("active_model")
    if not model_id or model_id not in cfg["models"]:
        print("cc: no local model is installed. Start with:\n"
              "    cc local install --runtime\n    cc local install qwen3.5-4b", file=sys.stderr)
        return 1
    return profile.launch(cfg, model_id, argv, force=force)


COMMANDS = {"status": cmd_status, "search": cmd_search, "install": cmd_install, "pull": cmd_install,
            "list": cmd_list, "ls": cmd_list, "use": cmd_use, "serve": cmd_serve, "stop": cmd_stop,
            "doctor": cmd_doctor, "logs": cmd_logs, "env": cmd_env, "runtime": cmd_runtime,
            "rm": cmd_rm, "remove": cmd_rm}


def main(args):
    """Entry for ``cc local ...``. Returns an exit code."""
    if not args or args[0] in ("help", "--help", "-h"):
        print(USAGE)
        return 0
    handler = COMMANDS.get(args[0])
    if not handler:
        print(f"cc local: unknown command '{args[0]}'.\n", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    return handler(args[1:])
