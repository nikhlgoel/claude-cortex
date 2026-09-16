#!/usr/bin/env bash
# ==============================================================================
# Claude Cortex - IDE process wrapper
#
# For use as `claudeCode.claudeProcessWrapper`. The extension invokes a wrapper as
#
#     wrapper <path-to-bundled-claude> [session args...]
#
# passing its own bundled binary as the FIRST ARGUMENT (extension.js:
# `executableArgs: X ? [X] : []`). So the wrapper must shift that path off and
# exec it - which is exactly what the old Cortex wrapper failed to do: it treated
# $1 as a subcommand name, so wiring it up broke the extension instead of
# enhancing it.
#
# NOTE: prefer `claudeCode.environmentVariables` for profile selection. Setting a
# process wrapper also disables the extension's permission-mode resolution and its
# CLAUDE_CONFIG_DIR watching. Use this only when you need to intercept the launch.
# ==============================================================================

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "cortex-ide-wrapper: expected the Claude binary path as the first argument" >&2
    echo "This script is meant to be used as claudeCode.claudeProcessWrapper." >&2
    exit 2
fi

REAL_CLAUDE="$1"
shift

if [ ! -x "$REAL_CLAUDE" ]; then
    echo "cortex-ide-wrapper: not executable: ${REAL_CLAUDE}" >&2
    exit 1
fi

# Apply the Cortex profile environment if a profile is configured. The config dir
# must be byte-identical to the terminal's, or the IDE session lands in a
# different credential namespace and appears signed out.
if [ -n "${CORTEX_PROFILE_DIR:-}" ]; then
    export CLAUDE_CONFIG_DIR="${CORTEX_PROFILE_DIR}"
    export CLAUDE_SECURESTORAGE_CONFIG_DIR="${CORTEX_PROFILE_DIR}"
fi

# Never let a stale compaction override reach an IDE session.
unset CLAUDE_AUTOCOMPACT_PCT_OVERRIDE CLAUDE_CODE_AUTO_COMPACT_WINDOW 2>/dev/null || true

exec "$REAL_CLAUDE" "$@"
