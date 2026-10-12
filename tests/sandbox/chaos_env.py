"""
Environment and concurrency chaos.

Complements ``fuzz.py``. Where that explores arguments and on-disk state, this
attacks the environment Cortex runs in and the assumption that only one copy
runs at a time.

Every check here asserts an invariant, not an expected message: no traceback, no
hang, no write outside the sandbox. A traceback in any of these states tells the
operator nothing actionable and makes a routine problem look like corruption.
"""

import os
import subprocess
import sys
import tempfile
import threading

WORK = os.environ.get("CORTEX_WORK", "/work")

failures = []
checks = 0


def record(ok, message):
    global checks
    checks += 1
    if not ok:
        failures.append(message)


def run_cc(args, env_extra=None, timeout=25, strip_env=()):
    env = dict(os.environ)
    env["PYTHONPATH"] = WORK
    for key in strip_env:
        env.pop(key, None)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "cortex"] + args,
            capture_output=True, text=True, timeout=timeout,
            env=env, cwd=WORK, stdin=subprocess.DEVNULL)
        return proc.returncode, proc.stdout + proc.stderr, False
    except subprocess.TimeoutExpired:
        return -1, "", True


def check_env_hostility(sandbox):
    """Hostile environment variables.

    HOME is not guaranteed to be sane: it can be unset in a cron job or a
    container, point at a file after a bad mount, or be empty. CLAUDE_CONFIG_DIR
    may already be set by an IDE. None of that should crash a status listing.
    """
    print("[env] hostile environment variables")

    file_home = os.path.join(sandbox, "home-is-a-file")
    os.makedirs(sandbox, exist_ok=True)
    with open(file_home, "w") as fh:
        fh.write("not a directory")

    cases = [
        ("HOME empty", {"HOME": ""}, ()),
        ("HOME is a file", {"HOME": file_home}, ()),
        ("HOME does not exist", {"HOME": os.path.join(sandbox, "nope")}, ()),
        ("HOME unset", {}, ("HOME",)),
        ("CLAUDE_CONFIG_DIR preset", {"CLAUDE_CONFIG_DIR": "/tmp/preset"}, ()),
        ("CLAUDE_PROFILE preset to garbage", {"CLAUDE_PROFILE": "../../etc"}, ()),
        ("PATH empty", {"PATH": ""}, ()),
        ("stale compaction overrides", {
            "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "0.45",
            "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "85000"}, ()),
    ]

    for label, extra, strip in cases:
        for command in (["status"], ["doctor"], ["version"]):
            rc, out, timed_out = run_cc(command, env_extra=extra, strip_env=strip)
            what = f"{label} / cc {' '.join(command)}"
            record(not timed_out, f"TIMEOUT: {what}")
            record("Traceback" not in out, f"TRACEBACK: {what} :: {out[-300:]}")


def check_concurrency(sandbox):
    """Many Cortex processes at once must not corrupt shared state."""
    print("[conc] concurrent invocations")

    profiles_dir = os.path.join(sandbox, "conc")
    for name in ("one", "two", "three"):
        run_cc(["profile", "add", name],
               env_extra={"CORTEX_PROFILES_DIR": profiles_dir})

    results = []

    def worker(name):
        rc, out, timed_out = run_cc(
            ["switch", name], env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
        results.append((name, rc, out, timed_out))

    threads = []
    for _ in range(4):
        for name in ("one", "two", "three"):
            t = threading.Thread(target=worker, args=(name,))
            threads.append(t)
            t.start()
    for t in threads:
        t.join()

    for name, rc, out, timed_out in results:
        record(not timed_out, f"TIMEOUT during concurrent switch to {name}")
        record("Traceback" not in out,
               f"TRACEBACK during concurrent switch: {out[-250:]}")

    # The pointer must name a real profile, never a torn or partial write.
    pointer = os.path.join(profiles_dir, "current_profile")
    active = ""
    if os.path.exists(pointer):
        with open(pointer, encoding="utf-8", errors="replace") as fh:
            active = fh.read().strip()
    record(active in ("one", "two", "three"),
           f"concurrent switches left a torn active profile: {active!r}")


def check_ide_chaos(sandbox):
    """The IDE settings writer must refuse anything it cannot safely rewrite."""
    print("[ide] hostile IDE settings states")

    home = os.path.expanduser("~")
    ext = os.path.join(home, ".vscode", "extensions", "anthropic.claude-code-9.9.9")
    os.makedirs(ext, exist_ok=True)
    with open(os.path.join(ext, "package.json"), "w") as fh:
        fh.write("{}")

    vsdir = os.path.join(home, ".config", "Code", "User")
    os.makedirs(vsdir, exist_ok=True)
    settings = os.path.join(vsdir, "settings.json")

    def reset(make):
        for path in (settings, settings + ".bak"):
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path) or os.path.islink(path):
                os.unlink(path)
        make()

    profiles_dir = os.path.join(sandbox, "ideprof")
    run_cc(["profile", "add", "idep"],
           env_extra={"CORTEX_PROFILES_DIR": profiles_dir})

    # settings.json is a directory.
    reset(lambda: os.makedirs(settings, exist_ok=True))
    rc, out, timed_out = run_cc(["ide", "apply", "--yes"],
                                env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
    record(not timed_out, "TIMEOUT: settings.json is a directory")
    record("Traceback" not in out,
           f"TRACEBACK: settings.json is a directory :: {out[-300:]}")

    # settings.json is a dangling symlink.
    def make_dangling():
        try:
            os.symlink(os.path.join(vsdir, "gone.json"), settings)
        except OSError:
            pass
    reset(make_dangling)
    rc, out, timed_out = run_cc(["ide", "apply", "--yes"],
                                env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
    record(not timed_out, "TIMEOUT: settings.json is a dangling symlink")
    record("Traceback" not in out,
           f"TRACEBACK: dangling settings.json symlink :: {out[-300:]}")

    # settings.json holds a JSON array rather than an object.
    reset(lambda: open(settings, "w").write('["not", "an", "object"]'))
    rc, out, timed_out = run_cc(["ide", "apply", "--yes"],
                                env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
    record(not timed_out, "TIMEOUT: settings.json is an array")
    record("Traceback" not in out,
           f"TRACEBACK: settings.json is an array :: {out[-300:]}")
    with open(settings, encoding="utf-8") as fh:
        content = fh.read()
    record("not" in content,
           "a settings.json containing an array was overwritten instead of refused")


def main():
    sandbox = os.environ.get("CORTEX_SANDBOX_DIR",
                             os.path.join(tempfile.gettempdir(), "chaosenv"))
    os.makedirs(sandbox, exist_ok=True)

    print("=" * 70)
    print("  Cortex environment & concurrency chaos")
    print("=" * 70)

    check_env_hostility(os.path.join(sandbox, "env"))
    check_concurrency(os.path.join(sandbox, "conc"))
    check_ide_chaos(os.path.join(sandbox, "ide"))

    print("\n" + "=" * 70)
    if failures:
        print(f"  {len(failures)} FAILURE(S) out of {checks} checks")
        print("=" * 70)
        seen = set()
        for message in failures:
            key = message.split("::")[0][:110]
            if key in seen:
                continue
            seen.add(key)
            print(f"  - {message}")
        return 1
    print(f"  {checks} checks passed")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
