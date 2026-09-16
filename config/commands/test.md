---
name: test
description: Run the comprehensive Claude Cortex test suite and benchmark runner across all services and token metrics.
command: true
---

# Claude Cortex Comprehensive Test Runner

Run all unit, integration, token conservation, and latency benchmark tests across Cortex subsystems.

## Instructions for Claude

1. Execute the Cortex master test runner via Bash:
   ```bash
   python3 ~/.claude/tests/run_all_tests.py
   ```

2. Display the test results, latency SLA compliance, and token conservation metrics.
