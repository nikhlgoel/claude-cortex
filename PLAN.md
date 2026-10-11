# Execution Plan
1. **Foundation**: Scaffold project management files (Done).
2. **Cleanup**: Resolve structural flaws, unmanaged resources, and shell vulnerabilities.
3. **Enhancement**: Inject Graphify and auto-skills indexer.
4. **UX Polish**: Add timeouts, flushes, and interactive confirmations.

## Phase 4: The Skills Paradigm Shift
1. **Executable Skills**: Bind MCP tools directly to skills via tools.py.
2. **Graphify Synergy**: Refactor memory-palace to inject nodes directly into the AST graph instead of flat markdown files.
3. **Smart Context**: Add tech-stack conditional filtering to prevent algorithms loading in non-C++ environments.
4. **Interactive Injection**: Enable skills to prompt the user (y/n) on launch for key architectural decisions.

## Phase 5: Concurrency & IPC Safety
- Implement portalocker or native file locks on all open(..., w) calls for shared configurations.

## Phase 6: Strict Isolation & Anti-Hallucination
- Replace all hardcoded ~/.claude strings with dynamic CLAUDE_CONFIG_DIR resolving logic.
- Expose Graphify strictly via a new MCP tool query_knowledge_graph to guarantee Claude receives deterministic JSON instead of hallucinating shell output.

## Phase 7: Deep Resilience & Anti-Hallucination
- **Network**: Implement the urllib.error.HTTPError exponential backoff (e.g. 3 retries) on 429 and 5xx errors for all proxy services.
- **Memory**: Add a 5MB threshold skip to all `.read()` loops in claude-analyze.py.
- **AST Guard**: Graphify subprocesses will execute with strict --timeout boundaries per file.

## Phase 8: Multi-Platform Stability
- Implement Windows Job Objects or strict subprocess process-group termination (e.g. CREATE_NEW_PROCESS_GROUP) for the launcher to guarantee child shutdown on SIGINT.
- Add a schema migrator to profiles.py that auto-upgrades settings.json (e.g., adding missing keys instead of raising KeyErrors).

## Phase 9: Model Expansion & Objective Impact Scoring
- **Model Updates**: Inject claude-opus-5-5 and claude-fable (and its variants) into MODEL_ALIASES in launcher.py and SUBSCRIPTION_MODELS in models.py.
- **Objective Action Scorer (OAS)**: Implement a calculated score parameter (0-100) that evaluates every agent change based on neutral metrics (AST complexity diff, test presence, reversibility). The agent will no longer output 'I am confident', but rather an objective mathematical score of the change.

## Phase 10: The Neutral Evaluator & Next-Gen Models
- Build scripts/cortex-scorer.py and bind it to MCP as evaluate_impact.
- Overhaul 00-core.md to legally ban subjective confidence phrases.
- Refactor cortex/launcher.py to route --opus-5-5 and --fable gracefully.
