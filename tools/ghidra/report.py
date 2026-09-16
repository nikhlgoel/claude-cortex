#!/usr/bin/env python3
"""
Turn Ghidra's extracted facts into a capability report.

Why capabilities rather than a function list
--------------------------------------------
Decompiled C is a wall of text, and the first question about an unknown binary
is not "what does line 400 do" but "what is this thing able to do at all". That
is answered by what it imports, and it is answered with certainty in one
direction: a binary that never imports a socket call cannot open a socket. The
absence of a capability is a hard fact; its presence is a lead.

So this reports capabilities first, ranked, each backed by the specific imports
that granted it — then points at the functions worth reading.

The facts come from ExtractProgramInfo.java. Judgement lives here so the two can
change independently and the evidence stays checkable.

Usage:
    report.py <program.json> [--decompiled FILE] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# A capability is granted by importing any of its symbols. Matching is on the
# symbol name with common decorations stripped, so __isoc99_scanf matches scanf.
#
# "concern" says why it matters when examining something untrusted. It is
# deliberately concrete: "can execute other programs" rather than "dangerous".
CAPABILITIES = [
    ("process execution", "can start other programs, so its reach is not limited to its own code", [
        "system", "execve", "execl", "execlp", "execv", "execvp", "popen",
        "fork", "vfork", "posix_spawn", "CreateProcessA", "CreateProcessW",
        "ShellExecuteA", "ShellExecuteW", "WinExec",
    ]),
    ("network", "can send data off the machine", [
        "socket", "connect", "send", "sendto", "recv", "recvfrom", "bind",
        "listen", "accept", "gethostbyname", "getaddrinfo", "inet_addr",
        "WSAStartup", "InternetOpenA", "InternetOpenW", "HttpSendRequestA",
        "URLDownloadToFileA", "curl_easy_init",
    ]),
    ("dynamic code loading", "can load and run code that is not in this file", [
        "dlopen", "dlsym", "LoadLibraryA", "LoadLibraryW", "GetProcAddress",
        "mmap", "mprotect", "VirtualAlloc", "VirtualProtect",
    ]),
    ("filesystem write", "can modify or create files", [
        "fopen", "open", "write", "fwrite", "unlink", "remove", "rename",
        "mkdir", "chmod", "CreateFileA", "CreateFileW", "WriteFile",
        "DeleteFileA", "MoveFileA",
    ]),
    ("filesystem read", "can read files", [
        "fread", "read", "fgets", "fscanf", "opendir", "readdir", "stat",
        "ReadFile", "FindFirstFileA",
    ]),
    ("persistence", "can arrange to run again later", [
        "RegSetValueExA", "RegSetValueExW", "RegCreateKeyExA",
        "CreateServiceA", "CreateServiceW", "schtasks", "crontab",
    ]),
    ("cryptography", "handles keys or ciphertext", [
        "AES_encrypt", "EVP_EncryptInit", "EVP_DecryptInit", "MD5_Init",
        "SHA256_Init", "RAND_bytes", "CryptEncrypt", "CryptAcquireContextA",
        "BCryptEncrypt",
    ]),
    ("privilege and identity", "inspects or changes who it runs as", [
        "setuid", "seteuid", "setgid", "getuid", "geteuid",
        "AdjustTokenPrivileges", "OpenProcessToken", "ImpersonateLoggedOnUser",
    ]),
    ("anti-analysis", "behaves differently when observed", [
        "ptrace", "IsDebuggerPresent", "CheckRemoteDebuggerPresent",
        "NtQueryInformationProcess", "OutputDebugStringA",
    ]),
    ("memory unsafety", "uses functions with no bounds checking", [
        "strcpy", "strcat", "sprintf", "gets", "scanf", "vsprintf",
        "memcpy", "alloca",
    ]),
]

# Strings that are worth surfacing on sight.
STRING_PATTERNS = [
    ("URL", re.compile(r"https?://[^\s\"']{4,}")),
    ("IP address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("file path", re.compile(r"(?:/(?:etc|usr|tmp|home|var)/|[A-Za-z]:\\\\)")),
    ("registry key", re.compile(r"(?:HKEY_|SOFTWARE\\\\|SYSTEM\\\\)")),
    ("shell command", re.compile(r"\b(?:/bin/sh|/bin/bash|cmd\.exe|powershell)\b",
                                 re.IGNORECASE)),
    ("format string", re.compile(r"%[sdxfp]")),
]


def normalize(symbol):
    """Strip decorations so __isoc99_scanf matches scanf."""
    name = symbol.lstrip("_")
    for prefix in ("isoc99_", "imp_", "IMP_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.split("@")[0]


def detect_capabilities(imports):
    names = {normalize(entry.get("name", "")) for entry in imports}
    lowered = {n.lower() for n in names}

    found = []
    for capability, concern, symbols in CAPABILITIES:
        matched = sorted({s for s in symbols
                          if s in names or s.lower() in lowered})
        if matched:
            found.append({"capability": capability, "concern": concern,
                          "evidence": matched})
    return found


def interesting_strings(strings):
    hits = []
    for entry in strings:
        value = entry.get("value", "")
        for label, pattern in STRING_PATTERNS:
            if pattern.search(value):
                hits.append({"kind": label, "address": entry.get("address"),
                             "value": value[:120]})
                break
    return hits


def rank_functions(functions):
    """Functions worth reading first.

    Ranked by callers then size. A function called from many places carries the
    program's logic; a large one with no callers is often an entry point or dead
    code, and both are worth a look for different reasons.
    """
    real = [f for f in functions
            if not f.get("thunk") and not f.get("external")
            and not f.get("name", "").startswith(("_init", "_fini", "__do_global",
                                                  "register_tm", "deregister_tm",
                                                  "frame_dummy"))]
    return sorted(real, key=lambda f: (-f.get("callers", 0), -f.get("size", 0)))


def render(data, decompiled_path=None):
    out = []
    add = out.append

    imports = data.get("imports", [])
    functions = data.get("functions", [])
    strings = data.get("strings", [])

    capabilities = detect_capabilities(imports)
    notable = interesting_strings(strings)
    ranked = rank_functions(functions)

    add("=" * 74)
    add(f"  {data.get('name', 'binary')} - capability report")
    add("=" * 74)
    add(f"  format    : {data.get('format')}")
    add(f"  language  : {data.get('language')}")
    add(f"  md5       : {data.get('executableMD5')}")
    add(f"  functions : {len(functions)}  ({len(ranked)} substantive)")
    add(f"  imports   : {len(imports)}")
    add("")

    add("-" * 74)
    add("  WHAT IT CAN DO")
    add("-" * 74)
    if not capabilities:
        # Distinguish "looked and found nothing" from "could not look". They
        # carry opposite weight and the previous wording conflated them.
        if not imports:
            add("  NO IMPORTS AT ALL - this section proves nothing.")
            add("  The binary is statically linked or its import table could not")
            add("  be parsed, so capability detection had nothing to read.")
            add("  Absence of findings here is not evidence of absence.")
        else:
            add(f"  {len(imports)} import(s), none of which grants a recognised")
            add("  capability. The binary cannot open a socket, start a process,")
            add("  or load code, because it does not import anything that can.")
            add("")
            add("  Imports seen: " + ", ".join(
                sorted(normalize(i.get("name", "")) for i in imports)[:12]))
    else:
        add("  Each line is granted by the imports listed. Absence of a")
        add("  capability is a hard fact; presence is a lead, not a verdict.")
        add("")
        for item in capabilities:
            add(f"  * {item['capability']}")
            add(f"      {item['concern']}")
            add(f"      via: {', '.join(item['evidence'][:8])}")
            if len(item["evidence"]) > 8:
                add(f"           (+{len(item['evidence']) - 8} more)")
            add("")

    if notable:
        add("-" * 74)
        add("  STRINGS WORTH SEEING")
        add("-" * 74)
        by_kind = {}
        for hit in notable:
            by_kind.setdefault(hit["kind"], []).append(hit)
        for kind in ("URL", "IP address", "shell command", "registry key",
                     "file path", "format string"):
            items = by_kind.get(kind)
            if not items:
                continue
            add(f"  {kind} ({len(items)}):")
            for hit in items[:6]:
                add(f"      {hit['address']}  {hit['value']}")
            if len(items) > 6:
                add(f"      ... and {len(items) - 6} more")
            add("")

    add("-" * 74)
    add("  FUNCTIONS WORTH READING FIRST")
    add("-" * 74)
    add("  Ranked by incoming calls, then size. A function called from many")
    add("  places carries the logic; a large one with none is often an entry")
    add("  point.")
    add("")
    add(f"  {'CALLERS':>8}  {'SIZE':>6}  {'ADDRESS':<12} NAME")
    for function in ranked[:15]:
        add(f"  {function.get('callers', 0):>8}  {function.get('size', 0):>6}  "
            f"{function.get('address', ''):<12} {function.get('name', '')}")

    if decompiled_path and os.path.exists(decompiled_path):
        add("")
        add(f"  Decompiled C: {decompiled_path}")

    add("")
    add("=" * 74)
    add("  Recovered logic, not original source. Names of locals are invented,")
    add("  types are inferred, and functions the compiler inlined have lost")
    add("  their boundaries - their code appears merged into the caller.")
    add("=" * 74)
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Ghidra capability report")
    parser.add_argument("program_json")
    parser.add_argument("--decompiled")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        with open(args.program_json, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"report: cannot read {args.program_json}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({
            "program": {k: data.get(k) for k in
                        ("name", "format", "language", "executableMD5")},
            "capabilities": detect_capabilities(data.get("imports", [])),
            "notable_strings": interesting_strings(data.get("strings", [])),
            "top_functions": rank_functions(data.get("functions", []))[:15],
        }, indent=2))
    else:
        print(render(data, args.decompiled))
    return 0


if __name__ == "__main__":
    sys.exit(main())
