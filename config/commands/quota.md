---
name: quota
description: Display real-time usage limits, 5-hour and 7-day quota utilization, and reset countdowns across all configured accounts.
command: true
---

# Multi-Account Quota & Capacity Status

Display the real-time capacity and rate limit status across all accounts.

## Instructions for Claude

1. Execute the Capacity Check script via Bash:
   ```bash
   python3 ~/.claude/scripts/claude-capacity-check.py
   ```

2. Format the output clearly for the user, highlighting:
   - Active profile
   - Accounts with remaining capacity
   - Accounts currently rate-limited and their reset countdowns
   - Recommendation on which account to use if limits are approaching
