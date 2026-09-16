# Ghidra supply-chain audit

**Subject:** `github.com/NationalSecurityAgency/ghidra` @ `Ghidra_12.1.3_build`
**Date:** 2026-09-16 · **Licence:** Apache-2.0 · **Size:** 406 MB, 15,459 Java files

## What this is and is not

This does **not** prove Ghidra contains no backdoor. Nothing short of a line-by-line
review of ~15,000 Java files plus a native C++ decompiler could attempt that, and
even then the claim would be weak. Anyone who tells you otherwise about a codebase
this size is overstating.

What it does is answer the question that actually determines exposure:

> By what routes could this code send data outward, and is any of them reachable
> without the operator asking for it?

Every finding below has a file and line and is reproducible with
`cc ghidra audit <checkout>`.

## Findings

| Check | Result |
| :--- | :--- |
| Telemetry / analytics / crash-reporting identifiers | **0** |
| `.gov`, `.mil`, `nsa.gov` references in code or config | **0** |
| Auto-update or version-check phone-home | **none found** |
| Network access from a static initializer (i.e. at startup) | **none** |
| Network call sites | 127, all in named modules (below) |
| Build-time command execution | 40 sites |
| Binaries committed in-tree | 16 |
| Third-party dependencies | 68 |

### Network egress, by module

All 127 sites are accounted for. None connects on its own.

| Sites | Module | Why it exists |
| ---: | :--- | :--- |
| 44 | `ghidra/net/*` | Shared HTTP/TLS plumbing — builds clients, SSL contexts, key and trust managers. Provides transport; initiates nothing itself. |
| 26 | `Features/BSim` | Function-similarity database. Connects to a Postgres/Elasticsearch instance **you** configure. |
| 12 | test sources | Not shipped behaviour. |
| 8 | `Features/GhidraServer` | Opt-in multi-user server. Only runs if you start it. |
| 6 | `Framework/Help` | Opens documentation links in a browser. |
| 5 | loopback | `127.0.0.1` only — cannot exfiltrate. |
| 5 | `Features/PDB` | Microsoft symbol server (`msdl.microsoft.com`), opt-in. |
| 4 | LibreTranslate | String translation against an instance you configure. **No default endpoint.** |
| 3 | Ghidra Server client | Only used against a server you configure. |
| 3 | `ghidra://` URL scheme | Ghidra's own project URLs. |
| 2 each | debugger RMI, Eclipse connector, help viewer | Operator-initiated; Eclipse is local. |

### Things worth knowing

- **`debuginfod` has no baked-in URL.** It reads the standard `DEBUGINFOD_URLS`
  environment variable, so it is inert unless you set it.
- **The only external host in a shipped feature is `msdl.microsoft.com`** — Microsoft's
  public symbol server, used by the PDB loader when you ask for symbols.
- **Build dependencies come from Maven Central and a local `flatDir`.** No
  NSA-hosted repository.
- **`log4j` is 2.26.1 and `bouncycastle` 1.84** — both current, well past Log4Shell.
- **The 16 in-tree binaries are benign:** the Gradle wrapper jar, HFS/DMG filesystem
  libraries under `GPL/DMG/`, and deliberately-odd training binaries in
  `GhidraDocs/GhidraClass/ExerciseFiles/` used by the official course.
- **`sentry` appears in 83 files** and is **not** Sentry.io — every hit is a substring
  of `...EntrySet`, `HasEntry`, and similar.

### What the recent changelog shows

The 12.1.3 changes are *hardening*: fixed path traversal in `AndroidProjectCreator`
and the XML `.bytes` importer, command injection in `ShellUtils`, an OOM in trace
storage, an infinite loop in the PEF loader, plus a log4j upgrade. One entry is
directly relevant to this integration — *"Updated the Headless Analyzer to not write
to the user's preferences."* Nothing telemetry-shaped in any recent release.

## Assessment

For the stated threat model — *don't let them see what we're doing* — the evidence
is consistent and unremarkable: no telemetry, no beacon, no update check, nothing
that connects unless you configure or start it. This is what a well-maintained,
security-conscious open-source project looks like.

**But the integration does not rely on that conclusion.** The audit is a review,
not a proof, so the design assumes it could be wrong:

1. Analysis runs with **`--network none`**. No route out means anything missed still
   cannot report.
2. The image is pinned to a **reviewed release tag**, never a moving branch.
3. Updates are **reported, never applied**.
4. Even with a network, the runtime sets a dead proxy and blanks `DEBUGINFOD_URLS`.

The container is the control that holds regardless of what this document got wrong.

## Residual risk — what is *not* covered

- **The 16 binaries cannot be source-reviewed.** They are plausible and match their
  stated purpose, but that is judgement, not verification.
- **68 third-party dependencies** are trusted transitively. A malicious dependency
  needs no change to Ghidra's own source. Only the declared versions are checked.
- **Pattern matching misses obfuscation.** Egress assembled from string fragments or
  reached by reflection would not appear. Grep finds what looks like networking.
- **The native C++ decompiler is not covered** by the Java-source scan.
- **Building requires network access.** The build stage fetches from Maven Central;
  only the analysis stage is isolated.

The `--network none` runtime is what makes each of these tolerable.

## Reproducing

```bash
git clone --depth 1 --branch Ghidra_12.1.3_build \
  https://github.com/NationalSecurityAgency/ghidra.git
cc ghidra audit ghidra                     # full report
cc ghidra audit ghidra --json              # machine-readable
cc ghidra update                           # upstream changes, classified
```

## One honest note on visibility

Cloning a public GitHub repository is ordinary anonymous traffic — GitHub sees it,
NSA is not notified, and they cannot distinguish you from the other 77,000 people
who starred it. There is no way to obtain their code without GitHub knowing you
fetched it. What *is* fully controllable is that Ghidra never talks outward once
it is here, and that is enforced rather than trusted.
