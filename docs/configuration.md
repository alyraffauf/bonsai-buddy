# Configuration reference

Run the example commands from the repository root. The flake supports `x86_64-linux`.
Its defaults were measured on a Radeon RX 6700 with 10 GB of VRAM.

## Model profiles

| App | Context tokens | Weight format | KV cache | Decoding | Thinking budget | Output limit |
| --- | ---: | --- | --- | --- | ---: | ---: |
| `#9b` | 65536 | PQ2_0 | F16 | MTP, depth 1 | 1024 | 8192 |
| `#27b` | 16384 | PQ2_0 | Q8_0 | Standard | 2048 | 4096 |
| `#9b-plain` | 65536 | PQ2_0 | F16 | Standard | 1024 | 8192 |
| `#9b-rewrite` | 8192 | PQ2_0 | F16 | DFlash2, draft length 16 | 1024 | 4096 |
| `#9b-vulkan` | 32768 | PQ2_0 | F16 | Standard | 1024 | 8192 |
| `#27b-vulkan` | 8192 | PTQ1_0 | F16 | Standard | 1024 | 4096 |

The default app is `#9b`. All profiles use one server slot and flash attention.
The ROCm profiles use a source build with pinned upstream fixes for coding agents.
The Vulkan profiles use the pinned binary release.

The `#9b` profile uses MTP depth 1 for coding agents. The `#9b-rewrite` profile uses
DFlash2 for repetitive code rewrites with a reused prefix. DFlash2 was slower on prose
and cold prompts in the [measured workloads](../PERFORMANCE.md). The `#27b` profile uses
PQ2_0 weights and a 16K context to reduce cold-prompt latency while keeping every layer
on the tested GPU.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `BONSAI_BUDDY_PORT` | `8080` | Listening port on `127.0.0.1` |
| `BONSAI_BUDDY_CTX` | Profile context | Context capacity in tokens |
| `BONSAI_BUDDY_KV_TYPE` | Profile KV format | Key and value cache format, such as `f16` or `q8_0` |
| `BONSAI_BUDDY_THINK_TOKENS` | Profile budget | Generated reasoning-token budget |
| `BONSAI_BUDDY_MAX_TOKENS` | Profile output limit | Total generated output-token limit |
| `BONSAI_BUDDY_CACHE_MB` | `1024` | Host prompt-cache capacity in MiB |
| `BONSAI_BUDDY_GPU_RESERVE_MB` | `512` for 9B, `256` for 27B | Additional VRAM reserve in MiB |
| `BONSAI_BUDDY_MODELS_DIR` | Cache path below | Directory for model and projector files |
| `HSA_OVERRIDE_GFX_VERSION` | `10.3.0` | ROCm architecture override |

The ROCm runtime preserves an explicit `HSA_OVERRIDE_GFX_VERSION` value, including an
empty value. The `10.3.0` default is specific to the tested RDNA2 card. Compatibility
with other cards depends on the host driver and the pinned ROCm kernels.

For a smaller context on a memory-constrained GPU:

```sh
BONSAI_BUDDY_CTX=8192 nix run .#27b
```

For a different port and a larger thinking budget:

```sh
BONSAI_BUDDY_PORT=8081 BONSAI_BUDDY_THINK_TOKENS=4096 nix run .#9b
```

The launcher appends arguments after `--` to the `llama-server` command, following
the profile defaults. With `--help` or `--version`, the launcher calls `llama-server`
directly and skips the profile defaults.

```sh
nix run .#9b -- --image-max-tokens 4096
nix run .#9b -- --help
```

## Model cache

The cache directory follows this precedence:

1. `BONSAI_BUDDY_MODELS_DIR`, when nonempty.
2. `$XDG_CACHE_HOME/bonsai-buddy/models`, when `XDG_CACHE_HOME` is nonempty.
3. `$HOME/.cache/bonsai-buddy/models`.

For a new download, the launcher saves the file to a temporary path, verifies its
pinned SHA-256 checksum, and moves the file into the cache. If a nonempty file already
exists, the launcher reuses it without verifying its checksum again. If you delete a
cached file, the launcher downloads and verifies it again on the next run.

The launcher downloads model weights, vision projectors, and optional draft weights
from Prism's Hugging Face repositories. These files are separate from Nix build outputs.

## Agent behavior

The default API base URL is `http://localhost:8080/v1`. When you override the port,
replace `8080` with the value of `BONSAI_BUDDY_PORT`. The model alias is `bonsai2:9b`
or `bonsai2:27b`. The server returns reasoning separately as `reasoning_content`.
The 27B profiles map unsupported reasoning-effort values such as `high` to `medium`.

The output limit is 8192 tokens for `#9b`, `#9b-plain`, and `#9b-vulkan`.
It is 4096 tokens for `#27b`, `#9b-rewrite`, and `#27b-vulkan`. The `#27b` profile has a
2048-token reasoning budget. All other profiles default to 1024 tokens. These limits apply per request, not to
the accumulated conversation. Clients can override the defaults per request.

The 2048-token budget is a local tuning choice. [Prism's guidance](https://github.com/PrismML-Eng/Bonsai-demo#thinking)
recommends `medium` reasoning effort to reduce reasoning length. The launcher already
selects `medium` for 27B. A numeric budget still imposes a hard cutoff. At the reasoning
budget, the runtime injects a short transition message. That text can make the reported
reasoning-token count exceed the generated reasoning budget.

A chat request can override the profile budget with `reasoning_budget_tokens`. The
following fields set a 2048-token reasoning budget and a 4096-token total output limit:

```json
{
	"reasoning_budget_tokens": 2048,
	"max_tokens": 4096
}
```

An OpenAI SDK client can pass `reasoning_budget_tokens` through `extra_body`.
The total output limit includes reasoning and the answer or tool call. The prompt and
generated output share the context capacity.

By default, the server enables prompt caching, 32 context checkpoints, and a 1024 MiB
host cache. Stable system prompts, tool ordering, and conversation prefixes allow the
server to reuse more of the prompt. Clients that preserve prior assistant
`reasoning_content` can retain more of the prefix when they send tool results.
History compaction remains the client's responsibility. The [client launchers](clients.md)
configure it for the selected profile, including compaction near 8K tokens for 27B.

## GPU memory and vision

On a system with one visible DRM counter for VRAM usage, the ROCm launcher compares
physical usage with HIP's memory report. The launcher adds the non-HIP usage to the
configured reserve before fitting the model. If the query fails, the launcher adds all
physical usage reported by sysfs to the configured reserve. On other systems, automatic
fitting uses the configured reserve alone.

The `#27b` profile is close to the tested card's 10 GB capacity. Another GPU workload
or a larger reserve can move layers to the CPU and reduce speed. A smaller context frees
VRAM and can keep all layers on the GPU.

The vision projector runs on the CPU. Images use at most 1024 vision tokens by default.
`--image-max-tokens` controls that limit.

## Runtime packages

| Package | Contents |
| --- | --- |
| `#runtime-source` | Source engine and server with the release HIP plugin |
| `#runtime-rocm` | Pinned ROCm release, patched for Nix |
| `#runtime` | Vulkan release, repackaged for Nix |

The source revision and dependency hashes are pinned in `runtime-source.nix` and
`flake.lock`. ROCm benchmark apps are `#bench`, `#bench-rocm`, and `#bench-rocm-release`.
The Vulkan benchmark app is `#bench-vulkan`.
