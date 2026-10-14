"""
The palace evaluation corpus: real facts from this project's own history, and questions about them.

How to read the cases (see ``cortex/palace/evalharness.py``):

* ``relevant`` - the question is a *paraphrase* (it avoids the memory's own wording on purpose, so
  synonym handling is tested); success is any of ``expect`` appearing in the injected result.
* ``update``   - a fact changed; the newest must appear and the superseded one (``forbid``) must not.
* ``quiet``    - nothing should be injected. This is the case that matters most for an
  auto-injecting memory: noise on prompts it has no business answering.
* ``heldout``  - cases the engine's thresholds were NOT tuned on.

Honest limit: the memories and the questions were written by the same hand, so scores here are
optimistic. They measure *relative* quality (new engine vs old) and guard against regressions;
the true test is a person's own memory over time.
"""

MEMORIES = [
    dict(key="cfg_default", kind="fact", age_days=20, paths=["cortex/paths.py"],
         title="Default account folder: leave CLAUDE_CONFIG_DIR unset",
         body="With CLAUDE_CONFIG_DIR unset Claude Code keeps the account, MCP servers and usage cache in "
              "~/.claude.json. With it set, even to ~/.claude, it reads ~/.claude/.claude.json instead, a different "
              "file. So the launcher leaves the variable unset for the default folder."),
    dict(key="cred_ns", kind="fact", age_days=60,
         title="Credential namespace is a hash of the exact config-dir string",
         body="Claude Code namespaces stored logins by a hash of the config directory string. C:\\x, /c/x and C:/x "
              "are three different accounts, so every path goes through one canonicalizer."),
    dict(key="adopt", kind="decision", age_days=15,
         title="Adopted profiles are never modified",
         body="Existing Claude folders are registered with their path verbatim and never moved, copied or edited. "
              "Removing an adopted profile only unregisters it, and doctor repair skips it."),
    dict(key="guard_keys", kind="fact", age_days=14, paths=["cortex/guard.py"],
         title="Guard compares stable keys of .claude.json",
         body="Claude Code rewrites ~/.claude.json constantly, so the guard hashes only oauthAccount, mcpServers, "
              "hasCompletedOnboarding, userID and customApiKeyResponses instead of the whole file."),
    dict(key="mcp_cli", kind="decision", age_days=14,
         title="Register MCP servers through claude mcp add",
         body="Never edit .claude.json directly: Claude Code rewrites it and a direct edit can lose a race. "
              "Use claude mcp add --scope user."),
    dict(key="routing", kind="decision", age_days=13,
         title="Tool routing hints must be precise",
         body="The first routing version had 48 percent false positives. Intent phrases plus vetoes, at most one hint, "
              "measured at zero of 91 quiet prompts."),
    dict(key="win_reset", kind="failure", age_days=12, paths=["scripts/cortex-gateway.py"],
         title="Windows resets connections closed with unread bytes",
         body="The gateway closed connections without reading the request body, so on Windows the client saw a "
              "connection reset. Drain up to 256 KiB with _discard_body before closing."),
    dict(key="slots", kind="fact", age_days=18,
         title="llama.cpp splits the context across parallel slots",
         body="The -c context size is divided between the slots set by -np. A 16k context with -np 4 gives 4k per "
              "slot. Use -np 1 for a single Claude Code session."),
    dict(key="escapes", kind="failure", age_days=10,
         title="Patch scripts: backslash escapes get collapsed",
         body="In heredoc patch scripts the tool layer turns backslash-n into a real newline and backslash-b into a "
              "backspace character. Use the Edit tool, placeholders, or chr(92)."),
    dict(key="gateguard", kind="fact", age_days=9,
         title="GateGuard hook demands facts before the first write",
         body="The first creation of a file is denied once. State the callers, the data schema and the user's "
              "instruction verbatim, then retry the identical call."),
    dict(key="consent", kind="rule", age_days=16,
         title="Never download or install anything for the user",
         body="Downloads need the user's consent. The consent gate refuses agents even with --yes."),
    dict(key="commits", kind="preference", age_days=3,
         title="Commit as nikhlgoel, few meaningful commits, ask first",
         body="Use the nikhlgoel GitHub account for this project and the user's personal projects. Make proper "
              "commits after a milestone, not ten a day, and ask before committing."),
    dict(key="sandbox", kind="recipe", age_days=17,
         title="Run the test suite sandboxed",
         body="Set CORTEX_SANDBOX=1 plus a temporary HOME and USERPROFILE, then run python tests/run_all_tests.py. "
              "The repository refuses to run tests against the real home directory."),
    dict(key="release", kind="recipe", age_days=1,
         title="Build and publish a release",
         body="Run python scripts/build-releases.py to build eight packages and SHA256SUMS, verify each by "
              "extracting and installing it in a sandbox, then gh release create."),
    dict(key="thin_installers", kind="decision", age_days=1, paths=["install.py"],
         title="Shell installers are thin launchers around install.py",
         body="install.sh, install.ps1 and install.cmd only find Python and run install.py. The PowerShell one used "
              "to overwrite hooks and permissions in settings.json."),
    dict(key="no_download", kind="decision", age_days=1,
         title="The installer never downloads executables",
         body="It used to fetch claude.real from a hard-coded URL with no checksum. That was removed; it now tells "
              "the user how to install Claude Code."),
    dict(key="cmd_pause", kind="failure", age_days=1,
         title="install.cmd hung on pause",
         body="An unconditional pause hung automation for thirty seconds. It now pauses only on a double-click, "
              "detected through CMDCMDLINE."),
    dict(key="stemmer", kind="fix", age_days=0,
         title="The stemmer must reach a fixpoint",
         body="settings and setting stemmed differently so a query missed the memory. Apply the stemmer until the "
              "word stops changing."),
    dict(key="ide_env", kind="fact", age_days=14, paths=["cortex/ide.py"],
         title="IDE settings: merge environmentVariables, never replace",
         body="cc ide apply must change only Cortex's own entries in claudeCode.environmentVariables and keep the "
              "person's other variables."),
    dict(key="desktop", kind="structure", age_days=15,
         title="Desktop profiles are Electron user-data-dir folders",
         body="Each Claude Desktop profile is a separate Electron --user-data-dir. A surface is only a way of "
              "launching a profile: terminal, ide or desktop."),
    dict(key="local", kind="structure", age_days=18,
         title="Local models run on llama-server behind the Cortex gateway",
         body="Hugging Face GGUF files run on llama.cpp. The Cortex gateway in local mode shapes requests and the "
              "model sleeps when idle."),
    dict(key="idle_old", kind="fact", age_days=30,
         title="Gateway idle timeout",
         body="The gateway idle timeout is 30 minutes before the process exits."),
    dict(key="idle_new", kind="fact", age_days=2, supersedes="idle_old",
         title="Gateway idle timeout",
         body="The gateway no longer exits when idle; it puts the model to sleep after 30 minutes and wakes it on "
              "the next request."),
    dict(key="hub", kind="fix", age_days=11,
         title="Download edge cases in the model hub",
         body="A 416 range reply and an already complete partial file were dead ends. Now the file is re-verified and "
              "retried once from the start, and finished shards are not fetched again."),
    dict(key="flaky_auth", kind="failure", age_days=11,
         title="Flaky gateway auth test",
         body="Root cause was the unread request body causing a reset. The test now sends a 200 KB body."),
    dict(key="py38", kind="decision", age_days=40,
         title="The core must run on Python 3.8",
         body="No match statements and no X | Y types evaluated at runtime, because the core supports Python 3.8."),
    dict(key="lf", kind="rule", age_days=10,
         title="Python sources use LF line endings",
         body="Two CRLF files broke patching in an LF project. TestRepoHygiene checks every python file."),
    dict(key="sh_lf", kind="rule", age_days=45,
         title="Shell scripts must keep LF endings",
         body="A bash script with CRLF endings fails on Linux with command not found. .gitattributes enforces eol=lf "
              "for sh files."),
    dict(key="version", kind="fact", age_days=1,
         title="One version string in three files",
         body="The version lives in cortex/__init__.py, cortex/__main__.py and scripts/cortex-mcp.py. The changelog "
              "must have an entry for it and a test enforces all of that."),
    dict(key="mods", kind="fact", age_days=0,
         title="Claude Code mods need version 2.1.287 or later",
         body="Mods are JavaScript or TypeScript hooks that can draw panes and a band above the prompt. They need CLI "
              "2.1.287 or Desktop 2.1.286, and they are not sandboxed."),
    dict(key="effort", kind="fact", age_days=30,
         title="Reasoning effort levels",
         body="Effort goes low, medium, high, xhigh and max. ultracode is a mode on top that enables workflows."),
    dict(key="scorer", kind="fact", age_days=35, paths=["scripts/cortex-scorer.py"],
         title="evaluate_impact is a heuristic risk score",
         body="cortex-scorer.py scores one file from complexity change, test references, recovery and dependents. "
              "Unmeasurable inputs are listed rather than invented."),
    dict(key="gh_accounts", kind="fact", age_days=1,
         title="Three GitHub accounts are logged in",
         body="gh has nikhlgoel, VeilLabsIN and saiusainc. The global git identity is VeilLabsIN, so a repository "
              "needs its own identity."),
    dict(key="why_sqlite", kind="decision", age_days=0,
         title="Palace v3 uses SQLite with its own BM25 index",
         body="Several sessions write at once, which a rewritten JSON file loses. SQLite in WAL mode serialises "
              "writers. FTS5 is not always compiled in, so keyword search is our own."),
    dict(key="graph_split", kind="decision", age_days=0,
         title="Graphify knows the code, the palace knows the why",
         body="The palace never copies code structure. Memories are anchored to files and symbols and flagged when "
              "Graphify's file hash changes."),
    dict(key="abstain", kind="decision", age_days=0,
         title="Memory injection abstains when evidence is thin",
         body="Noise on prompts the palace has no business answering is the worst failure, so retrieval returns "
              "nothing unless enough query terms are covered."),
    dict(key="names", kind="fact", age_days=13,
         title="Profile names are lowercased and adjusted",
         body="Names become lowercase letters, digits, dash and underscore. When the name changes the command says "
              "so instead of silently using another one."),
    dict(key="registry", kind="fix", age_days=13,
         title="A damaged registry raises an error instead of resetting",
         body="An unreadable registry.json raises CortexError. Silently starting empty would forget every adopted "
              "profile."),
]

CASES = [
    # ---- relevant: paraphrased, avoiding the memory's own words --------------------------------
    dict(id="r01", type="relevant", expect=["cfg_default"], query="why does my default account lose its MCP servers"),
    dict(id="r02", type="relevant", expect=["cfg_default"], query="which file stores the connected tools for the main claude folder", heldout=True),
    dict(id="r03", type="relevant", expect=["cred_ns"], query="are three spellings of one path the same login"),
    dict(id="r04", type="relevant", expect=["cred_ns"], query="how are stored credentials keyed by directory"),
    dict(id="r05", type="relevant", expect=["adopt"], query="can adopting an account change my existing folders", heldout=True),
    dict(id="r06", type="relevant", expect=["adopt"], query="what happens when I remove an adopted profile"),
    dict(id="r07", type="relevant", expect=["guard_keys"], query="how does the guard notice changes to the claude json file"),
    dict(id="r08", type="relevant", expect=["mcp_cli"], query="what is the right way to add an MCP server"),
    dict(id="r09", type="relevant", expect=["mcp_cli"], query="why not edit claude.json by hand", heldout=True),
    dict(id="r10", type="relevant", expect=["routing"], query="the tool hints fire too often, false positives"),
    dict(id="r11", type="relevant", expect=["win_reset"], query="connection reset on windows from the gateway"),
    dict(id="r12", type="relevant", expect=["win_reset", "flaky_auth"], query="client sees a reset when the server drops the socket early", heldout=True),
    dict(id="r13", type="relevant", expect=["slots"], query="how much context does each parallel slot get in llama server"),
    dict(id="r14", type="relevant", expect=["slots"], query="np parallel setting and context size"),
    dict(id="r15", type="relevant", expect=["escapes"], query="my newline escape got broken in a patch script", heldout=True),
    dict(id="r16", type="relevant", expect=["gateguard"], query="the gate guard denied creating a new file"),
    dict(id="r17", type="relevant", expect=["consent"], query="am I allowed to download a model for the user"),
    dict(id="r18", type="relevant", expect=["commits", "gh_accounts"], query="which account should author the commits"),
    dict(id="r19", type="relevant", expect=["sandbox"], query="how do I run the tests safely", heldout=True),
    dict(id="r20", type="relevant", expect=["release"], query="steps to build and publish a release"),
    dict(id="r21", type="relevant", expect=["thin_installers"], query="why is install.ps1 just a launcher"),
    dict(id="r22", type="relevant", expect=["no_download"], query="does the installer fetch the claude binary from the internet"),
    dict(id="r23", type="relevant", expect=["cmd_pause"], query="install.cmd hangs at the end of an automated run", heldout=True),
    dict(id="r24", type="relevant", expect=["stemmer"], query="search misses the plural form of a word"),
    dict(id="r25", type="relevant", expect=["ide_env"], query="ide apply overwrote my environment variables"),
    dict(id="r26", type="relevant", expect=["idle_new"], query="gateway shuts down when nobody is using it"),
    dict(id="r27", type="relevant", expect=["hub"], query="resuming a download fails with a 416 range error", heldout=True),
    dict(id="r28", type="relevant", expect=["py38"], query="which python versions must the core support"),
    dict(id="r29", type="relevant", expect=["lf", "sh_lf"], query="crlf line endings are breaking things"),
    dict(id="r30", type="relevant", expect=["version"], query="where do I bump the version number"),
    dict(id="r31", type="relevant", expect=["mods"], query="what version do mods require", heldout=True),
    dict(id="r32", type="relevant", expect=["effort"], query="what reasoning effort levels exist"),
    dict(id="r33", type="relevant", expect=["scorer"], query="how is the impact risk score calculated"),
    dict(id="r34", type="relevant", expect=["gh_accounts", "commits"], query="which github account do I use here"),
    dict(id="r35", type="relevant", expect=["why_sqlite"], query="why was a database chosen for the palace storage", heldout=True),
    dict(id="r36", type="relevant", expect=["graph_split"], query="how do graphify and the palace divide the work"),
    dict(id="r37", type="relevant", expect=["abstain"], query="when should memory stay silent instead of injecting"),
    dict(id="r38", type="relevant", expect=["names"], query="profile name gets changed to lowercase"),
    dict(id="r39", type="relevant", expect=["registry"], query="what if registry.json is corrupted"),
    dict(id="r40", type="relevant", expect=["desktop"], query="what is a surface for a profile", heldout=True),
    dict(id="r41", type="relevant", expect=["local"], query="how do local huggingface models run"),
    dict(id="r42", type="relevant", expect=["ide_env"], query="what do we know about cortex/ide.py"),
    dict(id="r43", type="relevant", expect=["guard_keys"], query="notes on guard.py", heldout=True),
    # ---- update: the newest fact wins, the superseded one must not appear -----------------------
    dict(id="u01", type="update", expect=["idle_new"], forbid=["idle_old"], query="what is the gateway idle timeout"),
    dict(id="u02", type="update", expect=["idle_new"], forbid=["idle_old"], query="how long before the gateway goes idle", heldout=True),
    # ---- quiet: nothing should be injected ------------------------------------------------------
    dict(id="q01", type="quiet", query="write a haiku about spring"),
    dict(id="q02", type="quiet", query="what is the capital of France", heldout=True),
    dict(id="q03", type="quiet", query="rename the variable x to count"),
    dict(id="q04", type="quiet", query="explain how binary search works"),
    dict(id="q05", type="quiet", query="fix the typo in the heading", heldout=True),
    dict(id="q06", type="quiet", query="hello"),
    dict(id="q07", type="quiet", query="thanks that worked"),
    dict(id="q08", type="quiet", query="summarize this paragraph for me", heldout=True),
    dict(id="q09", type="quiet", query="convert this list to json"),
    dict(id="q10", type="quiet", query="what is 17 times 23"),
    dict(id="q11", type="quiet", query="add a docstring to this function", heldout=True),
    dict(id="q12", type="quiet", query="make the button blue"),
    dict(id="q13", type="quiet", query="translate this sentence to spanish"),
    dict(id="q14", type="quiet", query="how do I center a div", heldout=True),
    dict(id="q15", type="quiet", query="give me a recipe for pancakes"),
    dict(id="q16", type="quiet", query="refactor this loop into a comprehension"),
    # near misses: they share one word with a memory but are about something else
    dict(id="q17", type="quiet", query="write a function that reverses a string"),
    dict(id="q18", type="quiet", query="install numpy with pip", heldout=True),
    dict(id="q19", type="quiet", query="add a button to the settings page"),
    dict(id="q20", type="quiet", query="the pool is closed for the winter", heldout=True),
    dict(id="q21", type="quiet", query="set up a new react app"),
    dict(id="q22", type="quiet", query="what is a good name for this class"),
    dict(id="q23", type="quiet", query="write unit tests for the checkout page"),
    dict(id="q24", type="quiet", query="why is my python loop so slow", heldout=True),
    dict(id="q25", type="quiet", query="please review my pull request description"),
]
