#!/usr/bin/env bash
# ==============================================================================
# Cortex sandbox scenarios.
#
# Each scenario reproduces a real reported failure and then asserts the fix.
# Sourced by entrypoint.sh, which provides: pass, fail, snapshot_home,
# verify_no_leak, stub_calls, WORK, STUB_LOG, SANDBOX_DIR.
# ==============================================================================

CC() { PYTHONPATH="$WORK" python3 -m cortex "$@"; }

# --------------------------------------------------------------------------
# The compaction loop: sessions compacted at startup, then repeatedly.
# Cause: CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=0.45 plus an 85000 window (below the
# CLI's 100k floor). The stub rejects an invalid window exactly like the real
# CLI, so a regression here fails loudly.
# --------------------------------------------------------------------------
scenario_compaction() {
    banner "COMPACTION: no invalid autocompact settings reach the CLI"

    if grep -rq "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" "${WORK}/cortex/" 2>/dev/null; then
        if grep -rq "pop(\"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE\"\|CLAUDE_AUTOCOMPACT_PCT_OVERRIDE\"," "${WORK}/cortex/launcher.py" 2>/dev/null; then
            pass "core strips CLAUDE_AUTOCOMPACT_PCT_OVERRIDE rather than setting it"
        else
            fail "core still sets CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"
        fi
    else
        pass "core never references CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"
    fi

    if grep -q '"autoCompactWindow"' "${WORK}/config/settings.json" 2>/dev/null; then
        fail "config/settings.json still pins autoCompactWindow"
    else
        pass "config/settings.json leaves autoCompactWindow to the CLI default"
    fi

    # The launcher must not leak a stale override from the ambient environment.
    local out
    out=$(CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=0.45 CLAUDE_CODE_AUTO_COMPACT_WINDOW=85000 \
          PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0, '$WORK')
from cortex.launcher import session_env
env = session_env('/tmp/p')
print('PCT' if 'CLAUDE_AUTOCOMPACT_PCT_OVERRIDE' in env else 'no-pct')
print('WIN' if 'CLAUDE_CODE_AUTO_COMPACT_WINDOW' in env else 'no-win')
")
    if [[ "$out" == *"no-pct"* && "$out" == *"no-win"* ]]; then
        pass "launcher strips inherited compaction overrides"
    else
        fail "launcher passes compaction overrides through: $out"
    fi
}

# --------------------------------------------------------------------------
# The re-login bug. Credentials are namespaced by sha256 of the config-dir
# STRING, so differing path spellings are different accounts. And onboarding is
# driven by .claude.json, which was never seeded.
# --------------------------------------------------------------------------
scenario_auth() {
    banner "AUTH: profile stays signed in across launches"

    local out
    out=$(PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0, '$WORK')
from cortex.paths import canonical_dir
forms = ['/tmp/x/main', '/tmp/x/main/', '/tmp/./x/main']
vals = {canonical_dir(f) for f in forms}
print('SAME' if len(vals) == 1 else 'DIFFERENT: %s' % vals)
")
    if [[ "$out" == SAME* ]]; then
        pass "path spellings canonicalize to one credential namespace"
    else
        fail "canonicalization inconsistent -> $out"
    fi

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/profiles"
    CC profile add authtest >/dev/null 2>&1
    CC login authtest >/dev/null 2>&1

    local cfg="${CORTEX_PROFILES_DIR}/authtest/.claude.json"
    if grep -q '"hasCompletedOnboarding": true' "$cfg" 2>/dev/null; then
        pass "login seeds hasCompletedOnboarding (no re-onboarding)"
    else
        fail "hasCompletedOnboarding not seeded -> onboarding will re-run"
    fi
    if grep -q "oauthAccount" "$cfg" 2>/dev/null; then
        pass "login seeds oauthAccount (usage/account context available)"
    else
        fail "oauthAccount not seeded"
    fi

    # A second launch must not report onboarding again.
    local launch
    launch=$(CLAUDE_CONFIG_DIR="${CORTEX_PROFILES_DIR}/authtest" \
             "${HOME}/.local/bin/claude.real" 2>&1)
    if [[ "$launch" == *"onboarding required"* ]]; then
        fail "second launch still triggers onboarding"
    else
        pass "second launch goes straight to a session"
    fi
    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# The prompt hook erased ordinary prompts, because exit 2 on UserPromptSubmit
# blocks AND erases. These are the phrasings that were being swallowed.
# --------------------------------------------------------------------------
scenario_prompt_hook() {
    banner "PROMPT HOOK: ordinary prompts must reach the model"

    local hook="${WORK}/scripts/cortex-prompt-hook.py"
    local should_pass=(
        "switch to the new API client"
        "test this function for edge cases"
        "claude keeps crashing, fix it"
        "continue the refactor from yesterday"
        "update the model config"
        "can you clean up this module"
        "research how tokio schedules tasks"
        "think about the caching strategy"
        "model the retry behaviour"
        "capacity planning for the queue"
    )
    local blocked=0
    for prompt in "${should_pass[@]}"; do
        echo "{\"prompt\": \"${prompt}\"}" | python3 "$hook" >/dev/null 2>&1
        if [ $? -eq 2 ]; then
            fail "ERASED an ordinary prompt: \"${prompt}\""
            blocked=$((blocked + 1))
        fi
    done
    [ $blocked -eq 0 ] && pass "all ${#should_pass[@]} ordinary prompts passed through"

    # The explicit prefix must still work.
    echo '{"prompt": "/cc capacity"}' | python3 "$hook" >/dev/null 2>&1
    if [ $? -eq 2 ]; then
        pass "/cc prefix is still intercepted"
    else
        fail "/cc prefix no longer intercepted"
    fi
}

# --------------------------------------------------------------------------
# Capacity: "no data" must never be reported as free, or failover routes to an
# exhausted account.
# --------------------------------------------------------------------------
scenario_capacity() {
    banner "CAPACITY: unknown is not treated as free"

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/cap-profiles"
    mkdir -p "${CORTEX_PROFILES_DIR}/blank"
    echo synced > "${CORTEX_PROFILES_DIR}/blank/.profile_mode"
    echo '{}' > "${CORTEX_PROFILES_DIR}/blank/.claude.json"

    local out
    out=$(PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0, '$WORK')
from cortex import capacity
r = capacity.inspect('blank', check_auth=False)
print(r['state'])
print('BEST=%s' % capacity.best([r]))
")
    if [[ "$out" == *"unknown"* ]]; then
        pass "profile with no usage data reports 'unknown'"
    else
        fail "expected unknown, got: $out"
    fi
    if [[ "$out" == *"BEST=None"* ]]; then
        pass "auto-selection refuses to pick an unknown profile"
    else
        fail "auto-selection chose a profile with no capacity evidence: $out"
    fi
    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# The IDE wrapper must implement the extension's calling convention:
# wrapper <real-binary> [args...]
# --------------------------------------------------------------------------
scenario_ide_wrapper() {
    banner "IDE WRAPPER: honours the extension calling convention"

    local fake="${SANDBOX_DIR}/fake-claude"
    printf '#!/bin/sh\necho "ARGS:$*"\n' > "$fake"
    chmod +x "$fake"

    local out
    out=$(bash "${WORK}/bin/cortex-ide-wrapper.sh" "$fake" --model opus --effort high 2>&1)
    if [[ "$out" == "ARGS:--model opus --effort high" ]]; then
        pass "shifts the binary path and forwards session args"
    else
        fail "wrapper mangled the invocation -> $out"
    fi

    out=$(bash "${WORK}/bin/cortex-ide-wrapper.sh" 2>&1; echo "rc=$?")
    if [[ "$out" == *"rc=2"* ]]; then
        pass "rejects being called without a binary path"
    else
        fail "expected exit 2 with no arguments -> $out"
    fi
}

# --------------------------------------------------------------------------
# Full install, then uninstall, asserting the official installation survives.
# --------------------------------------------------------------------------
scenario_install_uninstall() {
    banner "INSTALL/UNINSTALL: official Claude Code must survive"

    # Stand in for an official install and an IDE extension.
    mkdir -p "${HOME}/.local/share/claude/versions"
    echo "official-binary" > "${HOME}/.local/share/claude/versions/2.1.273"
    mkdir -p "${HOME}/.vscode/extensions/anthropic.claude-code-2.1.273"
    echo "extension" > "${HOME}/.vscode/extensions/anthropic.claude-code-2.1.273/package.json"
    mkdir -p "${HOME}/.claude"
    echo "my own notes" > "${HOME}/.claude/CLAUDE.md"
    echo '{"oauthAccount":{"emailAddress":"me@example.test"}}' > "${HOME}/.claude.json"

    CORTEX_SANDBOX=1 bash "${WORK}/install.sh" --yes >/dev/null 2>&1
    if [ -f "${HOME}/.claude/cortex-core/cortex/__main__.py" ]; then
        pass "install deployed the Cortex core"
    else
        fail "install did not deploy the Cortex core"
    fi

    ( cd "$WORK" && bash uninstall.sh --yes >/dev/null 2>&1 )

    local survived=1
    [ -f "${HOME}/.local/share/claude/versions/2.1.273" ] || { fail "uninstall deleted the official binary"; survived=0; }
    [ -f "${HOME}/.vscode/extensions/anthropic.claude-code-2.1.273/package.json" ] || { fail "uninstall deleted the IDE extension"; survived=0; }
    [ -f "${HOME}/.claude.json" ] || { fail "uninstall deleted ~/.claude.json (sign-in/MCP/trust)"; survived=0; }
    grep -q "my own notes" "${HOME}/.claude/CLAUDE.md" 2>/dev/null || { fail "uninstall destroyed user CLAUDE.md"; survived=0; }
    [ $survived -eq 1 ] && pass "official install, IDE extension, and user data all survived"

    # Clean up this scenario's scaffolding. The fake "official binary" is a
    # non-executable text file, and uninstall legitimately removed the
    # claude.real symlink - leaving both behind made a LATER scenario resolve the
    # decoy, fail to exec it, and silently test nothing.
    rm -rf "${HOME}/.local/share/claude"
    install -m 0755 "${WORK}/tests/sandbox/stub-claude.py" "${HOME}/.local/bin/claude.real"
}

# --------------------------------------------------------------------------
# The always-on prompt budget. The point of the rules rewrite was to stop
# loading a large fixed payload on every request.
# --------------------------------------------------------------------------
scenario_rules_budget() {
    banner "RULES: always-on payload stays small and consistent"

    local lines
    lines=$(cat "${WORK}/config/CLAUDE.md" "${WORK}/config/rules/"*.md 2>/dev/null | wc -l)
    if [ "$lines" -le 200 ]; then
        pass "always-on payload is ${lines} lines (budget 200)"
    else
        fail "always-on payload grew to ${lines} lines"
    fi

    # The contradictions that made the old ruleset unfollowable.
    local all; all=$(cat "${WORK}/config/CLAUDE.md" "${WORK}/config/rules/"*.md 2>/dev/null)
    if grep -q "Intent Expansion Blueprint" <<< "$all"; then
        fail "header-card mandate is back, contradicting the no-preamble rule"
    else
        pass "no header-card mandate"
    fi
    if grep -qi "extra amendments" <<< "$all"; then
        fail "closing-question mandate is back, contradicting no-concluding-fluff"
    else
        pass "no closing-question mandate"
    fi
    if grep -q 'C:\\\\Claude\\\\Tools' <<< "$all"; then
        fail "hardcoded Windows tool path in always-on rules"
    else
        pass "no dead Windows paths"
    fi
}

# --------------------------------------------------------------------------
# Every installer must deploy the Python core. The shells are shims, so an
# installer that copies them without the core produces a Cortex where every
# single command fails with "Cortex core not found". install.ps1 and install.py
# both shipped in exactly that state.
# --------------------------------------------------------------------------
scenario_installers_complete() {
    banner "INSTALLERS: each one must deploy the Python core"

    # Each installer must both name the core destination and actually copy the
    # package. Checked with fixed strings - a clever regex here previously
    # expanded a shell variable and aborted the whole run.
    for f in install.sh install.py install.ps1; do
        names_dest=0
        copies=0
        grep -qF 'cortex-core' "${WORK}/$f" 2>/dev/null && names_dest=1
        if grep -qF 'cp -r "${SCRIPT_DIR}/cortex"' "${WORK}/$f" 2>/dev/null            || grep -qF 'shutil.copytree(src_core' "${WORK}/$f" 2>/dev/null            || grep -qF 'Copy-Item -Path (Join-Path $ScriptDir "cortex")' "${WORK}/$f" 2>/dev/null; then
            copies=1
        fi
        if [ $names_dest -eq 1 ] && [ $copies -eq 1 ]; then
            pass "$f deploys the cortex package"
        else
            fail "$f does not deploy the cortex package -> every command would fail"
        fi
    done

    # End to end: a real install must produce a working `cc`.
    CORTEX_SANDBOX=1 bash "${WORK}/install.sh" --yes >/dev/null 2>&1
    local out
    out=$("${HOME}/.local/bin/claude" version 2>&1)
    if [[ "$out" == *"Claude Cortex"* ]]; then
        pass "installed wrapper runs: $out"
    else
        fail "installed wrapper does not run -> $out"
    fi

    # And the cc alias must work through the symlink.
    out=$("${HOME}/.local/bin/cc" version 2>&1)
    if [[ "$out" == *"Claude Cortex"* ]]; then
        pass "cc alias resolves the core through the symlink"
    else
        fail "cc alias broken -> $out"
    fi
}

# --------------------------------------------------------------------------
# Argument handling. A prompt must never be mistaken for a subcommand or a
# profile name, and effort values must be validated before reaching the CLI.
# --------------------------------------------------------------------------
scenario_args() {
    banner "ARGS: translation and prompt safety"

    local out
    out=$(PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0, '$WORK')
from cortex.launcher import translate_args
cases = [
    (['-s'],                 ['--model','claude-sonnet-5']),
    (['-o'],                 ['--model','claude-opus-5']),
    (['-H'],                 ['--model','claude-haiku-4-5']),
    (['-e','high'],          ['--effort','high']),
    (['--effort=xhigh'],     ['--effort','xhigh']),
    (['-t'],                 ['--model','claude-haiku-4-5','--effort','low']),
    (['-y'],                 ['--dangerously-skip-permissions']),
    (['fix the bug'],        ['fix the bug']),
]
bad = 0
for args, want in cases:
    got, err = translate_args(args)
    if got != want:
        print('MISMATCH %s -> %s (want %s)' % (args, got, want)); bad += 1
# invalid effort must be refused, not forwarded
got, err = translate_args(['-e','ludicrous'])
if not err:
    print('NO-VALIDATION'); bad += 1
# --thinking must not appear: it is undocumented
allout = []
for a in [['-t'], ['--think-off']]:
    g, _ = translate_args(a); allout += g
if '--thinking' in allout:
    print('USES-UNDOCUMENTED-THINKING'); bad += 1
print('OK' if bad == 0 else 'FAILURES=%d' % bad)
")
    if [[ "$out" == OK ]]; then
        pass "all flag translations correct, invalid effort rejected, no --thinking"
    else
        fail "argument translation problems -> $out"
    fi
}

# --------------------------------------------------------------------------
# Resolution must never select the Cortex wrapper itself as the "real" binary:
# that is an exec loop that forks until the machine gives up.
# --------------------------------------------------------------------------
scenario_no_exec_loop() {
    banner "BINARY: never exec ourselves"

    local decoy="${SANDBOX_DIR}/bin-decoy"
    mkdir -p "$decoy"
    printf '#!/usr/bin/env bash\n# Claude Cortex - shim\necho loop\n' > "${decoy}/claude.real"
    chmod +x "${decoy}/claude.real"

    local out
    out=$(PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0, '$WORK')
from cortex import binary
print('SKIPPED' if binary._is_cortex_wrapper('${decoy}/claude.real') else 'NOT-DETECTED')
")
    if [[ "$out" == SKIPPED ]]; then
        pass "a Cortex wrapper is recognised and never treated as the real binary"
    else
        fail "wrapper not detected -> exec loop possible"
    fi
}

# --------------------------------------------------------------------------
# doctor must actually detect the failure modes it exists to catch.
# --------------------------------------------------------------------------
scenario_doctor() {
    banner "DOCTOR: detects and repairs the known failure modes"

    mkdir -p "${HOME}/.claude"
    cat > "${HOME}/.claude/settings.json" <<'JSON'
{
  "autoCompactWindow": 85000,
  "bashOutputMaxChars": 6000,
  "hooks": {"UserPromptSubmit": [{"matcher": "", "hooks": [{"type":"command","command":"x"}]}]}
}
JSON

    local out
    out=$(PYTHONPATH="$WORK" python3 -m cortex doctor 2>&1)
    for probe in "autoCompactWindow=85000" "bashOutputMaxChars=6000" "matcher"; do
        if grep -q "$probe" <<< "$out"; then
            pass "doctor flags $probe"
        else
            fail "doctor missed $probe"
        fi
    done

    PYTHONPATH="$WORK" python3 -m cortex doctor --repair >/dev/null 2>&1
    if grep -q "autoCompactWindow" "${HOME}/.claude/settings.json" 2>/dev/null; then
        fail "--repair left the invalid autoCompactWindow in place"
    else
        pass "--repair removed the invalid autoCompactWindow"
    fi
    if [ -f "${HOME}/.claude/settings.json.bak" ]; then
        pass "--repair wrote a backup before changing settings"
    else
        fail "--repair changed settings with no backup"
    fi
}

# --------------------------------------------------------------------------
# The whole user journey, in order, the way a person actually uses it.
# Unit-level checks kept passing while the product was unusable, so this walks
# the real path: install, create, sign in, launch, switch, resume, diagnose.
# --------------------------------------------------------------------------
scenario_e2e() {
    banner "E2E: full user journey"

    CORTEX_SANDBOX=1 bash "${WORK}/install.sh" --yes >/dev/null 2>&1
    local CCBIN="${HOME}/.local/bin/cc"

    # 1. No profiles yet: must explain, not crash or launch something.
    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/e2e-profiles"
    local out
    out=$("$CCBIN" 2>&1); local rc=$?
    if [[ "$out" == *"No profiles configured"* ]] && [ $rc -ne 0 ]; then
        pass "bare launch with no profiles explains what to do"
    else
        fail "unhelpful no-profile behaviour (rc=$rc): $out"
    fi

    # 2. Create two profiles.
    "$CCBIN" profile add work >/dev/null 2>&1
    "$CCBIN" profile add personal >/dev/null 2>&1
    if [ -d "${CORTEX_PROFILES_DIR}/work" ] && [ -d "${CORTEX_PROFILES_DIR}/personal" ]; then
        pass "created two profiles"
    else
        fail "profile creation failed"
    fi

    # 3. Sign in to one. Identity must be seeded.
    "$CCBIN" login work >/dev/null 2>&1
    if grep -q '"hasCompletedOnboarding": true' "${CORTEX_PROFILES_DIR}/work/.claude.json" 2>/dev/null; then
        pass "login seeded identity for 'work'"
    else
        fail "login did not seed identity"
    fi

    # 4. Isolation: signing into one profile must not sign in the other.
    if grep -q "oauthAccount" "${CORTEX_PROFILES_DIR}/personal/.claude.json" 2>/dev/null; then
        fail "credentials leaked between profiles"
    else
        pass "profiles are credential-isolated"
    fi

    # 5. Launch must reach the CLI with the right config dir.
    : > "$STUB_LOG"
    "$CCBIN" -work -s >/dev/null 2>&1
    if grep -q "claude-sonnet-5" "$STUB_LOG" 2>/dev/null; then
        pass "model alias -s reached the CLI"
    else
        fail "model alias did not reach the CLI"
    fi
    if grep -qF "${CORTEX_PROFILES_DIR}/work" "$STUB_LOG" 2>/dev/null; then
        pass "session ran with the work profile's config dir"
    else
        fail "wrong or missing CLAUDE_CONFIG_DIR in the launched session"
    fi

    # 6. Both isolation variables must carry the SAME string, or the credential
    #    namespace differs and the session appears signed out.
    out=$(python3 -c "
import json,sys
last=None
for line in open('$STUB_LOG'):
    try: last=json.loads(line)
    except Exception: pass
e=(last or {}).get('env',{})
a=e.get('CLAUDE_CONFIG_DIR'); b=e.get('CLAUDE_SECURESTORAGE_CONFIG_DIR')
print('MATCH' if a and a==b else 'MISMATCH %r %r'%(a,b))
")
    if [[ "$out" == MATCH ]]; then
        pass "config dir and securestorage dir are byte-identical"
    else
        fail "credential namespace split -> $out"
    fi

    # 7. A prompt must be forwarded verbatim, not eaten as a subcommand.
    : > "$STUB_LOG"
    "$CCBIN" -work "refactor the switch statement" >/dev/null 2>&1
    if grep -qF "refactor the switch statement" "$STUB_LOG" 2>/dev/null; then
        pass "prompt forwarded verbatim"
    else
        fail "prompt was not forwarded"
    fi

    # 8. Switching.
    "$CCBIN" switch personal >/dev/null 2>&1
    if [ "$(cat "${CORTEX_PROFILES_DIR}/current_profile" 2>/dev/null)" = "personal" ]; then
        pass "switch changed the active profile"
    else
        fail "switch did not take effect"
    fi

    # 9. continue must pass --continue through.
    : > "$STUB_LOG"
    "$CCBIN" continue work >/dev/null 2>&1
    if grep -q '"--continue"' "$STUB_LOG" 2>/dev/null; then
        pass "continue resumed with --continue"
    else
        fail "continue did not pass --continue"
    fi

    # 10. status and doctor must run cleanly.
    out=$("$CCBIN" status 2>&1)
    if [[ "$out" == *"work"* && "$out" == *"personal"* ]]; then
        pass "status lists both profiles"
    else
        fail "status output incomplete: $out"
    fi
    "$CCBIN" doctor >/dev/null 2>&1
    if [ $? -le 1 ]; then
        pass "doctor runs without crashing"
    else
        fail "doctor crashed"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# Degraded environments. These must fail with an explanation, never a traceback.
# --------------------------------------------------------------------------
scenario_degraded() {
    banner "DEGRADED: clear errors, never a traceback"

    CORTEX_SANDBOX=1 bash "${WORK}/install.sh" --yes >/dev/null 2>&1
    local CCBIN="${HOME}/.local/bin/cc"
    local out

    # No Claude binary at all.
    out=$(CORTEX_REAL_CLAUDE="/nonexistent/claude" PATH="/usr/bin:/bin" "$CCBIN" status 2>&1)
    if [[ "$out" == *"Traceback"* ]]; then
        fail "traceback when the binary is missing"
    else
        pass "missing binary handled without a traceback"
    fi

    # Corrupt settings.json must not crash doctor.
    echo 'this is not json {{{' > "${HOME}/.claude/settings.json"
    out=$("$CCBIN" doctor 2>&1)
    if [[ "$out" == *"Traceback"* ]]; then
        fail "traceback on corrupt settings.json"
    else
        pass "corrupt settings.json handled gracefully"
    fi
    echo '{}' > "${HOME}/.claude/settings.json"

    # Corrupt profile .claude.json must not crash status.
    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/degraded"
    mkdir -p "${CORTEX_PROFILES_DIR}/broken"
    echo 'not json' > "${CORTEX_PROFILES_DIR}/broken/.claude.json"
    out=$("$CCBIN" status 2>&1)
    if [[ "$out" == *"Traceback"* ]]; then
        fail "traceback on corrupt profile config"
    else
        pass "corrupt profile config handled gracefully"
    fi

    # Unknown profile must produce a helpful message.
    out=$("$CCBIN" switch nosuchprofile 2>&1)
    if [[ "$out" == *"not found"* ]]; then
        pass "unknown profile reports a helpful error"
    else
        fail "unhelpful unknown-profile error: $out"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# No command may silently become a prompt. Before the tool dispatcher existed,
# twelve legacy subcommands (docs, menu, palace, dream, ...) fell through to the
# session launcher and were sent to Claude AS THE PROMPT - a real API call, real
# tokens, to answer the word "palace".
# --------------------------------------------------------------------------
scenario_no_prompt_leak() {
    banner "DISPATCH: commands must never leak into a session as prompts"

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/leak-profiles"
    CC profile add main >/dev/null 2>&1
    CC login main >/dev/null 2>&1
    : > "$STUB_LOG"

    for cmd in docs menu turbo fast effort reasoning clean test bench nonsensecmd; do
        CC "$cmd" >/dev/null 2>&1
    done

    local leaked
    leaked=$(python3 -c "
import json
n=0
for line in open('$STUB_LOG'):
    try: d=json.loads(line)
    except Exception: continue
    a=d.get('argv',[])
    if a and a[0] not in ('auth','--version','update'):
        n+=1; print('   leaked:', a)
print('COUNT=%d' % n)
")
    if [[ "$leaked" == *"COUNT=0"* ]]; then
        pass "no retired or unknown command reached a session"
    else
        fail "commands leaked into sessions -> $leaked"
    fi

    # Retired commands must explain themselves.
    local out
    out=$(CC docs 2>&1)
    if [[ "$out" == *"no longer a Cortex command"* ]]; then
        pass "retired commands explain the replacement"
    else
        fail "retired command gave an unhelpful error: $out"
    fi

    # Unknown commands must suggest, not guess.
    out=$(CC nonsensecmd 2>&1)
    if [[ "$out" == *"unknown command"* && "$out" == *"cc -- nonsensecmd"* ]]; then
        pass "unknown command suggests the -- prompt escape"
    else
        fail "unknown command message unhelpful: $out"
    fi

    # The -- escape must still deliver a one-word prompt.
    : > "$STUB_LOG"
    CC -- docs >/dev/null 2>&1
    if grep -q '"docs"' "$STUB_LOG" 2>/dev/null; then
        pass "'cc -- docs' delivers docs as a prompt"
    else
        fail "-- escape did not forward the prompt"
    fi

    # Real tools must still dispatch to their scripts, not to a session.
    : > "$STUB_LOG"
    out=$(CC palace 2>&1)
    if grep -qE '"argv": \["palace"' "$STUB_LOG" 2>/dev/null; then
        fail "'cc palace' went to a session instead of the palace tool"
    else
        pass "'cc palace' dispatched to the tool, not a session"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# Windows parity. The old PowerShell wrapper was a separate 565-line
# reimplementation that had drifted badly - missing login, profile management,
# and doctor entirely - precisely because nothing ever executed it. Now that it
# is a shim over the shared core, running it under pwsh proves the two entry
# points really do behave the same.
#
# Skipped when pwsh is unavailable (build with --build-arg INSTALL_PWSH=1).
# --------------------------------------------------------------------------
scenario_powershell() {
    banner "POWERSHELL: the Windows shim reaches the same core"

    if ! command -v pwsh >/dev/null 2>&1; then
        pass "pwsh not installed - skipping (build with INSTALL_PWSH=1)"
        return 0
    fi

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/ps-profiles"
    local ps="${WORK}/bin/claude.ps1"
    local out

    out=$(CORTEX_HOME="$WORK" pwsh -NoProfile -File "$ps" version 2>&1)
    if [[ "$out" == *"Claude Cortex"* ]]; then
        pass "PowerShell shim runs the core: $(echo "$out" | tr -d '\r')"
    else
        fail "PowerShell shim did not reach the core -> $out"
    fi

    # The command surface must match bash, not a reduced subset.
    for cmd in "--help" "doctor" "status"; do
        out=$(CORTEX_HOME="$WORK" pwsh -NoProfile -File "$ps" "$cmd" 2>&1)
        if [[ "$out" == *"not found"* || "$out" == *"Exception"* ]]; then
            fail "PowerShell shim failed on '$cmd' -> $(echo "$out" | head -2)"
        else
            pass "PowerShell shim handles '$cmd'"
        fi
    done

    # Critically: the canonical config dir must be identical from both shells, or
    # the two entry points land in different credential namespaces.
    local bash_dir ps_dir
    bash_dir=$(PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0,'$WORK')
from cortex.paths import profile_dir; print(profile_dir('psmain'))")
    ps_dir=$(CORTEX_HOME="$WORK" pwsh -NoProfile -Command "
\$env:PYTHONPATH='$WORK'
python3 -c \"import sys; sys.path.insert(0,'$WORK')
from cortex.paths import profile_dir; print(profile_dir('psmain'))\"" 2>&1 | tr -d '\r')

    if [ "$bash_dir" = "$ps_dir" ]; then
        pass "bash and PowerShell resolve an identical config dir"
    else
        fail "config dir differs by shell -> bash='$bash_dir' pwsh='$ps_dir'"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# Installing twice must be safe and must not duplicate or corrupt anything.
# People re-run installers after a git pull without thinking about it.
# --------------------------------------------------------------------------
scenario_idempotent() {
    banner "IDEMPOTENCY: installing twice is safe"

    CORTEX_SANDBOX=1 bash "${WORK}/install.sh" --yes >/dev/null 2>&1
    local first
    first=$(python3 "$LEAK_CHECK" snapshot "$HOME" "${SANDBOX_DIR}/after-first.json" --quiet; echo done)

    # Put a user customization in place; a second install must not destroy it.
    echo '{"theme":"light","model":"opus","mySetting":true}' > "${HOME}/.claude/settings.json"
    echo "user notes" > "${HOME}/.claude/CLAUDE.md.user"

    CORTEX_SANDBOX=1 bash "${WORK}/install.sh" --yes >/dev/null 2>&1

    if grep -q "mySetting" "${HOME}/.claude/settings.json" 2>/dev/null; then
        pass "second install preserved existing settings.json"
    else
        fail "second install overwrote settings.json"
    fi
    if [ -f "${HOME}/.claude/CLAUDE.md.user" ]; then
        pass "second install preserved user files"
    else
        fail "second install removed user files"
    fi

    local out
    out=$("${HOME}/.local/bin/cc" version 2>&1)
    if [[ "$out" == *"Claude Cortex"* ]]; then
        pass "cc still works after reinstall"
    else
        fail "reinstall broke cc -> $out"
    fi

    # The core must be replaced cleanly, not merged with a stale copy.
    local stale
    stale=$(find "${HOME}/.claude/cortex-core" -name "*.py.orig" -o -name "*.rej" 2>/dev/null | wc -l)
    if [ "$stale" -eq 0 ]; then
        pass "core replaced cleanly with no leftovers"
    else
        fail "reinstall left $stale stale file(s) in the core"
    fi
}

# --------------------------------------------------------------------------
# The hooks must survive real-world input: multimodal payloads, huge prompts,
# unicode, and malformed JSON. A hook that throws blocks the session.
# --------------------------------------------------------------------------
scenario_hook_robustness() {
    banner "HOOKS: survive malformed and hostile input"

    local hook="${WORK}/scripts/cortex-prompt-hook.py"
    local pre="${WORK}/scripts/cortex-pretool-hook.py"

    local inputs=(
        '{"prompt": ""}'
        '{"prompt": null}'
        'not json at all'
        ''
        '{"prompt": {"nested": {"deeply": {"text": "hello"}}}}'
        '{"prompt": [{"type":"image","source":{"data":"AAAA"}},{"type":"text","text":"describe"}]}'
        '{"prompt": "emoji and unicode: éè 你好"}'
    )
    local crashed=0
    for payload in "${inputs[@]}"; do
        printf '%s' "$payload" | python3 "$hook" >/dev/null 2>"${SANDBOX_DIR}/hookerr"
        local rc=$?
        if [ $rc -ne 0 ] && [ $rc -ne 2 ]; then
            fail "prompt hook exited $rc on: ${payload:0:40}"
            crashed=1
        fi
        if grep -q "Traceback" "${SANDBOX_DIR}/hookerr" 2>/dev/null; then
            fail "prompt hook traceback on: ${payload:0:40}"
            crashed=1
        fi
    done
    [ $crashed -eq 0 ] && pass "prompt hook survived ${#inputs[@]} malformed payloads"

    # A very large prompt must not hang or crash the hook.
    python3 -c "
import json,sys
sys.stdout.write(json.dumps({'prompt': 'x' * 500000}))" | timeout 10 python3 "$hook" >/dev/null 2>&1
    if [ $? -le 2 ]; then
        pass "prompt hook handles a 500KB prompt"
    else
        fail "prompt hook failed on a large prompt"
    fi

    # PreTool hook: malformed input must fail open, never block a legitimate call.
    printf 'garbage' | python3 "$pre" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        pass "pretool hook fails open on malformed input"
    else
        fail "pretool hook blocks on malformed input (would break the session)"
    fi

    # And it must still block what it is for.
    echo '{"tool_name":"Bash","tool_input":{"command":"cat package-lock.json"}}' | python3 "$pre" >/dev/null 2>&1
    if [ $? -eq 2 ]; then
        pass "pretool hook still blocks lockfile dumps"
    else
        fail "pretool hook no longer blocks lockfile dumps"
    fi
}

# --------------------------------------------------------------------------
# `cc ide apply` writes into the user's IDE settings.json - a file full of their
# themes, keybindings, and extension config. It must be additive and atomic.
# --------------------------------------------------------------------------
scenario_ide_apply() {
    banner "IDE APPLY: additive, atomic, never destructive"

    # Stand up a fake VS Code install with real-looking user settings.
    local ext="${HOME}/.vscode/extensions/anthropic.claude-code-2.1.273"
    mkdir -p "$ext"
    echo '{}' > "${ext}/package.json"
    local vsdir="${HOME}/.config/Code/User"
    mkdir -p "$vsdir"
    cat > "${vsdir}/settings.json" <<'JSON'
{
  "workbench.colorTheme": "Solarized Dark",
  "editor.fontSize": 14,
  "editor.fontFamily": "JetBrains Mono",
  "files.autoSave": "onFocusChange"
}
JSON

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/ide-profiles"
    CC profile add work >/dev/null 2>&1
    CC login work >/dev/null 2>&1

    # check must never write.
    local before after
    before=$(md5sum "${vsdir}/settings.json" | cut -d' ' -f1)
    CC ide check >/dev/null 2>&1
    after=$(md5sum "${vsdir}/settings.json" | cut -d' ' -f1)
    if [ "$before" = "$after" ]; then
        pass "'ide check' did not modify settings.json"
    else
        fail "'ide check' modified settings.json"
    fi

    # dry run must not write either.
    CC ide apply >/dev/null 2>&1
    after=$(md5sum "${vsdir}/settings.json" | cut -d' ' -f1)
    if [ "$before" = "$after" ]; then
        pass "'ide apply' without --yes is a dry run"
    else
        fail "'ide apply' wrote without --yes"
    fi

    # Real write: Cortex keys added, user keys untouched.
    CC ide apply --yes >/dev/null 2>&1
    local out
    out=$(python3 -c "
import json
d = json.load(open('${vsdir}/settings.json'))
checks = []
checks.append(('theme-kept', d.get('workbench.colorTheme') == 'Solarized Dark'))
checks.append(('font-kept', d.get('editor.fontFamily') == 'JetBrains Mono'))
checks.append(('autosave-kept', d.get('files.autoSave') == 'onFocusChange'))
ev = d.get('claudeCode.environmentVariables') or []
names = {e.get('name') for e in ev if isinstance(e, dict)}
checks.append(('config-dir-set', 'CLAUDE_CONFIG_DIR' in names))
checks.append(('securestorage-set', 'CLAUDE_SECURESTORAGE_CONFIG_DIR' in names))
vals = {e.get('value') for e in ev if isinstance(e, dict)}
checks.append(('both-identical', len(vals) == 1))
checks.append(('login-prompt-off', d.get('claudeCode.disableLoginPrompt') is True))
bad = [n for n, ok in checks if not ok]
print('OK' if not bad else 'FAILED: ' + ','.join(bad))
" 2>&1)
    if [[ "$out" == OK ]]; then
        pass "Cortex keys written, every user setting preserved, values identical"
    else
        fail "ide apply produced bad settings -> $out"
    fi

    if [ -f "${vsdir}/settings.json.bak" ]; then
        pass "a backup was written before modifying settings.json"
    else
        fail "settings.json modified with no backup"
    fi

    # Applying twice must be a no-op, not a duplicate.
    CC ide apply --yes >/dev/null 2>&1
    out=$(python3 -c "
import json
d = json.load(open('${vsdir}/settings.json'))
print(len(d.get('claudeCode.environmentVariables') or []))")
    if [ "$out" = "2" ]; then
        pass "re-applying does not duplicate entries"
    else
        fail "re-applying produced $out entries (expected 2)"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# install.py is a separate code path from install.sh and is what Windows users
# fall back to. It shipped without deploying the core at all.
# --------------------------------------------------------------------------
scenario_install_py() {
    banner "INSTALL.PY: the Python installer produces a working install"

    # Clear anything a previous scenario installed.
    rm -rf "${HOME}/.claude/cortex-core" "${HOME}/.local/bin/claude" "${HOME}/.local/bin/cc"

    local out
    out=$(python3 "${WORK}/install.py" --dry-run 2>&1)
    if [[ "$out" == *"DRY RUN"* ]] && [ ! -d "${HOME}/.claude/cortex-core" ]; then
        pass "install.py --dry-run changes nothing"
    else
        fail "install.py --dry-run wrote something"
    fi

    CORTEX_SANDBOX=1 python3 "${WORK}/install.py" --yes >/dev/null 2>&1

    if [ -f "${HOME}/.claude/cortex-core/cortex/__main__.py" ]; then
        pass "install.py deployed the Cortex core"
    else
        fail "install.py did not deploy the core -> every command would fail"
    fi

    if [ -f "${HOME}/.local/bin/claude" ]; then
        out=$(PYTHONPATH="${HOME}/.claude/cortex-core" python3 -m cortex version 2>&1)
        if [[ "$out" == *"Claude Cortex"* ]]; then
            pass "core installed by install.py is runnable: $out"
        else
            fail "core installed by install.py does not run -> $out"
        fi
    else
        fail "install.py did not install the wrapper"
    fi
}

# --------------------------------------------------------------------------
# There must be exactly one capacity implementation. The standalone script and
# the core once disagreed: the script called a profile with no usage data
# "Ready (100% capacity free)" and ranked it best, so failover could switch to
# an exhausted account. Both paths must now give the same answer.
# --------------------------------------------------------------------------
scenario_capacity_agreement() {
    banner "CAPACITY: the script and the core agree"

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/agree-profiles"
    mkdir -p "${CORTEX_PROFILES_DIR}/blank"
    echo synced > "${CORTEX_PROFILES_DIR}/blank/.profile_mode"
    echo '{}' > "${CORTEX_PROFILES_DIR}/blank/.claude.json"

    local script_out
    script_out=$(PYTHONPATH="$WORK" python3 "${WORK}/scripts/claude-capacity-check.py" 2>&1)

    if grep -qi "100% capacity free" <<< "$script_out"; then
        fail "the standalone script still calls unknown capacity 'free'"
    else
        pass "standalone script no longer reports unknown as free"
    fi
    # It must not claim availability it cannot substantiate. Either "unknown"
    # (no usage data) or "signed out" (not authenticated) is an honest answer;
    # "available" for a profile with no evidence is not.
    if grep -qiE "unknown|signed out" <<< "$script_out"; then
        pass "standalone script reports the state honestly"
    else
        fail "standalone script output unexpected -> $(head -5 <<< "$script_out")"
    fi
    if grep -qi "available" <<< "$script_out"; then
        fail "standalone script claims availability without evidence"
    else
        pass "standalone script claims no unsubstantiated availability"
    fi

    # --best must print nothing and fail when no profile has evidence of capacity.
    local best rc
    best=$(PYTHONPATH="$WORK" python3 "${WORK}/scripts/claude-capacity-check.py" --best 2>/dev/null)
    rc=$?
    if [ -z "$best" ] && [ $rc -ne 0 ]; then
        pass "--best refuses to name a profile with unknown capacity"
    else
        fail "--best named '$best' (rc=$rc) despite no capacity evidence"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# Edge cases in dispatch. Each of these was a real bug: a path that bypassed the
# no-profile check, silently created an unauthenticated profile, and either
# launched into it or opened a browser login nobody asked for.
# --------------------------------------------------------------------------
scenario_edge_cases() {
    banner "EDGE CASES: no silent profile creation or stray logins"

    local out

    # 1. The -- prompt escape must not conjure a profile.
    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/edge1"
    out=$(CC -- "hello world" 2>&1 | head -1)
    if [[ "$out" == *"No profiles configured"* ]]; then
        pass "'cc -- <prompt>' refuses when no profile exists"
    else
        fail "'cc --' did not refuse -> $out"
    fi
    if [ -z "$(ls "$CORTEX_PROFILES_DIR" 2>/dev/null)" ]; then
        pass "'cc --' created no directories"
    else
        fail "'cc --' created: $(ls "$CORTEX_PROFILES_DIR")"
    fi

    # 2. continue must not start a login flow out of nowhere.
    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/edge2"
    out=$(CC continue 2>&1 | head -1)
    if [[ "$out" == *"No profiles configured"* ]]; then
        pass "'cc continue' refuses when no profile exists"
    else
        fail "'cc continue' did not refuse -> $out"
    fi

    # 3. Removing the last profile must clear the active pointer, or the next
    #    launch recreates the deleted profile unauthenticated.
    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/edge3"
    CC profile add solo >/dev/null 2>&1
    CC switch solo >/dev/null 2>&1
    CC profile remove solo </dev/null >/dev/null 2>&1
    local active
    active=$(cat "${CORTEX_PROFILES_DIR}/current_profile" 2>/dev/null)
    if [ -z "$active" ]; then
        pass "removing the last profile cleared the active pointer"
    else
        fail "active pointer still names the deleted profile: '$active'"
    fi
    CC >/dev/null 2>&1
    if [ -z "$(ls "$CORTEX_PROFILES_DIR" 2>/dev/null | grep -v current_profile)" ]; then
        pass "next launch did not recreate the deleted profile"
    else
        fail "deleted profile was silently recreated"
    fi

    # 4. Launching a profile that does not exist must name the alternatives.
    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/edge4"
    CC profile add real >/dev/null 2>&1
    out=$(CC -ghost 2>&1 | head -2 | tr '\n' ' ')
    if [[ "$out" == *"no profile named"* ]]; then
        pass "launching a nonexistent profile is refused, listing alternatives"
    else
        fail "nonexistent profile not refused -> $out"
    fi
    if [[ "$out" == *"Logged in"* || "$out" == *"session started"* ]]; then
        fail "a session was started before refusing"
    else
        pass "no session was started for a mistyped profile"
    fi

    # 5. A profile may not shadow a command name.
    out=$(CC profile add status </dev/null 2>&1 | head -1)
    if [[ "$out" == *"is a Cortex command"* ]]; then
        pass "refuses a profile name that shadows a command"
    else
        fail "allowed an unreachable profile name -> $out"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# Paths with spaces and the two profile modes. Spaces in a home directory are
# ordinary on Windows ("C:\Users\First Last") and break naively-quoted shells.
# --------------------------------------------------------------------------
scenario_paths_and_modes() {
    banner "PATHS & MODES: spaces, synced vs isolated"

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/my profiles/cortex"
    CC profile add spacey >/dev/null 2>&1
    CC login spacey >/dev/null 2>&1
    : > "$STUB_LOG"
    CC -spacey -s >/dev/null 2>&1

    local out
    out=$(python3 -c "
import json
last = None
for line in open('$STUB_LOG'):
    try: last = json.loads(line)
    except Exception: pass
e = (last or {}).get('env', {})
a, b = e.get('CLAUDE_CONFIG_DIR'), e.get('CLAUDE_SECURESTORAGE_CONFIG_DIR')
ok = a and ' ' in a and a == b
print('OK' if ok else 'BAD a=%r b=%r' % (a, b))
")
    if [[ "$out" == OK ]]; then
        pass "a config dir containing spaces survives intact and matches"
    else
        fail "spaces in the path broke the config dir -> $out"
    fi

    # Synced links shared content; isolated does not.
    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/modes"
    mkdir -p "${HOME}/.claude/commands"
    echo "shared" > "${HOME}/.claude/commands/shared.md"
    CC profile add syncedone >/dev/null 2>&1
    CC profile add isoone --isolated >/dev/null 2>&1

    if [ "$(cat "${CORTEX_PROFILES_DIR}/syncedone/.profile_mode" 2>/dev/null)" = "synced" ] \
       && [ "$(cat "${CORTEX_PROFILES_DIR}/isoone/.profile_mode" 2>/dev/null)" = "isolated" ]; then
        pass "profile modes recorded correctly"
    else
        fail "profile mode not recorded"
    fi

    if [ -e "${CORTEX_PROFILES_DIR}/syncedone/commands" ]; then
        pass "synced profile shares commands"
    else
        fail "synced profile did not link shared content"
    fi
    if [ ! -e "${CORTEX_PROFILES_DIR}/isoone/commands" ]; then
        pass "isolated profile does not share commands"
    else
        fail "isolated profile linked shared content"
    fi

    # settings.json must be a real file in both modes, never a link: Claude Code
    # writes it itself, and a link either leaks across profiles or is lost.
    local linked=0
    for p in syncedone isoone; do
        if [ -L "${CORTEX_PROFILES_DIR}/${p}/settings.json" ]; then
            fail "$p settings.json is a link"
            linked=1
        fi
    done
    [ $linked -eq 0 ] && pass "settings.json is a real file in both modes"

    # Numeric switch.
    out=$(CC switch 2 2>&1 | head -1)
    if [[ "$out" == *"Active profile"* ]]; then
        pass "switching by index works"
    else
        fail "numeric switch failed -> $out"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# IDE detection must find every supported IDE, and report a stale duplicate
# extension rather than silently configuring whichever loads first.
# --------------------------------------------------------------------------
scenario_ide_detect() {
    banner "IDE DETECT: all supported IDEs, stale duplicates flagged"

    for ide in .vscode .antigravity-ide .cursor .windsurf; do
        mkdir -p "${HOME}/${ide}/extensions/anthropic.claude-code-2.1.273"
        echo '{}' > "${HOME}/${ide}/extensions/anthropic.claude-code-2.1.273/package.json"
    done
    # A stale second version in VS Code, as on the author's machine.
    mkdir -p "${HOME}/.vscode/extensions/anthropic.claude-code-2.1.269"
    echo '{}' > "${HOME}/.vscode/extensions/anthropic.claude-code-2.1.269/package.json"

    local out
    out=$(PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0,'$WORK')
from cortex import ide
found = {i['label']: i for i in ide.detect()}
print('LABELS=' + ','.join(sorted(found)))
vs = found.get('VS Code')
print('STALE=' + str(bool(vs and vs['stale'])))
")
    for want in "VS Code" "Antigravity" "Cursor" "Windsurf"; do
        if [[ "$out" == *"$want"* ]]; then
            pass "detected $want"
        else
            fail "did not detect $want -> $out"
        fi
    done
    if [[ "$out" == *"STALE=True"* ]]; then
        pass "flagged the duplicate VS Code extension version"
    else
        fail "did not flag a duplicate extension version"
    fi
}

# --------------------------------------------------------------------------
# No command may hang without a network. Several tools reach out (arXiv, model
# catalogs, update checks), and a missing timeout turns a routine `cc status`
# into a stall on a train or a plane.
# --------------------------------------------------------------------------
scenario_offline() {
    banner "OFFLINE: nothing hangs without a network"

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/offline"
    local slow=0

    for c in version status doctor; do
        local start end
        start=$(date +%s)
        timeout 20 env PYTHONPATH="$WORK" python3 -m cortex "$c" >/dev/null 2>&1
        local rc=$?
        end=$(date +%s)
        if [ $rc -eq 124 ]; then
            fail "'cc $c' hung with no network"
            slow=1
        elif [ $(( end - start )) -gt 10 ]; then
            fail "'cc $c' took $(( end - start ))s with no network"
            slow=1
        fi
    done
    [ $slow -eq 0 ] && pass "core commands return promptly with no network"

    # Tools that reach the network must bound their wait.
    local hung=0
    for s in claude-research.py claude-models.py claude-update.py; do
        timeout 25 python3 "${WORK}/scripts/$s" --help >/dev/null 2>&1
        if [ $? -eq 124 ]; then
            fail "$s hung with no network"
            hung=1
        fi
    done
    [ $hung -eq 0 ] && pass "network-touching tools do not hang"

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# The `cc` shortcut must exist after every installer. Every document refers to
# `cc`, and neither Windows installer created it - so the documented command
# simply did not exist there.
# --------------------------------------------------------------------------
scenario_cc_alias() {
    banner "CC ALIAS: the documented shortcut exists after install"

    for f in install.sh install.py install.ps1; do
        if grep -qiE "cc\.cmd|cc\.ps1|install_cc_alias|BIN_DIR}/cc|bin_dir / \"cc\"" "${WORK}/$f" 2>/dev/null; then
            pass "$f creates a cc shortcut"
        else
            fail "$f does not create a cc shortcut -> documented command missing"
        fi
    done

    # install.sh, end to end.
    rm -f "${HOME}/.local/bin/cc"
    CORTEX_SANDBOX=1 bash "${WORK}/install.sh" --yes >/dev/null 2>&1
    local out
    out=$("${HOME}/.local/bin/cc" version 2>&1)
    if [[ "$out" == *"Claude Cortex"* ]]; then
        pass "cc works after install.sh"
    else
        fail "cc broken after install.sh -> $out"
    fi

    # install.py, end to end.
    rm -f "${HOME}/.local/bin/cc"
    CORTEX_SANDBOX=1 python3 "${WORK}/install.py" --yes >/dev/null 2>&1
    out=$("${HOME}/.local/bin/cc" version 2>&1)
    if [[ "$out" == *"Claude Cortex"* ]]; then
        pass "cc works after install.py"
    else
        fail "cc broken after install.py -> $out"
    fi
}

# --------------------------------------------------------------------------
# VS Code settings.json is JSONC: comments and trailing commas are normal there
# and strict json.load rejects them. Treating that failure as "empty file" and
# writing would replace the user's entire configuration - theme, keybindings,
# everything - with two Cortex keys. This is the highest-consequence bug in the
# IDE path, so it gets its own scenario.
# --------------------------------------------------------------------------
scenario_jsonc_safety() {
    banner "JSONC: a settings file with comments is never rewritten"

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/jsonc"
    CC profile add work >/dev/null 2>&1
    CC login work >/dev/null 2>&1

    local ext="${HOME}/.vscode/extensions/anthropic.claude-code-2.1.273"
    mkdir -p "$ext"; echo '{}' > "${ext}/package.json"
    local vsdir="${HOME}/.config/Code/User"
    mkdir -p "$vsdir"
    cat > "${vsdir}/settings.json" <<'JSONC'
{
  // Theme I actually use
  "workbench.colorTheme": "Solarized Dark",
  "editor.fontSize": 14,
  /* block comment */
  "files.autoSave": "onFocusChange",
}
JSONC
    local before after out
    before=$(md5sum "${vsdir}/settings.json" | cut -d' ' -f1)
    out=$(CC ide apply --yes 2>&1)
    after=$(md5sum "${vsdir}/settings.json" | cut -d' ' -f1)

    if [ "$before" = "$after" ]; then
        pass "a JSONC settings.json was left untouched"
    else
        fail "JSONC settings.json was rewritten - user settings destroyed"
    fi
    if grep -q "Solarized Dark" "${vsdir}/settings.json" 2>/dev/null; then
        pass "user settings survived"
    else
        fail "user settings were lost"
    fi
    if [[ "$out" == *"could not be parsed"* && "$out" == *"by hand"* ]]; then
        pass "explains why and prints the keys to add manually"
    else
        fail "unhelpful message for a JSONC file -> $(head -2 <<< "$out")"
    fi

    # The printed snippet must be valid JSON once wrapped in braces.
    local snippet
    snippet=$(sed -n '/claudeCode.environmentVariables/,/disableLoginPrompt/p' <<< "$out" | sed 's/^ *//')
    if python3 -c "
import json, sys
body = sys.stdin.read().strip()
json.loads('{' + body + '}')
" <<< "$snippet" 2>/dev/null; then
        pass "the printed snippet is valid JSON"
    else
        fail "the printed snippet is not valid JSON to paste"
    fi

    # 'ide check' must warn rather than claim it is simply unconfigured.
    out=$(CC ide check 2>&1)
    if [[ "$out" == *"not strict JSON"* ]]; then
        pass "'ide check' warns about the unparseable file"
    else
        fail "'ide check' did not warn about JSONC"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# API providers and the local gateway. Keys are secrets, so storage permissions
# matter, and the gateway binds a port - it must bind to loopback only.
# --------------------------------------------------------------------------
scenario_provider() {
    banner "PROVIDER: key storage, masking, and a loopback-only gateway"

    local out
    out=$(python3 "${WORK}/scripts/claude-provider.py" key openrouter "sk-or-v1-secret-value" 2>&1)
    if [[ "$out" == *"Configured"* ]]; then
        pass "provider key stored"
    else
        fail "could not store a provider key -> $out"
    fi

    local perms
    perms=$(stat -c %a "${HOME}/.claude/providers.json" 2>/dev/null)
    if [ "$perms" = "600" ]; then
        pass "providers.json is 0600 (owner-only)"
    else
        fail "providers.json permissions are $perms, expected 600"
    fi

    out=$(python3 "${WORK}/scripts/claude-provider.py" status 2>&1)
    if [[ "$out" == *"secret-value"* ]]; then
        fail "the full API key is printed in status output"
    else
        pass "status masks the API key"
    fi

    # It must not advertise profiles that do not exist.
    if [[ "$out" == *"VL / WS"* ]]; then
        fail "status shows hardcoded profile names"
    else
        pass "status does not show hardcoded profile names"
    fi

    # The gateway must listen on loopback only, never 0.0.0.0.
    if grep -q 'default="127.0.0.1"' "${WORK}/scripts/cortex-gateway.py" 2>/dev/null; then
        pass "gateway defaults to loopback"
    else
        fail "gateway does not default to loopback"
    fi

    # Poll rather than sleeping a fixed amount. A fixed wait makes the result
    # depend on how loaded the machine is, and a test that fails intermittently
    # teaches people to ignore failures.
    (timeout 25 python3 "${WORK}/scripts/cortex-gateway.py" --port 8099 >/dev/null 2>&1 &)
    out=$(python3 -c "
import time, urllib.request
deadline = time.time() + 15
last = 'never responded'
while time.time() < deadline:
    try:
        r = urllib.request.urlopen('http://127.0.0.1:8099/health', timeout=2)
        print('OK' if r.status == 200 else 'STATUS=%d' % r.status)
        break
    except Exception as exc:
        last = type(exc).__name__
        time.sleep(0.4)
else:
    print('ERR ' + last)
")
    if [[ "$out" == OK ]]; then
        pass "gateway starts and answers /health"
    else
        fail "gateway did not respond within 15s -> $out"
    fi
}

# --------------------------------------------------------------------------
# Robustness: concurrent use, hostile names, and scale. Profile names become
# directory names, so traversal sequences must not escape the profiles root.
# --------------------------------------------------------------------------
scenario_robustness() {
    banner "ROBUSTNESS: concurrency, hostile names, scale"

    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/robust"
    for n in a1 b2 c3 d4; do CC profile add "$n" >/dev/null 2>&1; done

    # Concurrent switches must leave a valid pointer, not a torn write.
    for n in a1 b2 c3 d4; do CC switch "$n" >/dev/null 2>&1 & done
    wait
    local val
    val=$(cat "${CORTEX_PROFILES_DIR}/current_profile" 2>/dev/null)
    if [ -n "$val" ] && [ -d "${CORTEX_PROFILES_DIR}/${val}" ]; then
        pass "concurrent switches leave a valid active profile ('$val')"
    else
        fail "concurrent switches corrupted the active profile: '$val'"
    fi

    # Path traversal must be neutralized, not merely rejected somewhere later.
    CC profile add "a/../../etc" </dev/null >/dev/null 2>&1
    if [ -d "/etc/.profile_mode" ] || [ -d "${CORTEX_PROFILES_DIR}/../../etc" ]; then
        fail "a traversal sequence escaped the profiles root"
    else
        pass "traversal in a profile name is neutralized"
    fi

    # And the user is told the name was changed.
    local out
    out=$(CC profile add "My Profile" </dev/null 2>&1)
    if [[ "$out" == *"adjusted from"* ]]; then
        pass "reports when a profile name is adjusted"
    else
        fail "silently renamed the profile -> $out"
    fi

    # A name with no usable characters must explain itself.
    out=$(CC profile add "日本語" </dev/null 2>&1)
    if [[ "$out" == *"no usable characters"* ]]; then
        pass "explains a name with no usable characters"
    else
        fail "unhelpful message for a non-ASCII name -> $out"
    fi

    # Scale: status must stay responsive with many profiles.
    export CORTEX_PROFILES_DIR="${SANDBOX_DIR}/many"
    for i in $(seq 1 25); do CC profile add "p$i" >/dev/null 2>&1; done
    local start elapsed
    start=$(date +%s)
    CC status >/dev/null 2>&1
    elapsed=$(( $(date +%s) - start ))
    if [ "$elapsed" -le 10 ]; then
        pass "status with 25 profiles completed in ${elapsed}s"
    else
        fail "status with 25 profiles took ${elapsed}s"
    fi

    unset CORTEX_PROFILES_DIR
}

# --------------------------------------------------------------------------
# An IDE's extensions directory name does not predict its settings directory
# name. Antigravity keeps extensions in ~/.antigravity-ide but settings under
# "Antigravity IDE/User" - and a separate "Antigravity/" directory also exists,
# so the obvious guess silently finds nothing or the wrong place.
# --------------------------------------------------------------------------
scenario_ide_settings_paths() {
    banner "IDE PATHS: settings resolved by probing, not by guessing"

    local cfg="${HOME}/.config"
    mkdir -p "${HOME}/.antigravity-ide/extensions/anthropic.claude-code-2.1.273"
    echo '{}' > "${HOME}/.antigravity-ide/extensions/anthropic.claude-code-2.1.273/package.json"

    # Decoy directory that must NOT be chosen, plus the real one.
    mkdir -p "${cfg}/Antigravity/User"
    mkdir -p "${cfg}/Antigravity IDE/User"
    echo '{"editor.fontSize": 13}' > "${cfg}/Antigravity IDE/User/settings.json"

    local out
    out=$(PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0,'$WORK')
from cortex import ide
for i in ide.detect():
    if i['label'] == 'Antigravity':
        print(i['settings_path'] or 'NONE')
")
    if [[ "$out" == *"Antigravity IDE/User/settings.json" ]]; then
        pass "chose the directory that actually holds settings.json"
    else
        fail "resolved the wrong Antigravity settings path -> $out"
    fi

    # With no settings.json anywhere, it should still offer a usable location
    # rather than giving up.
    rm -f "${cfg}/Antigravity IDE/User/settings.json"
    out=$(PYTHONPATH="$WORK" python3 -c "
import sys; sys.path.insert(0,'$WORK')
from cortex import ide
for i in ide.detect():
    if i['label'] == 'Antigravity':
        print(i['settings_path'] or 'NONE')
")
    if [[ "$out" != "NONE" && -n "$out" ]]; then
        pass "falls back to an existing User directory when no settings.json yet"
    else
        fail "gave up when settings.json did not exist yet"
    fi
}

# --------------------------------------------------------------------------
# Adversarial pass. The scenarios above were each written after fixing the bug
# they cover, so they pass by construction and cannot find anything new. This
# explores instead: generated argument vectors, random profile-operation
# sequences, and hostile on-disk states, checking invariants rather than
# expected output.
#
# Its first run found four real defects: an unknown command with trailing
# arguments still reached a session as a prompt, and three filesystem states
# produced raw tracebacks.
#
# Uses a fixed seed here for reproducibility; run fuzz.py directly with
# --seed to explore.
# --------------------------------------------------------------------------
scenario_fuzz() {
    banner "FUZZ: adversarial exploration"

    # Do not inherit whatever the previous scenario left behind.
    install -m 0755 "${WORK}/tests/sandbox/stub-claude.py" "${HOME}/.local/bin/claude.real"

    local out rc
    out=$(CORTEX_WORK="$WORK" CORTEX_STUB_LOG="$STUB_LOG" \
          CORTEX_SANDBOX_DIR="${SANDBOX_DIR}/fuzz" \
          python3 "${WORK}/tests/sandbox/fuzz.py" \
          --seed 20260916 --arg-rounds 30 --state-rounds 18 2>&1)
    rc=$?

    if [ $rc -eq 0 ]; then
        pass "$(grep -oE '[0-9]+ checks passed' <<< "$out" | head -1)"
    else
        fail "adversarial pass found defects:"
        grep "^  - " <<< "$out" | head -5 | sed 's/^/      /'
    fi
}

# --------------------------------------------------------------------------
# Environment and concurrency chaos: hostile HOME, preset CLAUDE_CONFIG_DIR,
# empty PATH, parallel invocations racing on shared state, and IDE settings
# files that are directories, dangling symlinks, or JSON arrays.
# --------------------------------------------------------------------------
scenario_chaos_env() {
    banner "CHAOS: hostile environment and concurrent use"

    install -m 0755 "${WORK}/tests/sandbox/stub-claude.py" "${HOME}/.local/bin/claude.real"

    local out rc
    out=$(CORTEX_WORK="$WORK" CORTEX_STUB_LOG="$STUB_LOG" \
          CORTEX_SANDBOX_DIR="${SANDBOX_DIR}/chaosenv" \
          python3 "${WORK}/tests/sandbox/chaos_env.py" 2>&1)
    rc=$?
    if [ $rc -eq 0 ]; then
        pass "$(grep -oE '[0-9]+ checks passed' <<< "$out" | head -1)"
    else
        fail "environment chaos found defects:"
        grep "^  - " <<< "$out" | head -5 | sed 's/^/      /'
    fi
}

# --------------------------------------------------------------------------
# Mutation testing. The point of this one is different from every scenario
# above: it measures whether the SUITE works, by reintroducing each fixed bug
# and checking that something notices.
#
# A suite reporting zero failures proves nothing on its own - it may simply be
# unable to fail. When this was first run, 4 of 10 mutations went undetected.
# --------------------------------------------------------------------------
scenario_mutation() {
    banner "MUTATION: do the tests actually detect regressions?"

    local out rc
    out=$(CORTEX_WORK="$WORK" CORTEX_STUB_LOG="$STUB_LOG" \
          python3 "${WORK}/tests/sandbox/mutate.py" 2>&1)
    rc=$?
    local summary
    summary=$(grep -oE '[0-9]+/[0-9]+ mutations caught' <<< "$out" | head -1)

    if [ $rc -eq 0 ]; then
        pass "${summary:-all mutations caught}"
    else
        fail "tests that do not protect anything: ${summary}"
        # Print the whole diagnostic. Truncating it previously hid the reason a
        # mutation was missed and turned debugging into guesswork.
        sed 's/^/      /' <<< "$out" | tail -40
    fi
}
