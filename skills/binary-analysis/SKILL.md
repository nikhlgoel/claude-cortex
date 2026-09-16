---
name: binary-analysis
description: Analyse a compiled binary - what it can do, what it does, and what its logic is - using the isolated Ghidra integration. Use when asked to inspect, reverse, decompile, or assess an executable, library, firmware image, or any file you cannot read as source.
---

# Binary analysis

Use `cc ghidra` when the thing to understand is compiled. It runs Ghidra in a
container with **no network route out**, so an untrusted binary cannot report
home and neither can the analysis tool.

## Running it

```bash
cc ghidra status                      # is the image built?
cc ghidra build                       # ~15 min, compiles the decompiler
cc ghidra analyze <binary>            # capability report + decompiled C
```

Output lands in `./ghidra-out/`:

| File | What it is |
| :--- | :--- |
| `<name>.c` | Decompiled C for every function |
| `<name>.json` | Structured facts: imports, exports, functions, strings |

## Read it in this order

**1. Capabilities first.** This is the highest-value answer per second spent, and
it is certain in one direction: *a binary that never imports a socket call cannot
open one.* Absence is a hard fact. Presence is a lead, not a verdict — importing
`CreateProcessW` means it *can* spawn a process, not that it does.

**2. Strings.** Usually the fastest route to intent. URLs, IPs, file paths,
registry keys, and command lines are extracted and grouped.

**3. Ranked functions.** Sorted by incoming calls, then size. Many callers means
load-bearing logic; large with none often means an entry point.

**4. The decompiled C**, only for the functions step 3 pointed at. Reading it
front to back is a waste of time.

## What it recovers well

Measured against binaries whose source was known, on both an unstripped Linux ELF
and a stripped Windows PE:

- **Imported API calls** — correct names *and* argument types, even when stripped,
  because the import table survives stripping
- **String literals** — including wide strings, correctly typed
- **Control flow** — branches, loops and fallback paths are legible
- **Known structs** — `PROCESS_INFORMATION` came back with its real field names
- **Constants** — `0x104` for MAX_PATH, `0xffffffff` for INVALID_FILE_ATTRIBUTES
- **Recursion** and arithmetic, including the compiler's own transformations
  (`i % 2` recovered as `i & 1`)

## What it loses, and what it gets wrong

These matter more than the successes, because each one can mislead.

- **Internal function names are gone** in a stripped binary. Everything is
  `FUN_140001c40`. Recovering meaning means reading the code.
- **Local variable names are always invented**, even unstripped. `param_1`,
  `uVar2` carry no information.
- **Inlined functions lose their boundaries.** A `static` helper the compiler
  inlined does not exist as a function; its logic appears merged into the caller.
  Do not conclude a function is absent because you cannot find it.
- **Type inference can be confidently wrong.** On a variadic call, a `wchar_t*`
  was rendered as `(double)`. The machine behaviour is right; the C is
  misleading. Treat types near varargs and unknown-signature calls with suspicion.
- **Compiler transformations are baked in.** A `for` loop may come back as
  `do-while`. This is faithful to the binary, not to the original source.

The header of every generated `.c` says this too, so it travels with the output.

## Reporting on a binary

State what it *can* do and what it *does*, separately — they are different claims
and conflating them is how analysis becomes alarmism.

Cite evidence: an address, an import, a string. "It spawns a process" is weak;
"`CreateProcessW` at `140001d20`, command line built from
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%s\"` at `14000a118`"
can be checked.

Say what you did not determine. A capability with no reachable call path, a
function you did not read, an encrypted blob you did not unpack — name them
rather than leaving a confident-sounding gap.

## Safety

Analysis runs `--network none`, `--cap-drop ALL`, `--security-opt
no-new-privileges`, with the input mounted read-only. That is hardening against
*the binary* as much as against the tool: the target is assumed hostile.

**It is still static analysis. Nothing is executed.** If a question genuinely
needs the binary to run, say so and stop — do not run it to find out.

The Ghidra supply-chain audit is in `tools/ghidra/AUDIT.md`; `cc ghidra update`
reports upstream changes and never applies them.
