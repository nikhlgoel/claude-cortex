---
name: capacity
description: Display real-time subscription limits, 5-hour and 7-day quota utilization, and countdowns across all configured accounts.
command: true
---

# Multi-Account Capacity & Quota Status

Display real-time capacity, session limits, and rate-limit reset countdowns across all accounts.

## Instructions for Claude

1. Execute the Capacity Check script via Bash:
   ```bash
   python3 ~/.claude/scripts/claude-capacity-check.py
   ```

2. Format the output clearly for the user, highlighting:
   - Active profile
   - Accounts with remaining capacity
   - Accounts currently rate-limited and their reset countdowns
   - Auto-failover recommendation if capacity is low
