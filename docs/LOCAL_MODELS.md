# Local models with Claude Cortex

Run Claude Code against an open model on your own machine - downloaded from Hugging Face,
served by llama.cpp, no cloud account involved.

```
cc local install --runtime        # llama.cpp (asks first, shows size + hash)
cc local install qwen3.5-4b       # a model   (asks first, shows size + hash)
cc local doctor --smoke           # checks every link and MEASURES your speed
cc offline                        # Claude Code on the local model
```

## Read this first: what is and is not verified

| Claim | Status |
|---|---|
| Request shaping, consent gate, downloads (resume, hash check, redirect safety), auth, SSE relay, pings, overflow rewrite, process safety | **Tested** with fakes (114 tests, mutation-checked) |
| A real `llama-server` + a real model + a real Claude Code session end to end | **Not run by the author of this code.** The first real run is yours: `cc local doctor --smoke` |
| Tokens/second on your machine | **Unknown until you measure it.** `doctor --smoke` prints a measured number; nothing here estimates speed |
| Any listed model "works well with Claude Code" | **Unproven.** The catalog lists suggestions; a model is not marked proven because a list says so |
| Anthropic support | **None.** Anthropic's documentation says non-Claude models behind a gateway are unsupported. Pin versions and re-test after updates |

Small local models are much weaker than Claude at multi-step agent work. Expect them to be
useful for short, well-scoped edits and questions - not for the long autonomous runs a
frontier model handles. This integration makes the plumbing work; it cannot make a 4B model
as capable as a cloud one.

## Safety model

* **Nothing downloads, installs or deletes without a person saying yes.** Every such action
  shows the source, each file with its size and sha256, and the destination, and defaults to
  **No**.
* **An agent can never approve.** Inside a Claude Code session (`CLAUDECODE` is set) the
  consent gate refuses even with `--yes`. If Claude suggests a download, run the command
  yourself in a normal terminal.
* **Only `.gguf` files.** A model repo can hold pickles and scripts; files are accepted by
  extension, hash-verified, and written only inside the models folder. Paths from the
  network are checked so they cannot escape it.
* **Hugging Face token** (`HF_TOKEN`, only if you set it for gated repos) is sent to
  `huggingface.co` only, and dropped on any redirect to another host. Cortex never asks for,
  stores or prints one.
* **Loopback only, behind a token.** `llama-server` and the gateway bind to `127.0.0.1`. The
  token lives in `~/.claude/cortex-local/token`, owner-only (ACLs on Windows), and is passed
  to `llama-server` as a file, not on the command line where other programs could read it.
* **Runtime from one place.** llama.cpp comes only from the official `ggml-org/llama.cpp`
  releases. Not from links on model cards, not from the winget package (a Vulkan build).
* **Your cloud credentials stay out.** `cc offline` drops `ANTHROPIC_API_KEY`, OAuth tokens
  and provider switches from the environment, and uses its own config folder.

## Commands

| Command | What it does |
|---|---|
| `cc local status` | Hardware, runtime, what is running, and which catalog models fit this machine |
| `cc local search <text>` | Search Hugging Face for GGUF repos (search only; flags unknown publishers) |
| `cc local install --runtime [--backend cuda-12.4]` | Install llama.cpp after you confirm |
| `cc local install <id>` / `<owner/repo> --quant Q4_K_M` | Download a model after you confirm; resumable; verified |
| `cc local list` / `use <id>` | Installed models / choose the active one |
| `cc local serve [id] [--force]` | Start the model server and the gateway |
| `cc local stop` | Stop both and release VRAM/RAM |
| `cc local doctor [--smoke]` | Check every link; `--smoke` sends one tiny request and measures speed |
| `cc local logs [server\|gateway]` | Tail the logs |
| `cc local env` | Show the session environment (token hidden) |
| `cc local runtime [--path EXE]` | Show or set which `llama-server` to use |
| `cc local rm <id>` | Delete a model's files after you confirm (only inside the models folder) |
| `cc offline [claude args] [--local-model ID]` | Start Claude Code on the local model |

`cc offline` starts the model and gateway on demand and stops them after
`idle_stop_minutes` (default 30) with no traffic, so a laptop does not keep gigabytes of
VRAM pinned.

## Choosing a model for a 6 GB GPU

Sizes were read from the Hugging Face listing on 2026-10-11; real sizes and hashes are shown
at install time. "Fits" comes from `cc local status`, which uses your current free RAM.

| id | size | Notes |
|---|---|---|
| `qwen3.5-4b` | ~2.7 GB | Fits entirely in VRAM. The model to try first |
| `qwen3.5-9b` | ~5.7 GB | Daily driver for short tasks once ~4.5 GB of RAM is free |
| `mellum2.1-12b-a2.5b` | ~7.0 GB | Experimental: vendor numbers only |
| `qwen3-coder-30b-a3b` | ~12.9 GB | Non-thinking coder; needs ~11 GB free RAM |
| `qwen3.6-35b-a3b` | ~13.2 GB | Strongest that fits at all; needs ~11 GB free RAM and little else running |
| `gpt-oss-20b` | ~12.1 GB | Mature llama.cpp support |

Not offered: dense 27B models (2-3 tokens/s here) and 80B models (smallest sane quant is over
40 GB). The fit check is deliberately conservative - it keeps 2 GB free for Windows - and
`--force` overrides it.

## Reasoning levels: `low` ... `xhigh` ... `max`, and `ultracode`

Claude Code sends its effort level to the API as `output_config.effort`
(`low | medium | high | xhigh | max`). A cloud Claude model turns that into adaptive thinking.
A local model has no such thing, so the gateway **translates the level into an explicit
thinking budget**, per request:

| Level | Turn start | After a failed tool call | Tool-result follow-ups |
|---|---|---|---|
| low | off | off | off |
| medium | 2048 | 1024 | off |
| high | 4096 | 1024 | off |
| xhigh | 8192 | 2048 | off |
| max | 16384 | 4096 | off |

Why that shape: thinking is spent where it pays - at the start of a task and right after
something failed - and not on every tool result, which would multiply latency on a model
that is already slow. Budgets are always clamped to leave 1024 tokens for the answer, and an
unrecognised level means *no* thinking, never an upgrade. **These numbers are starting
points, not measured optima.** Every request writes one metadata line (never prompt text) to
`~/.claude/cortex-local/logs/gateway-events.jsonl` so you can tune
`reasoning.levels` in `config.json` from your own runs.

How a model receives it depends on its chat template, set per catalog entry: Qwen3.x gets
`enable_thinking` sent explicitly on **every** request (the server default is on, so omitting
it would make `low` think anyway); gpt-oss gets a low/medium/high variable; always-thinking
models get a budget cap only; non-thinking models get every thinking field removed.

**`ultracode` is not a reasoning level.** It is a Claude Code mode that orchestrates many
subagent calls (workflows). `cc -e ultracode` is accepted and passed through, but on a small
local model it usually makes things worse: more calls means more chances for a weak model to
go wrong, and each call is slow. What helps instead:

1. Use `max` for the hard step, `medium` for the rest.
2. Verify with tests rather than thinking harder: run the tests, feed the failure back, retry.
   The per-failure thinking bump above does a small version of this automatically.
3. Hybrid: let a cloud model plan and use the local model for bulk edits.
4. If you try it anyway, keep concurrency low (`gateway.max_concurrent`) and expect slowness.

## How it fits together

```
cc offline -> Claude Code --(Anthropic API, bearer token)--> Cortex gateway --> llama-server --> model
                                                 |  shapes requests, answers count_tokens,
                                                 |  pings during prefill, rewrites overflow
                          ~/.claude/cortex-local/profile   (its own config dir, no cloud login)
```

Fixes the gateway applies, each against a verified llama.cpp / Claude Code gap:

* Strips Anthropic-only request fields (`output_config`, `context_management`,
  `cache_control`, ...).
* Moves `tool_result` blocks ahead of text; folds mid-conversation system messages into the
  next user message (hoisting them would break the prompt cache and several chat templates).
* Overrides Claude Code's `temperature=1` with the model's recommended sampling.
* Streams line by line (buffering delayed events by seconds) and sends `ping` events while
  the model is silent reading a long prompt, so Claude Code's idle watchdog does not abort.
* Turns a context overflow into "Prompt is too long", which Claude Code compacts on.
* Answers `/v1/messages/count_tokens` instead of running a generation for it.
* Stops generating when the client disconnects.

## Where things live

Under `~/.claude/cortex-local/` (override with `CORTEX_LOCAL_HOME`): `config.json` (no
secrets), `token`, `state/`, `logs/`, `runtime/<tag>/`, `profile/`. Models go to
`<drive>:\cortex-models\` on the drive with the most room - not the system drive unless
nothing else fits - or wherever you pass `--dir`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `doctor` fails on "runtime" with a CUDA build | Driver too old for that CUDA version: `cc local install --runtime --backend cuda-12.4` (or `cpu`) |
| "does not fit" | Close programs to free RAM, pick a smaller model, or `--force` |
| First response takes a long time | Prompt prefill: Claude Code's base prompt is 6-33k tokens. The gateway pings so it does not time out. Measured by `doctor --smoke` |
| Claude keeps compacting | The context is small (16k default). Expected on tight hardware |
| Port in use | Change `ports.server` / `ports.gateway` in `config.json` |
| `config.json` problems | An unparseable or newer-schema file is never overwritten; `cc local doctor` names it |
