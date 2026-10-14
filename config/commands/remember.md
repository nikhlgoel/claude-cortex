---
name: remember
description: Deposit a key lesson, architectural decision, or bug fix into the project's Memory Palace.
command: true
---

# Store Memory in the Palace

Store a memory in the project's layered palace. Choose a kind (the old rooms still work as `--room`):
- `blueprint`: System architecture, schemas, boundaries, APIs
- `procedures`: Workflows, build recipes, test commands
- `graveyard`: Bugs solved, tricky pitfalls, things never to repeat
- `decisions`: Architecture Decision Records (ADRs), trade-offs
- `working`: Current focus, immediate next tasks

## Instructions for Claude

1. Extract the room name, title, content, and relevant tags from the user's prompt.
2. If room is omitted, default intelligently:
   - Bug/pitfall -> `graveyard`
   - Workflow/script -> `procedures`
   - Design/architecture -> `blueprint`
   - Choice/trade-off -> `decisions`
3. Execute the memory deposit via Bash:
   ```bash
   cc palace remember --title "<title>" --content "<content>" --kind <kind> [--file <path>] [--supersedes <id>]
   ```
4. Confirm to the user which room received the memory and why it will make future coding smarter.
