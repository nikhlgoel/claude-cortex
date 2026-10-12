---
name: cc
description: Display Claude Cortex command index, shortcuts, and active configuration.
command: true
---

# Claude Cortex (cc) Command Index

Display available in-session and terminal commands, active profiles, and shortcuts.

## Instructions for Claude

1. If subcommands were passed with arguments (e.g. `model`, `capacity`, `palace`), invoke the corresponding command.
2. If no arguments were provided, display the Claude Cortex command index:
   ```text
   ======================================================================
                    Claude Cortex (cc) - Command Suite
   ======================================================================
   In-Session Commands (0 API tokens consumed):
     /capacity                   Real-time quota & rate-limit check
     /model [list|free|set]      Model explorer & selector
     /provider [status|set]      Manage external API providers
     /effort [low..max]          Adjust reasoning effort level
     /turbo [on|off]             High-speed token saver mode
     /palace [status|rooms]      Cognitive Memory Palace
     /remember <room> <note>     Deposit knowledge into palace room
     /recall <query>             Instant tag & keyword search
     /dream <concept>            Research-backed concept explorer
     /research <topic>           Frontier arXiv & SOTA testbench
     /update [check|apply]       Ecosystem updater
     /switch [profile]           Toggle active account
     /continue                   Auto-failover resume
     /clean                      Storage & cache cleanup
   ======================================================================
   ```
