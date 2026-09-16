"""
Ghidra integration - isolated binary analysis.

Ghidra is NSA-authored, open source under Apache-2.0. The integration is built
on the assumption that the audit could be wrong, because it is a best-effort
review of ~15,000 files rather than a proof:

  * analysis runs in a container started with ``--network none``. If there is no
    route out, anything the audit missed still cannot report.
  * the image is pinned to a reviewed release tag, never a moving branch.
  * updates are reported, never applied. Automated classification cannot
    reliably separate a refactor of network code from one that changes what is
    sent, and that is the case worth catching.

What the audit of 12.1.3 found, reproducible with ``cc ghidra audit``:
zero telemetry identifiers, zero .gov/.mil references, no auto-update mechanism,
no network access from any static initializer, and all 127 network call sites
accounted for in named modules that require the operator to configure or start
something.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .paths import canonical_dir

REPO = "NationalSecurityAgency/ghidra"

#: The reviewed release. Bump only after `cc ghidra update` has been read and
#: the CRITICAL/HIGH diffs actually looked at.
PINNED_REF = "Ghidra_12.1.3_build"
IMAGE = f"cortex-ghidra:{PINNED_REF}"


def tools_dir():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, "tools", "ghidra")


def _docker_available():
    return shutil.which("docker") is not None


def _run(cmd, **kwargs):
    try:
        return subprocess.run(cmd, **kwargs).returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"cc ghidra: {exc}", file=sys.stderr)
        return 1


def cmd_audit(args):
    """Re-run the supply-chain audit against a checkout."""
    script = os.path.join(tools_dir(), "audit.py")
    if not os.path.isfile(script):
        print("cc ghidra: audit.py not found; run from a repository checkout.",
              file=sys.stderr)
        return 1
    if not args:
        print("Usage: cc ghidra audit <path-to-ghidra-checkout> [--json]")
        print()
        print("  Clone one with:")
        print(f"    git clone --depth 1 --branch {PINNED_REF} \\")
        print(f"      https://github.com/{REPO}.git")
        return 2
    return _run([sys.executable, script] + list(args))


def cmd_build(args):
    """Build the network-isolated image."""
    if not _docker_available():
        print("cc ghidra: docker is required to build the analysis image.",
              file=sys.stderr)
        return 1

    ref = args[0] if args and not args[0].startswith("-") else PINNED_REF
    dockerfile = os.path.join(tools_dir(), "Dockerfile")
    repo_root = os.path.dirname(tools_dir().rstrip(os.sep))
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print(f"Building Ghidra {ref} (this takes a while - it compiles the decompiler).")
    print("The BUILD needs network access to fetch dependencies.")
    print("Analysis afterwards runs with --network none.")
    print()
    return _run(["docker", "build", "-f", dockerfile,
                 "--build-arg", f"GHIDRA_REF={ref}",
                 "-t", f"cortex-ghidra:{ref}", repo_root])


def cmd_analyze(args):
    """Run headless analysis on a binary, with no network."""
    if not _docker_available():
        print("cc ghidra: docker is required.", file=sys.stderr)
        return 1
    if not args:
        print("Usage: cc ghidra analyze <binary> [-- <analyzeHeadless args>]")
        print()
        print("  The binary's directory is mounted read-only at /work/in and the")
        print("  container runs with no network.")
        return 2

    target = os.path.abspath(args[0])
    if not os.path.isfile(target):
        print(f"cc ghidra: not a file: {target}", file=sys.stderr)
        return 1

    extra = list(args[1:])
    if extra and extra[0] == "--":
        extra = extra[1:]

    host_dir = canonical_dir(os.path.dirname(target))
    name = os.path.basename(target)
    out_dir = os.path.join(os.getcwd(), "ghidra-out")
    os.makedirs(out_dir, exist_ok=True)

    # --network none is the control that does not depend on the audit being
    # complete. Read-only input mount and a dropped capability set follow the
    # same principle: assume the analysis target may itself be hostile, since
    # the whole point is examining untrusted binaries.
    scripts = os.path.join(tools_dir(), "scripts")

    # The project directory must already exist - Ghidra will not create it, and
    # the failure ("Directory not found") does not say so.
    project = os.path.join(out_dir, "project")
    os.makedirs(project, exist_ok=True)

    source_out = os.path.join(out_dir, f"{name}.c")

    cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", f"{host_dir}:/work/in:ro",
        "-v", f"{canonical_dir(out_dir)}:/work/out",
        "-v", f"{canonical_dir(scripts)}:/work/scripts:ro",
        f"cortex-ghidra:{PINNED_REF}",
        "/work/out/project", "cortex",
        "-import", f"/work/in/{name}",
        "-scriptPath", "/work/scripts",
        "-postScript", "ExtractProgramInfo.java", f"/work/out/{name}.json",
        "-postScript", "DecompileToC.java", f"/work/out/{name}.c",
        "-deleteProject", "-analysisTimeoutPerFile", "600",
    ] + extra

    print(f"Analyzing {name} with no network access.")
    print()
    rc = _run(cmd)
    if rc != 0:
        return rc

    # Ending at "here is a file path" leaves the actual work undone. Render the
    # capability report so the command answers the question people open a
    # decompiler to ask: what is this thing able to do?
    facts = os.path.join(out_dir, f"{name}.json")
    reporter = os.path.join(tools_dir(), "report.py")
    if os.path.exists(facts) and os.path.exists(reporter):
        print()
        _run([sys.executable, reporter, facts, "--decompiled", source_out])
    elif os.path.exists(source_out):
        print()
        print(f"  Decompiled C: {source_out}")
    return rc


def cmd_update(args):
    """Report on upstream changes. Never applies them."""
    script = os.path.join(tools_dir(), "update_watch.py")
    if not os.path.isfile(script):
        print("cc ghidra: update_watch.py not found.", file=sys.stderr)
        return 1
    return _run([sys.executable, script, "check"] + list(args))


def cmd_status(args):
    print("=" * 74)
    print("  Ghidra integration")
    print("=" * 74)
    print(f"  pinned release : {PINNED_REF}")
    print(f"  image          : cortex-ghidra:{PINNED_REF}")

    if _docker_available():
        result = subprocess.run(
            ["docker", "images", "-q", f"cortex-ghidra:{PINNED_REF}"],
            capture_output=True, text=True)
        built = bool(result.stdout.strip())
        print(f"  image built    : {'yes' if built else 'no (run: cc ghidra build)'}")
    else:
        print("  docker         : not found")

    baseline = os.path.join(tools_dir(), "baseline-current.json")
    print(f"  audit baseline : {'recorded' if os.path.exists(baseline) else 'none'}")
    print()
    print("  Isolation: analysis runs with --network none, --cap-drop ALL, and a")
    print("  read-only input mount. That holds regardless of what the audit")
    print("  missed - no route out means nothing can be reported.")
    print()
    print("  Updates are reported, never auto-applied.")
    print("=" * 74)
    return 0


USAGE = """\
cc ghidra - isolated binary analysis

  cc ghidra status              show pinned version and image state
  cc ghidra audit <checkout>    re-run the supply-chain audit
  cc ghidra build [ref]         build the network-isolated image
  cc ghidra analyze <binary>    headless analysis, no network
  cc ghidra update              report upstream changes (never applies)
"""

COMMANDS = {
    "status": cmd_status,
    "audit": cmd_audit,
    "build": cmd_build,
    "analyze": cmd_analyze,
    "update": cmd_update,
}


def main(args):
    if not args or args[0] in ("--help", "help"):
        print(USAGE)
        return 0
    action = args[0]
    handler = COMMANDS.get(action)
    if not handler:
        print(f"cc ghidra: unknown action '{action}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    return handler(args[1:])
