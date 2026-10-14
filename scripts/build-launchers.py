#!/usr/bin/env python3
"""
Build install.exe and bin/claude.exe from native/launcher.c.

    python scripts/build-launchers.py            build both, in place
    python scripts/build-launchers.py --check    build into a temp folder and compare with the
                                                 committed files (exit 1 if the source and the
                                                 binaries have drifted apart)

Needs a MinGW-w64 gcc and windres (MSYS2 "ucrt64" or "mingw64" provide both). It only compiles what
is already in the repository: nothing is downloaded. If no compiler is found it says so and stops.
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NATIVE = os.path.join(ROOT, "native")

# (define, output relative to the repo, description shown in the file's Properties dialog)
TARGETS = (
    ("CORTEX_INSTALLER", "install.exe", "Claude Cortex installer"),
    ("CORTEX_SHIM", os.path.join("bin", "claude.exe"), "Claude Cortex command (cc)"),
)

COMPILER_FOLDERS = (
    r"C:\msys64\ucrt64\bin",
    r"C:\msys64\mingw64\bin",
    r"C:\mingw64\bin",
    r"C:\mingw\bin",
)


def find_tool(name):
    found = shutil.which(name)
    if found:
        return found
    for folder in COMPILER_FOLDERS:
        candidate = os.path.join(folder, name + ".exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def build_one(gcc, windres, define, description, output):
    stem = os.path.splitext(os.path.basename(output))[0]
    original = os.path.basename(output)
    work = tempfile.mkdtemp(prefix="cortex-launcher-")
    try:
        resource = os.path.join(work, stem + ".res.o")
        with open(os.path.join(NATIVE, "launcher.rc.in"), encoding="utf-8") as fh:
            template = fh.read()
        script = os.path.join(work, stem + ".rc")
        with open(script, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(template.replace("@DESCRIPTION@", description).replace("@ORIGINAL@", original)
                     .replace("@MANIFEST@", os.path.join(NATIVE, "launcher.manifest").replace("\\", "/")))
        subprocess.run([windres, "-O", "coff", script, resource], check=True)
        os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
        subprocess.run(
            [gcc, "-O2", "-Wall", "-Wextra", "-D" + define, "-municode", "-mconsole", "-static", "-s",
             "-Wl,--no-insert-timestamp", os.path.join(NATIVE, "launcher.c"), resource, "-o", output],
            check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="rebuild into a temp folder and compare with the committed binaries")
    args = parser.parse_args(argv)

    gcc, windres = find_tool("gcc"), find_tool("windres")
    if not gcc or not windres:
        print("error: a MinGW-w64 gcc and windres are needed (for example MSYS2's ucrt64 toolchain).")
        print("       Nothing was built. The launchers already in the repository are unchanged.")
        return 1

    drift = 0
    scratch = tempfile.mkdtemp(prefix="cortex-launcher-check-") if args.check else None
    try:
        for define, relative, description in TARGETS:
            committed = os.path.join(ROOT, relative)
            output = os.path.join(scratch, os.path.basename(relative)) if args.check else committed
            build_one(gcc, windres, define, description, output)
            digest = sha256(output)
            if args.check:
                same = os.path.isfile(committed) and sha256(committed) == digest
                print(f"  {'same   ' if same else 'DIFFERS'} {relative}  {digest[:16]}")
                drift += 0 if same else 1
            else:
                print(f"  built {relative}  {os.path.getsize(output)} bytes  sha256 {digest[:16]}")
    finally:
        if scratch:
            shutil.rmtree(scratch, ignore_errors=True)
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
