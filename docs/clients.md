# Run OpenCode

Choose `nix run .#opencode-9b` or `nix run .#opencode-27b` from the checkout.
From another project, replace `.` with the checkout path. OpenCode opens in your
current directory.

## Token limits

| Model | Context | Input limit | Output limit | Reasoning budget | Compaction threshold |
| --- | ---: | ---: | ---: | ---: | ---: |
| 9B | 131072 | 122880 | 8192 | 1024 | 114688 |
| 27B | 16384 | 12288 | 4096 | 2048 | 8192 |

Output includes reasoning, tool arguments, and the answer. Automatic compaction
keeps up to 8192 recent tokens for 9B and 4096 for 27B. Large tool results can still
exceed the reserve. See [OpenCode's compaction settings](https://dev.opencode.ai/v2/docs/config/#compaction).

## Server ownership

The launcher starts a server on port 8080 when needed and waits up to 30 minutes.
It rejects a different model alias or context size. On exit, it stops a server it
started and leaves a reused server running. Stop the old server before switching models.

## Overrides

[Environment variables](configuration.md#environment-variables) set port, context,
budgets, and memory options. Client limits adjust to context and output overrides:

```sh
BONSAI_BUDDY_PORT=8081 nix run .#opencode-27b
```

Arguments after `--` go to OpenCode. `--help` and `--version` skip server startup.
Each run uses OpenCode 2 in foreground mode with a temporary config. Your normal
settings, history, and MCP tools still load. The OpenCode process exits with the
client, so model settings apply even when another OpenCode server is running.
