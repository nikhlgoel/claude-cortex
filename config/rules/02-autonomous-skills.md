---
name: autonomous-skills
description: Automatically detects and utilizes Spec Kit, Scrapling, and ECC skills without requiring explicit prompting.
---

# Autonomous Skills Integration Rule

1. **Spec Kit (Spec-Driven Development)**:
   - When asked to build a new feature, module, or major refactor, check if the project uses Spec Kit (`.specify/`).
   - If not yet initialized, you can scaffold with `specify init --here --force --non-interactive --integration claude` when appropriate.
   - Use `/speckit-specify` for clear user requirements, `/speckit-plan` for technical decisions, and `/speckit-tasks` before jumping into raw code.
   - Keep tasks granular, test-driven, and validated.

2. **Scrapling (Adaptive Web Scraping & Research)**:
   - When the user asks to scrape, extract, or fetch content from web pages, use the native `scrapling` MCP tools or the `scrapling` CLI (`scrapling get ...`).
   - Leverage Scrapling's stealth headers, auto-parsing, and markdown conversion to extract only the relevant data, reducing context token waste.

3. **Everything Claude Code (ECC) Quality Loops**:
   - Apply TDD (Test-Driven Development) whenever tests exist in the project.
   - Always run project test suites (e.g. `npm test`, `pytest`, `cargo test`, `go test`) to confirm fixes before reporting completion.
