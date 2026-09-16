#!/usr/bin/env bash
# ==============================================================================
# Claude Cortex - sandbox scenario runner (runs INSIDE the container)
#
# Prepares a disposable environment, runs one scenario, then verifies that
# nothing changed outside the paths the scenario declared it would touch.
#
# Usage (as container CMD):
#   entrypoint.sh <scenario> [scenario args...]
#   entrypoint.sh list
# ==============================================================================

set -uo pipefail

REPO_RO="/repo"          # read-only mount of the repository
WORK="${CORTEX_WORK_DIR:-/work}"   # writable copy the scenario operates on
SANDBOX_DIR="${HOME}/.cortex-sandbox"
STUB_LOG="${SANDBOX_DIR}/stub-invocations.jsonl"
SNAPSHOT="${SANDBOX_DIR}/home-snapshot.json"
LEAK_CHECK="${WORK}/tests/sandbox/leak_check.py"

# Scenario implementations live alongside this runner.
# shellcheck source=/dev/null
[ -f "/repo/tests/sandbox/scenarios.sh" ] && source "/repo/tests/sandbox/scenarios.sh"

SCENARIO="${1:-smoke}"
shift || true

banner() {
    echo "======================================================================"
    echo "  $*"
    echo "======================================================================"
}

fail() { echo "  FAIL: $*" >&2; FAILURES=$((FAILURES + 1)); }
pass() { echo "  ok: $*"; }
FAILURES=0

# --------------------------------------------------------------------------
# Prepare the writable copy and the stub binary
# --------------------------------------------------------------------------
prepare() {
    # Mutation testing modifies /work deliberately and then runs a scenario to
    # see whether it is noticed. Re-copying from /repo here would silently undo
    # the mutation and report a false pass, so allow the reset to be skipped.
    if [ "${CORTEX_NO_RESET:-0}" = "1" ] && [ -d "${WORK}/cortex" ]; then
        export CORTEX_STUB_LOG="${CORTEX_STUB_LOG:-$STUB_LOG}"
        mkdir -p "$SANDBOX_DIR" "${HOME}/.local/bin"
        [ -f "${HOME}/.local/bin/claude.real" ] ||             install -m 0755 "${WORK}/tests/sandbox/stub-claude.py" "${HOME}/.local/bin/claude.real"
        : > "$CORTEX_STUB_LOG"
        return 0
    fi

    # Empty /work rather than removing it: the directory is owned by this user
    # but its parent (/) is not, so unlinking the directory itself is denied.
    [ -d "$WORK" ] && find "$WORK" -mindepth 1 -delete 2>/dev/null
    rm -rf "$SANDBOX_DIR"
    mkdir -p "$WORK" "$SANDBOX_DIR" "${HOME}/.local/bin"
    # -a preserves the exec bits the installer and wrapper depend on.
    #
    # Local artifact directories are excluded rather than copied. A Ghidra run
    # writes ghidra-out/ as its own container uid, and a single unreadable file
    # made cp fail outright - which aborted EVERY scenario with a message that
    # pointed at the mount rather than at the stray directory. Test setup should
    # not be breakable by an unrelated tool's leftovers.
    if ! tar -C "${REPO_RO}"             --exclude=./.git             --exclude=./ghidra-out             --exclude=./.ghidra-test             --exclude=./__pycache__             -cf - . 2>/dev/null | tar -C "${WORK}" -xf - 2>/dev/null; then
        echo "FATAL: could not copy repository from ${REPO_RO}" >&2
        exit 1
    fi

    # Defensive CRLF strip. The repository enforces LF via .gitattributes, but a
    # Windows editor can reintroduce CRLF in the working tree, and a bash script
    # with CRLF endings fails on Linux with "$'\r': command not found" - an error
    # that looks nothing like its cause. Normalizing here keeps a sandbox run from
    # failing for a reason that has nothing to do with the code under test.
    find "$WORK" -type f \( -name '*.sh' -o -name '*.py' -o -name 'claude' \) \
        -exec sed -i 's/\r$//' {} + 2>/dev/null

    # Install the stub as the "real" Claude binary the wrapper will exec.
    install -m 0755 "${WORK}/tests/sandbox/stub-claude.py" "${HOME}/.local/bin/claude.real"
    export CORTEX_STUB_LOG="$STUB_LOG"
    : > "$STUB_LOG"
}

snapshot_home() {
    python3 "$LEAK_CHECK" snapshot "$HOME" "$SNAPSHOT" --quiet
}

# Verify nothing changed outside the allowlist. Extra allowlist globs may be
# passed as arguments by a scenario that legitimately installs files.
verify_no_leak() {
    local allow_args=()
    for glob in "$@"; do
        allow_args+=(--allow "$glob")
    done
    # Always-permitted: the sandbox's own bookkeeping.
    allow_args+=(--allow '.cortex-sandbox/**' --allow '.local/bin/claude.real')
    python3 "$LEAK_CHECK" compare "$HOME" "$SNAPSHOT" "${allow_args[@]}"
}

stub_calls() {
    [ -s "$STUB_LOG" ] && cat "$STUB_LOG" || echo ""
}

# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

# Harness self-test: proves the stub, the leak check, and the copy all work
# before any scenario relies on them.
scenario_smoke() {
    banner "SMOKE: harness self-test"

    local ver
    ver="$("${HOME}/.local/bin/claude.real" --version 2>&1)"
    if [[ "$ver" == *"Claude Code"* ]]; then pass "stub reports: $ver"; else fail "stub --version: $ver"; fi

    # auth status must exit 0 while logged OUT and report loggedIn:false.
    export CLAUDE_CONFIG_DIR="${SANDBOX_DIR}/profile-smoke"
    local out rc
    out="$("${HOME}/.local/bin/claude.real" auth status 2>&1)"; rc=$?
    if [ $rc -eq 0 ]; then pass "auth status exits 0 when logged out"; else fail "auth status exit $rc"; fi
    if [[ "$out" == *'"loggedIn": false'* ]]; then pass "reports loggedIn:false"; else fail "auth status body: $out"; fi

    # After login it must flip, and seed onboarding state.
    "${HOME}/.local/bin/claude.real" auth login >/dev/null 2>&1
    out="$("${HOME}/.local/bin/claude.real" auth status 2>&1)"
    if [[ "$out" == *'"loggedIn": true'* ]]; then pass "reports loggedIn:true after login"; else fail "post-login: $out"; fi
    if grep -q hasCompletedOnboarding "${CLAUDE_CONFIG_DIR}/.claude.json" 2>/dev/null; then
        pass "login seeds hasCompletedOnboarding"
    else
        fail "login did not seed onboarding state"
    fi

    # The autocompact validation that guards the compaction regression.
    if "${HOME}/.local/bin/claude.real" --autocompact 85000 >/dev/null 2>&1; then
        fail "stub accepted invalid --autocompact 85000"
    else
        pass "stub rejects --autocompact 85000 (matches real CLI)"
    fi
    if "${HOME}/.local/bin/claude.real" --autocompact auto >/dev/null 2>&1; then
        pass "stub accepts --autocompact auto"
    else
        fail "stub rejected valid --autocompact auto"
    fi

    # Invocations must be recorded for later assertions.
    local n; n="$(wc -l < "$STUB_LOG")"
    if [ "$n" -ge 5 ]; then pass "recorded $n stub invocations"; else fail "only $n invocations logged"; fi

    unset CLAUDE_CONFIG_DIR
}

# The installer must change nothing at all in --dry-run.
scenario_install_dryrun() {
    banner "INSTALL DRY-RUN: must not modify the filesystem"
    snapshot_home
    bash "${WORK}/install.sh" --dry-run
    if verify_no_leak; then pass "dry-run changed nothing"; else fail "dry-run modified the filesystem"; fi
}

# The installer must refuse to run non-interactively without opt-in, even
# though CORTEX_SANDBOX is set here - so we unset it for this check.
scenario_install_guard() {
    banner "INSTALL GUARD: refuses without opt-in"
    snapshot_home
    local rc
    env -u CORTEX_SANDBOX bash "${WORK}/install.sh" </dev/null >/dev/null 2>&1
    rc=$?
    if [ $rc -eq 3 ]; then pass "refused with guard exit code 3"; else fail "expected exit 3, got $rc"; fi
    if verify_no_leak; then pass "guard refusal changed nothing"; else fail "guard refusal modified the filesystem"; fi
}

scenario_list() {
    echo "Available scenarios:"
    echo "  smoke              harness self-test (stub + leak check)"
    echo "  install-dryrun     installer --dry-run must change nothing"
    echo "  install-guard      installer must refuse without explicit opt-in"
    echo "  compaction         no invalid autocompact settings reach the CLI"
    echo "  auth               profile stays signed in across launches"
    echo "  prompt-hook        ordinary prompts must reach the model"
    echo "  capacity           unknown capacity is never treated as free"
    echo "  capacity-agree     script and core give the same capacity answer"
    echo "  edge-cases         no silent profile creation or stray logins"
    echo "  paths-modes        spaces in paths, synced vs isolated profiles"
    echo "  ide-detect         all supported IDEs found, duplicates flagged"
    echo "  offline            nothing hangs without a network"
    echo "  cc-alias           the documented cc shortcut exists after install"
    echo "  jsonc              a settings file with comments is never rewritten"
    echo "  provider           key storage, masking, loopback-only gateway"
    echo "  robustness         concurrency, hostile names, scale"
    echo "  ide-paths          settings resolved by probing, not guessing"
    echo "  fuzz               adversarial exploration (args, state, filesystem chaos)"
    echo "  chaos-env          hostile environment, concurrency, IDE settings chaos"
    echo "  mutation           do the tests actually detect regressions?"
    echo "  precedence         a checkout beats the installed copy"
    echo "  analyze            risk findings depend on the code (not a template)"
    echo "  mcp                tools exposed, subscription untouched by registration"
    echo "  instinct           learned-patterns store works standalone"
    echo "  integrity          install matches source; tampering detected"
    echo "  model              live catalog, graceful offline"
    echo "  dream-doc          explorations are persisted, indexed, recallable"
    echo "  ide-wrapper        extension calling convention is honoured"
    echo "  install-uninstall  official Claude Code survives an uninstall"
    echo "  rules-budget       always-on prompt payload stays small"
    echo "  installers         every installer deploys the Python core"
    echo "  args               flag translation and prompt safety"
    echo "  exec-loop          never exec the Cortex wrapper as the real binary"
    echo "  doctor             detects and repairs known failure modes"
    echo "  e2e                full user journey end to end"
    echo "  degraded           clear errors in broken environments"
    echo "  prompt-leak        commands never leak into a session as prompts"
    echo "  powershell         Windows shim reaches the same core (needs pwsh)"
    echo "  idempotent         installing twice is safe"
    echo "  hooks              hooks survive malformed and hostile input"
    echo "  ide-apply          IDE settings writes are additive and atomic"
    echo "  install-py         the Python installer produces a working install"
}

# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------
if [ "$SCENARIO" = "list" ]; then
    scenario_list
    exit 0
fi

prepare

case "$SCENARIO" in
    smoke)          scenario_smoke ;;
    install-dryrun) scenario_install_dryrun ;;
    install-guard)  scenario_install_guard ;;
    compaction)        scenario_compaction ;;
    auth)              scenario_auth ;;
    prompt-hook)       scenario_prompt_hook ;;
    capacity)          scenario_capacity ;;
    ide-wrapper)       scenario_ide_wrapper ;;
    install-uninstall) scenario_install_uninstall ;;
    rules-budget)      scenario_rules_budget ;;
    installers)        scenario_installers_complete ;;
    args)              scenario_args ;;
    exec-loop)         scenario_no_exec_loop ;;
    doctor)            scenario_doctor ;;
    e2e)               scenario_e2e ;;
    degraded)          scenario_degraded ;;
    prompt-leak)       scenario_no_prompt_leak ;;
    powershell)        scenario_powershell ;;
    idempotent)        scenario_idempotent ;;
    hooks)             scenario_hook_robustness ;;
    ide-apply)         scenario_ide_apply ;;
    install-py)        scenario_install_py ;;
    capacity-agree)    scenario_capacity_agreement ;;
    edge-cases)        scenario_edge_cases ;;
    paths-modes)       scenario_paths_and_modes ;;
    ide-detect)        scenario_ide_detect ;;
    offline)           scenario_offline ;;
    cc-alias)          scenario_cc_alias ;;
    jsonc)             scenario_jsonc_safety ;;
    provider)          scenario_provider ;;
    robustness)        scenario_robustness ;;
    ide-paths)         scenario_ide_settings_paths ;;
    fuzz)              scenario_fuzz ;;
    chaos-env)         scenario_chaos_env ;;
    mutation)          scenario_mutation ;;
    precedence)        scenario_script_precedence ;;
    analyze)           scenario_analyze ;;
    mcp)               scenario_mcp ;;
    instinct)          scenario_instinct ;;
    integrity)         scenario_integrity ;;
    model)             scenario_model ;;
    dream-doc)         scenario_dream_doc ;;
    all)
        scenario_smoke
        scenario_install_dryrun
        scenario_install_guard
        scenario_compaction
        scenario_auth
        scenario_prompt_hook
        scenario_capacity
        scenario_capacity_agreement
        scenario_edge_cases
        scenario_paths_and_modes
        scenario_ide_detect
        scenario_ide_settings_paths
        scenario_offline
        scenario_ide_wrapper
        scenario_rules_budget
        scenario_args
        scenario_no_exec_loop
        scenario_doctor
        scenario_installers_complete
        scenario_e2e
        scenario_degraded
        scenario_no_prompt_leak
        scenario_powershell
        scenario_hook_robustness
        scenario_idempotent
        scenario_ide_apply
        scenario_jsonc_safety
        scenario_provider
        scenario_robustness
        scenario_install_py
        scenario_cc_alias
        scenario_install_uninstall
        scenario_fuzz
        scenario_chaos_env
        scenario_mutation
        scenario_script_precedence
        scenario_analyze
        scenario_mcp
        scenario_instinct
        scenario_integrity
        scenario_model
        scenario_dream_doc
        ;;
    *)
        echo "Unknown scenario: ${SCENARIO}" >&2
        scenario_list
        exit 2
        ;;
esac

echo ""
banner "RESULT: ${FAILURES} failure(s)"
exit $(( FAILURES > 0 ? 1 : 0 ))
