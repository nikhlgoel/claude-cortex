#!/usr/bin/env python3
"""
Automated Security, Sanitization & Secret Scanner for Claude Cortex Pack
Audits all files in the distribution pack to guarantee zero leaked credentials,
no hardcoded personal paths, no leftover cache/temp files, and strict packaging cleanliness.
"""

import os
import sys
import re

PACK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Regex patterns for credential leak detection
SECRET_PATTERNS = [
    (re.compile(r'sk-ant-api03-[A-Za-z0-9_-]{20,}'), "Live Anthropic API Key"),
    (re.compile(r'AIzaSy[A-Za-z0-9_-]{33}'), "Live Google Gemini / GCP Key"),
    (re.compile(r'sk-or-v1-[A-Za-z0-9_-]{30,}'), "Live OpenRouter API Key"),
    (re.compile(r'sk-[A-Za-z0-9_-]{32,}'), "Live OpenAI API Key"),
    (re.compile(r'ghp_[A-Za-z0-9]{36}'), "GitHub Personal Access Token"),
    (re.compile(r'github_pat_[A-Za-z0-9_]{40,}'), "GitHub Fine-Grained Token"),
]

# Prohibited private personal identity markers
PRIVATE_STRINGS = [
    ("veillabs.in@gmail.com", "User private email"),
    ("white.dev.sc@gmail.com", "User private email"),
    ("/home/nikhl", "Hardcoded absolute user home path"),
    ("C:\\Users\\nikhl", "Hardcoded Windows user path"),
]

# Disallowed files or directories in distribution pack
DISALLOWED_PATTERNS = [
    re.compile(r'.*\.pyc$'),
    re.compile(r'.*\.pyo$'),
    re.compile(r'.*__pycache__.*'),
    re.compile(r'.*\.DS_Store$'),
    re.compile(r'.*Thumbs\.db$'),
    re.compile(r'.*\.lock$'),
    re.compile(r'.*\.tmp\..*'),
    re.compile(r'.*\.credentials\.json$'),
]

# Excluded documentation or audit scripts from certain string checks
AUDIT_SELF = os.path.abspath(__file__)

def audit_pack():
    print("======================================================================")
    print(f"   🔍 Scanning Distribution Pack: {PACK_DIR}")
    print("======================================================================")

    violations = []
    scanned_files = 0

    for root, dirs, files in os.walk(PACK_DIR):
        # Check directory names
        for d in dirs:
            dir_path = os.path.join(root, d)
            for pat in DISALLOWED_PATTERNS:
                if pat.match(dir_path):
                    violations.append(f"[DISALLOWED DIR] {os.path.relpath(dir_path, PACK_DIR)}")

        for f in files:
            file_path = os.path.join(root, f)
            rel_path = os.path.relpath(file_path, PACK_DIR)

            # Skip the audit script itself (it contains the patterns as strings). Compare
            # the full path, not the basename: a basename match exempted ANY file with
            # that name anywhere in the pack from the secret scan, which is a way to
            # smuggle a leak past the gate.
            if os.path.abspath(file_path) == AUDIT_SELF:
                continue

            scanned_files += 1

            # Check disallowed filenames
            for pat in DISALLOWED_PATTERNS:
                if pat.match(file_path):
                    violations.append(f"[DISALLOWED FILE] {rel_path}")

            # Read and scan file contents (skip binary files)
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()
            except OSError as exc:
                # A security gate must not fail open. An unreadable file (permission,
                # a broken symlink, an over-long Windows path) used to be skipped
                # silently, so the audit could still print "100% CLEAN" without ever
                # having scanned it.
                violations.append(f"[UNREADABLE] {rel_path}: {exc}")
                continue

            # Check for secrets
            for pattern, desc in SECRET_PATTERNS:
                m = pattern.search(content)
                if m:
                    violations.append(f"[SECRET LEAK] {rel_path}: Found {desc} ('{m.group(0)[:8]}...')")

            # Check for private strings
            for s, desc in PRIVATE_STRINGS:
                if s in content:
                    violations.append(f"[PERSONAL DATA] {rel_path}: Found {desc} ('{s}')")

    print(f"Scanned {scanned_files} files across distribution pack.")
    if violations:
        print("\n❌ SECURITY & SANITIZATION AUDIT FAILED:")
        for v in violations:
            print(f"  • {v}")
        print("\nPlease resolve all violations before packaging.")
        sys.exit(1)
    else:
        print("\n✓ 100% CLEAN! Zero secrets, zero personal markers, zero disallowed files.")
        print("======================================================================")
        sys.exit(0)

if __name__ == "__main__":
    audit_pack()
