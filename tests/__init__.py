# Claude Cortex Comprehensive Test & Benchmark Suite
#
# These tests read and write real paths under ~/.claude. The guard below aborts
# the run unless we are in a sandbox, so importing any test module directly
# (e.g. `python -m unittest tests.test_provider_security`) is protected too.

from ._guard import require_sandbox  # noqa: F401

require_sandbox()
