# Run Bonsai 2 locally

Run either model in your terminal:

```sh
nix run ~/src/bonsaid#9b
nix run ~/src/bonsaid#27b
```

Open http://localhost:8080. Press Ctrl+C to stop the server.
Plain `nix run ~/src/bonsaid` selects 9B.

These profiles target the Radeon RX 6700 with 10 GB VRAM on x86_64 Linux.
They use ROCm with `HSA_OVERRIDE_GFX_VERSION=10.3.0`, matching Hoenn's Petalburg configuration.
The runtime includes pinned upstream fixes for agent tool grammars and malformed input.
The first build compiles the server and web UI. Nix caches later runs.

| App | Context | Packing and decoding | Use |
| --- | ---: | --- | --- |
| `#9b` | 64K | PQ2_0 with MTP depth 1, F16 KV | Default for coding agents |
| `#27b` | 32K | PTQ1_0, Q8 KV | Larger model with room for agent history |
| `#9b-plain` | 64K | PQ2_0, F16 KV | 9B without speculative decoding |
| `#9b-rewrite` | 8K | PQ2_0 with DFlash2, F16 KV | Cached, repetitive code rewrites |
| `#27b-prefill` | 8K | PQ2_0, Q8 KV | Faster cold prompts with a shorter context |

`#9b-vulkan` and `#27b-vulkan` provide the release's Vulkan backend as alternatives.
They use 32K and 8K contexts respectively.

All apps run in the foreground. They cache model files in
`${XDG_CACHE_HOME:-$HOME/.cache}/bonsaid/models` and verify new downloads with SHA-256.
Run one model at a time for the measured performance on this GPU.

The OpenAI-compatible API is at http://localhost:8080/v1.
Use model name `bonsai2:9b` or `bonsai2:27b`, matching the selected size.
Enable history compaction in your agent and configure its context limit to match the profile.

Thinking defaults to 1024 tokens. Main profiles allow up to 8192 total output tokens;
the short 8K profiles allow 4096. Clients can override these defaults per request.
At the thinking limit, a short transition message prompts the answer or next tool call.
If thinking is enabled, leave room for both reasoning and the final answer in the client's output limit.
The 27B profile maps unsupported reasoning-effort values such as `high` to `medium`.
If your agent supports it, preserve `reasoning_content` on previous assistant messages
when sending tool results. This keeps more of the conversation prefix reusable.

To change defaults, set these environment variables:

| Variable | Default |
| --- | --- |
| `BONSAI_PORT` | `8080` |
| `BONSAI_CTX` | Profile context |
| `BONSAI_KV_TYPE` | Profile KV type |
| `BONSAI_THINK_TOKENS` | `1024` |
| `BONSAI_MAX_TOKENS` | Profile output limit |
| `BONSAI_CACHE_MB` | `1024` MiB of host prompt-cache storage |
| `BONSAI_GPU_RESERVE_MB` | `512` MiB for 9B, `256` MiB for 27B, beyond desktop VRAM |
| `BONSAI_MODELS_DIR` | Model-cache path above |

For example:

```sh
BONSAI_PORT=8081 nix run ~/src/bonsaid#9b
BONSAI_THINK_TOKENS=4096 nix run ~/src/bonsaid#9b
```

Arguments after `--` pass to llama-server. The vision projector runs on the CPU to reserve VRAM for agent context.
Large images are downscaled to 1024 vision tokens; pass `--image-max-tokens 4096` for more detail.

Read [the measurements and tuning decisions](PERFORMANCE.md) for benchmark results,
tradeoffs, and commands to repeat the tests.
