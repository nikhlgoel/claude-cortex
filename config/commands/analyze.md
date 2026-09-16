---
name: analyze
description: Static risk analysis of source code - swallowed errors, non-atomic writes, missing timeouts, shell injection - with file, line, and the failure mechanism.
argument-hint: [--path DIR | --all | --since REF]
command: true
---

# Analyze — static risk analysis of code

Runs Cortex's source analyser over changed files (or `--path`, `--all`, `--since`).
It reports findings ranked by how *quietly* the failure happens: a swallowed
exception or a truncated write (SILENT) outranks a crash (LOUD), because a wrong
answer with no error is worse than one that announces itself.

```bash
cc analyze              # uncommitted changes
cc analyze --all        # whole tree
cc analyze --path src   # a directory
```

This is code analysis, not concept exploration. For exploring an idea or decision
before acting on it, use `/dream <concept>`.
