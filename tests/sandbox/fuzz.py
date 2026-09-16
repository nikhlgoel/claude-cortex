#!/usr/bin/env python3
"""
Adversarial testing for the Cortex core.

The scenario suite in ``scenarios.sh`` was written after each bug was fixed, so
it passes by construction: it proves regressions do not return, but it cannot
find anything new. This module explores instead of asserting known outcomes.

Three strategies:

1. **Argument fuzzing** - throw generated argument vectors at the dispatcher and
   check *invariants* rather than expected output: never a traceback, never a
   session launched for something that is not a prompt, always a bounded runtime.

2. **State-machine fuzzing** - apply random sequences of profile operations and
   assert the invariants that must hold after *any* sequence (the active profile
   is either empty or a real directory, no profile escapes the root, and so on).

3. **Property checks** - properties that must hold for all inputs, such as
   canonicalization being idempotent and stable across spellings.

Run with a seed to reproduce a failure:  fuzz.py --seed 12345
"""

import argparse
import itertools
import json
import os
import random
import string
import subprocess
import sys
import time

WORK = os.environ.get("CORTEX_WORK", "/work")
STUB_LOG = os.environ.get("CORTEX_STUB_LOG", "/tmp/fuzz-stub.jsonl")

# Fragments the dispatcher must cope with in any combination.
TOKENS = [
    "-s", "-o", "-H", "-t", "-y", "-e", "high", "low", "bogus",
    "--effort=max", "--effort=nonsense", "-e", "--", "-p", "--print",
    "status", "doctor", "switch", "continue", "profile", "add", "remove",
    "login", "ide", "check", "apply", "--yes", "version", "help",
    "palace", "dream", "docs", "menu", "nonsensecmd",
    "ghidra", "mcp", "analyze", "audit", "status", "add", "remove", "test",
    "", " ", "--", "-", "---", "-ghost", "-1", "0",
    "a b", "'; rm -rf /", "$(whoami)", "`id`", "..", "../..",
    "éè", "你好", "x" * 300,
]

failures = []
checks = 0


def record(ok, message):
    global checks
    checks += 1
    if not ok:
        failures.append(message)


def run_cc(args, timeout=25, env_extra=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = WORK
    env["CORTEX_STUB_LOG"] = STUB_LOG
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "cortex"] + args,
            capture_output=True, text=True, timeout=timeout,
            env=env, cwd=WORK, stdin=subprocess.DEVNULL)
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired:
        return -1, "", "", True


def stub_invocations():
    try:
        with open(STUB_LOG, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except (OSError, ValueError):
        return []


# --------------------------------------------------------------------------
# 1. Argument fuzzing
# --------------------------------------------------------------------------
def fuzz_arguments(rounds, rng, profiles_dir):
    """Invariants that must hold for ANY argument vector."""
    print(f"[args] fuzzing {rounds} argument vectors")

    # A signed-in profile must exist first. Without one, require_profile refuses
    # before the launch path is reached, so "did a command leak into a session"
    # could never be observed.
    #
    # This precondition is ASSERTED rather than assumed. When setup silently
    # failed, the pass reported 274 checks while actually testing nothing - and
    # mutation testing exposed it as a mutation that was caught standalone but
    # missed inside the full suite. A test that cannot establish its
    # preconditions must fail, not report success.
    run_cc(["profile", "add", "fuzzprof"],
           env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
    run_cc(["login", "fuzzprof"],
           env_extra={"CORTEX_PROFILES_DIR": profiles_dir})

    open(STUB_LOG, "w").close()
    rc, out, err, timed_out = run_cc(
        ["-fuzzprof", "-s"], env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
    launched = [c for c in stub_invocations()
                if c.get("argv") and c["argv"][0] not in ("auth", "--version")]
    if not launched:
        record(False,
               "PRECONDITION FAILED: could not launch a session with a signed-in "
               "profile, so leak detection below is vacuous. "
               f"rc={rc} out={(out + err)[-250:]!r}")
        return

    # Random generation alone leaves gaps: mutation testing showed a known-bad
    # vector (an unknown command WITH trailing arguments) was simply never
    # produced at this seed, so the check passed while the bug was live. Always
    # run the known-dangerous corpus, then fuzz on top of it.
    corpus = [
        ["nonsensecmd"],
        ["nonsensecmd", "check"],
        ["nonsensecmd", "---", "check", "bogus"],
        ["docs", "extra"],
        ["menu", "-s"],
        ["typo", "--effort=high"],
        ["status", "unexpected"],
        ["profile", "nonsense-action"],
        ["ide", "nonsense-action"],
        ["palace", "--weird"],
    ]

    vectors = list(corpus)
    for _ in range(rounds):
        n = rng.randint(1, 5)
        vectors.append([rng.choice(TOKENS) for _ in range(n)])

    for args in vectors:

        open(STUB_LOG, "w").close()
        rc, out, err, timed_out = run_cc(
            args, env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
        combined = out + err
        shown = " ".join(repr(a) for a in args)

        record(not timed_out, f"TIMEOUT for args: {shown}")
        record("Traceback (most recent call last)" not in combined,
               f"TRACEBACK for args: {shown}\n{combined[-400:]}")

        # A session may only start when the user actually asked for one. If the
        # first token is a known command or an unknown bare word, nothing should
        # reach the CLI as a prompt.
        head = args[0] if args else ""
        never_a_prompt = ("status", "doctor", "version", "help", "profile", "ide",
                          "docs", "menu", "nonsensecmd", "typo", "palace")
        if head in never_a_prompt:
            launched = [c for c in stub_invocations()
                        if c.get("argv") and c["argv"][0] not in
                        ("auth", "--version", "update")]
            record(not launched,
                   f"COMMAND LEAKED INTO A SESSION: {shown} -> {launched[:1]}")


# --------------------------------------------------------------------------
# 2. State-machine fuzzing
# --------------------------------------------------------------------------
def fuzz_state_machine(rounds, rng, profiles_dir):
    """Invariants that must hold after ANY sequence of profile operations."""
    print(f"[state] fuzzing {rounds} profile operation sequences")

    names = ["alpha", "beta", "gamma", "delta"]

    for step in range(rounds):
        op = rng.choice(["add", "remove", "switch", "login", "status", "add-odd"])
        name = rng.choice(names)

        if op == "add":
            run_cc(["profile", "add", name],
                   env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
        elif op == "add-odd":
            odd = "".join(rng.choice(string.printable[:80]) for _ in range(6))
            run_cc(["profile", "add", odd],
                   env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
        elif op == "remove":
            run_cc(["profile", "remove", name],
                   env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
        elif op == "switch":
            run_cc(["switch", name],
                   env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
        elif op == "login":
            run_cc(["login", name],
                   env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
        else:
            run_cc(["status"], env_extra={"CORTEX_PROFILES_DIR": profiles_dir})

        # Invariant A: the active profile is empty, or names a real directory.
        pointer = os.path.join(profiles_dir, "current_profile")
        active = ""
        if os.path.exists(pointer):
            with open(pointer, encoding="utf-8") as fh:
                active = fh.read().strip()
        if active:
            record(os.path.isdir(os.path.join(profiles_dir, active)),
                   f"[step {step}] active profile '{active}' has no directory "
                   f"(after {op} {name})")

        # Invariant B: nothing escapes the profiles root.
        if os.path.isdir(profiles_dir):
            for entry in os.listdir(profiles_dir):
                record(".." not in entry and "/" not in entry and "\\" not in entry,
                       f"[step {step}] profile entry escapes the root: {entry!r}")

        # Invariant C: status never crashes, whatever the state.
        rc, out, err, timed_out = run_cc(
            ["status"], env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
        record(not timed_out, f"[step {step}] status timed out after {op}")
        record("Traceback" not in (out + err),
               f"[step {step}] status crashed after {op} {name}:\n{(out+err)[-300:]}")


# --------------------------------------------------------------------------
# 3. Property checks
# --------------------------------------------------------------------------
def check_properties(rng):
    """Properties that must hold for all inputs."""
    print("[props] checking canonicalization properties")
    sys.path.insert(0, WORK)
    from cortex.paths import canonical_dir, securestorage_suffix

    bases = ["/tmp/a", "/tmp/a/b", "/tmp/x y/z", "/tmp/.hidden/p"]
    for base in bases:
        spellings = [
            base, base + "/", base + "//", base + "/.",
            base.replace("/", "//"), "/.." + "/tmp" + base[4:] if base.startswith("/tmp") else base,
        ]
        results = {canonical_dir(s) for s in spellings if s}
        record(len(results) == 1,
               f"canonicalization is not stable for {base!r}: {results}")

        # Idempotence: canonicalizing twice equals canonicalizing once.
        once = canonical_dir(base)
        record(canonical_dir(once) == once,
               f"canonicalization is not idempotent for {base!r}")

        # The credential namespace must follow the canonical form, not the input.
        suffixes = {securestorage_suffix(canonical_dir(s))
                    for s in spellings if s}
        record(len(suffixes) == 1,
               f"credential namespace differs by spelling for {base!r}: {suffixes}")

    # Unicode: the same path written in NFC and NFD must resolve to one
    # namespace. macOS hands out NFD filenames while most tooling produces NFC,
    # so without normalization the same directory hashes two ways and a profile
    # looks signed out depending on which form reached us.
    nfc = "/tmp/café/p"          # e-acute as one code point
    nfd = "/tmp/café/p"         # e + combining acute
    record(canonical_dir(nfc) == canonical_dir(nfd),
           "NFC and NFD spellings of the same path do not canonicalize equal")
    record(securestorage_suffix(canonical_dir(nfc))
           == securestorage_suffix(canonical_dir(nfd)),
           "NFC and NFD spellings produce different credential namespaces")




# --------------------------------------------------------------------------
# 4. Filesystem chaos
# --------------------------------------------------------------------------
def chaos_filesystem(sandbox):
    """Hostile on-disk states. None may produce a traceback or a hang.

    These are states a real machine reaches: an interrupted install, a synced
    folder replacing a directory with a file, a truncated write, a stale symlink
    after a move.
    """
    print("[chaos] hostile filesystem states")

    cases = []

    # A profile directory replaced by a regular file.
    d = os.path.join(sandbox, "c1")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "broken"), "w") as fh:
        fh.write("not a directory")
    cases.append(("profile entry is a file", d))

    # current_profile containing binary garbage.
    d = os.path.join(sandbox, "c2")
    os.makedirs(os.path.join(d, "real"), exist_ok=True)
    with open(os.path.join(d, "current_profile"), "wb") as fh:
        # Built programmatically so this source file stays ASCII-clean.
        fh.write(bytes([0, 255, 254]) + b" garbage " + bytes([10, 13, 0]))
    cases.append(("current_profile is binary garbage", d))

    # current_profile naming a profile that does not exist.
    d = os.path.join(sandbox, "c3")
    os.makedirs(os.path.join(d, "real"), exist_ok=True)
    with open(os.path.join(d, "current_profile"), "w") as fh:
        fh.write("ghost")
    cases.append(("current_profile names a missing profile", d))

    # A profile whose .claude.json is a directory, not a file.
    d = os.path.join(sandbox, "c4")
    os.makedirs(os.path.join(d, "weird", ".claude.json"), exist_ok=True)
    cases.append((".claude.json is a directory", d))

    # A dangling symlink where a profile should be.
    d = os.path.join(sandbox, "c5")
    os.makedirs(d, exist_ok=True)
    try:
        os.symlink(os.path.join(d, "nowhere"), os.path.join(d, "dangling"))
    except OSError:
        pass
    cases.append(("profile is a dangling symlink", d))

    # A symlink loop.
    d = os.path.join(sandbox, "c6")
    os.makedirs(d, exist_ok=True)
    try:
        os.symlink(os.path.join(d, "loop"), os.path.join(d, "loop"))
    except OSError:
        pass
    cases.append(("profile is a symlink loop", d))

    # An empty profile directory with nothing in it.
    d = os.path.join(sandbox, "c7")
    os.makedirs(os.path.join(d, "hollow"), exist_ok=True)
    cases.append(("profile directory is empty", d))

    # A truncated .claude.json (interrupted write).
    d = os.path.join(sandbox, "c8")
    os.makedirs(os.path.join(d, "trunc"), exist_ok=True)
    with open(os.path.join(d, "trunc", ".claude.json"), "w") as fh:
        fh.write('{"hasCompletedOnboarding": tru')
    cases.append(("truncated .claude.json", d))

    for label, profiles_dir in cases:
        for command in (["status"], ["doctor"], ["switch"], ["profile", "list"]):
            rc, out, err, timed_out = run_cc(
                command, env_extra={"CORTEX_PROFILES_DIR": profiles_dir})
            combined = out + err
            what = f"{label} / cc {' '.join(command)}"
            record(not timed_out, f"TIMEOUT: {what}")
            record("Traceback" not in combined,
                   f"TRACEBACK: {what} :: {combined[-400:]}")


def chaos_readonly(sandbox):
    """A read-only profiles root must produce an error, not a traceback."""
    print("[chaos] read-only profiles root")
    d = os.path.join(sandbox, "ro")
    os.makedirs(os.path.join(d, "existing"), exist_ok=True)
    try:
        os.chmod(d, 0o500)
    except OSError:
        print("  (cannot chmod here, skipping)")
        return
    try:
        for command in (["status"], ["profile", "add", "newone"], ["switch", "existing"]):
            rc, out, err, timed_out = run_cc(
                command, env_extra={"CORTEX_PROFILES_DIR": d})
            combined = out + err
            what = f"read-only root / cc {' '.join(command)}"
            record(not timed_out, f"TIMEOUT: {what}")
            record("Traceback" not in combined,
                   f"TRACEBACK: {what} :: {combined[-400:]}")
    finally:
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass


def chaos_never_writes_global(sandbox):
    """Cortex must never write ~/.claude.json - sign-in, MCP servers, trust."""
    print("[chaos] global config must stay untouched")
    home = os.path.expanduser("~")
    target = os.path.join(home, ".claude.json")
    with open(target, "w", encoding="utf-8") as fh:
        json.dump({"oauthAccount": {"emailAddress": "real@example.test"},
                   "projects": {"/some/project": {"trust": True}}}, fh)
    before = open(target, "rb").read()

    d = os.path.join(sandbox, "global")
    for command in (["profile", "add", "gtest"], ["login", "gtest"],
                    ["status"], ["doctor", "--repair"], ["switch", "gtest"]):
        run_cc(command, env_extra={"CORTEX_PROFILES_DIR": d})

    after = open(target, "rb").read()
    record(before == after,
           "~/.claude.json was modified - sign-in, MCP config and folder trust "
           "live there")


def main():
    parser = argparse.ArgumentParser(description="Cortex adversarial tests")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--arg-rounds", type=int, default=60)
    parser.add_argument("--state-rounds", type=int, default=40)
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else int(time.time())
    rng = random.Random(seed)
    print("=" * 70)
    print(f"  Cortex adversarial tests (seed {seed})")
    print("=" * 70)

    sandbox = os.environ.get("CORTEX_SANDBOX_DIR", "/tmp/fuzz")
    os.makedirs(sandbox, exist_ok=True)

    check_properties(rng)
    fuzz_arguments(args.arg_rounds, rng, os.path.join(sandbox, "argfuzz"))
    fuzz_state_machine(args.state_rounds, rng, os.path.join(sandbox, "statefuzz"))
    chaos_filesystem(os.path.join(sandbox, "chaos"))
    chaos_readonly(os.path.join(sandbox, "chaos"))
    chaos_never_writes_global(os.path.join(sandbox, "chaos"))

    print("\n" + "=" * 70)
    if failures:
        print(f"  {len(failures)} FAILURE(S) out of {checks} checks (seed {seed})")
        print("=" * 70)
        seen = set()
        for message in failures:
            key = message.split("\n")[0][:120]
            if key in seen:
                continue
            seen.add(key)
            print(f"  - {message}")
        print(f"\n  Reproduce with: fuzz.py --seed {seed}")
        return 1

    print(f"  {checks} checks passed (seed {seed})")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
