# Run OpenCode

Run one of these commands from the checkout:

| Model | Command |
| --- | --- |
| 9B | `nix run .#opencode-9b` |
| 27B | `nix run .#opencode-27b` |

When working in another project directory, replace `.` with the path to this checkout.
The client opens in your current directory. Nix supplies the client and model runtime.

The launcher starts a model server on port 8080 if no healthy server is there.
It waits up to 30 minutes for the model to load, then opens the client. On exit, it stops a server
it started. A reused server stays running, with its existing generation defaults.
The launcher rejects a server with a different model alias or context size.

To switch models, exit the client and stop any separately started server before
launching the other profile. Run one GPU model at a time for the measured performance.

## Context and output limits

| Profile | Context | Reasoning budget | Total output limit | Compaction threshold |
| --- | ---: | ---: | ---: | ---: |
| 9B | 65536 | 1024 | 8192 | 49152 |
| 27B | 16384 | 2048 | 4096 | 8192 |

The output limit includes reasoning, tool arguments, and the final answer. The prompt,
tool definitions, history, and generated output share the context window. A reasoning
budget is a per-request cap, so it cannot bound the total history of an agent session.

For 27B, compaction starts near 8K used tokens to leave space for the next response,
tool results, and the summary. Large tool outputs can still exceed that reserve in
one step. Keep file reads and tool results bounded. Disable unused MCP tools because
their definitions also consume context.

OpenCode uses an input limit of 12288 for 27B, an output limit of 4096, and a compaction
reserve of 4096. Its threshold is the input limit minus that reserve. Automatic
compaction and removal of old tool outputs are enabled. See [OpenCode's configuration
reference](https://opencode.ai/docs/config/#compaction).

OpenCode's per-request options set the reasoning budget and output limit, including
when it reuses a server.

## Override settings

The client launchers accept the same port and token environment variables as the
[model profiles](configuration.md#environment-variables). They recalculate client
limits when context or output settings change. They require finite nonnegative
reasoning budgets and room for the final answer.

```sh
BONSAI_BUDDY_PORT=8081 nix run .#opencode-27b
```

Arguments after `--` pass to the client:

```sh
nix run .#opencode-27b -- --help
nix run .#opencode-9b -- --version
```

`--help` and `--version` do not start a model server. Nix may still build dependencies. The launchers create a temporary
OpenCode configuration for each run. Your normal client settings still load,
including any configured MCP tools.
