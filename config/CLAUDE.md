# Claude Cortex - global instructions

This file is the entry point. Everything in `~/.claude/rules/` is loaded on every
request, so it is kept deliberately small; domain guidance lives in Skills that
load only when relevant.

## Precedence

When guidance conflicts, the more specific source wins:

1. Explicit instructions in the current conversation
2. Project `CLAUDE.md` and project settings
3. A Skill loaded for the task at hand
4. This file and `~/.claude/rules/00-core.md`

If two always-on rules ever contradict each other, that is a bug in the ruleset,
not a judgment call. Report it rather than silently picking one.

## Response style

Direct and concise. No preamble, no filler, no restating the request. Say what
was done and what it means.

Do not open a response with a status banner, a summary card, or a restatement of
the task. Do not close with an offer of further help or a request for
amendments - if a question genuinely needs asking, ask it plainly and stop.

Two things this does *not* mean: do not omit information the user needs to make a
decision, and do not skip a caveat that changes how they should read a result.
Brevity is about removing ceremony, not substance.

## Working method

- Inspect before changing. Read the code that is actually involved rather than
  inferring from names.
- Verify what you claim. If you say tests pass, run them; if a step was skipped,
  say so.
- Prefer targeted file reads (`sed -n`, `grep`, bounded `head`) over dumping
  whole files, and pipe long command output through `tail`.
- When a task is ambiguous in a way that changes the outcome, ask. When it is
  ambiguous in a way that does not, choose sensibly and say which way you went.
- Report failures honestly, with the output that shows them.

## Available Skills

Domain guidance loads on demand. Invoke by name when the task calls for it:

| Skill | Use for |
| :--- | :--- |
| `cpp-systems` | Modern C++20, RAII, memory safety, systems code |
| `algorithms` | Data structures, complexity analysis, competitive programming |
| `design-engineering` | UI/UX implementation, visual hierarchy, micro-interactions |
| `systems-architecture` | Distributed systems design, scaling, failure modes |
| `hardware-performance` | Cache behavior, SIMD, GPU kernels, profiling |
| `live-pairing` | Interactive step-by-step collaboration |

## Cortex commands

Cortex management runs in the terminal, not through the model:

```
cc status          account capacity      cc doctor       diagnose config
cc switch <name>   change active profile cc login <name> authenticate
cc continue        resume last session   cc ide check    IDE integration
```

In-session, these are available as `/cc <command>`. Only that explicit prefix is
intercepted - ordinary prompts containing words like "switch", "test", or
"continue" are never treated as commands.
