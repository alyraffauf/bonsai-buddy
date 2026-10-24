# Configuration reference

All commands in this document run from the repository root. The flake supports
`x86_64-linux`. Its defaults were measured on a Radeon RX 6700 with 10 GB of VRAM.

## Model profiles

| App | Context tokens | Weight format | KV cache | Decoding | Output limit |
| --- | ---: | --- | --- | --- | ---: |
| `#9b` | 65536 | PQ2_0 | F16 | MTP, depth 1 | 8192 |
| `#27b` | 16384 | PQ2_0 | Q8_0 | Standard | 8192 |
| `#9b-plain` | 65536 | PQ2_0 | F16 | Standard | 8192 |
| `#9b-rewrite` | 8192 | PQ2_0 | F16 | DFlash2, draft length 16 | 4096 |
| `#9b-vulkan` | 32768 | PQ2_0 | F16 | Standard | 8192 |
| `#27b-vulkan` | 8192 | PTQ1_0 | F16 | Standard | 4096 |

The default app is `#9b`. All profiles use one server slot and flash attention.
The ROCm profiles use the source runtime with pinned upstream agent fixes.
The Vulkan profiles use the pinned binary release.

MTP is the default for 9B coding agents. The DFlash2 profile targets repetitive code
rewrites with a reused prefix. DFlash2 was slower on prose and cold prompts in the
[measured workloads](../PERFORMANCE.md). The 27B profile uses PQ2_0 weights and a
16K context to reduce cold-prompt latency while keeping every layer on the tested GPU.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `BONSAI_BUDDY_PORT` | `8080` | Listening port on `127.0.0.1` |
| `BONSAI_BUDDY_CTX` | Profile context | Context capacity in tokens |
| `BONSAI_BUDDY_KV_TYPE` | Profile KV format | Key and value cache format, such as `f16` or `q8_0` |
| `BONSAI_BUDDY_THINK_TOKENS` | `1024` | Generated reasoning-token budget |
| `BONSAI_BUDDY_MAX_TOKENS` | Profile output limit | Total generated output-token limit |
| `BONSAI_BUDDY_CACHE_MB` | `1024` | Host prompt-cache capacity in MiB |
| `BONSAI_BUDDY_GPU_RESERVE_MB` | `512` for 9B, `256` for 27B | Additional VRAM reserve in MiB |
| `BONSAI_BUDDY_MODELS_DIR` | Cache path below | Directory for model and projector files |
| `HSA_OVERRIDE_GFX_VERSION` | `10.3.0` | ROCm architecture override |

Explicit values for `HSA_OVERRIDE_GFX_VERSION`, including an empty value, pass through
unchanged. The `10.3.0` default is specific to the tested RDNA2 card. Compatibility
with other cards depends on the host driver and the pinned ROCm kernels.

For a smaller context on a memory-constrained GPU:

```sh
BONSAI_BUDDY_CTX=8192 nix run .#27b
```

For a different port and a larger thinking budget:

```sh
BONSAI_BUDDY_PORT=8081 BONSAI_BUDDY_THINK_TOKENS=4096 nix run .#9b
```

Arguments after `--` pass to `llama-server` after the profile defaults:

```sh
nix run .#9b -- --image-max-tokens 4096
nix run .#9b -- --help
```

## Model cache

The cache directory follows this precedence:

1. `BONSAI_BUDDY_MODELS_DIR`, when nonempty.
2. `$XDG_CACHE_HOME/bonsai-buddy/models`, when `XDG_CACHE_HOME` is nonempty.
3. `$HOME/.cache/bonsai-buddy/models`.

New downloads use temporary files, pass a pinned SHA-256 check, and move into the
cache after verification. Existing nonempty files are reused. Removing a cached
file causes the launcher to download and verify it again on the next run.

Model weights, vision projectors, and optional draft weights are downloaded from
Prism's Hugging Face repositories. They are separate from Nix build outputs.

## Agent behavior

The API base URL is `http://localhost:8080/v1`. The model alias is `bonsai2:9b` or
`bonsai2:27b`. The server returns reasoning separately as `reasoning_content`.
The 27B profile maps unsupported reasoning-effort values such as `high` to `medium`.

The main profiles allow 8192 total output tokens. The 8K profiles allow 4096.
At the reasoning budget, the runtime injects a short transition message. That text
can make the reported reasoning-token count exceed the generated reasoning budget.

The server enables prompt caching, 32 context checkpoints, and a 1024 MiB host cache.
Stable system prompts, tool ordering, and conversation prefixes permit more reuse.
Clients that preserve prior assistant `reasoning_content` can retain more of the prefix
when they send tool results. History compaction remains the client's responsibility.

## GPU memory and vision

On systems with one visible DRM VRAM-usage counter, the ROCm launcher compares physical
VRAM usage with HIP's memory report. It adds the usage omitted by HIP to the configured
reserve before fitting the model. If the query fails, it reserves the full physical
usage reported by sysfs. On other systems, fitting uses the configured reserve alone.

The 27B profile is close to the tested card's capacity. Another GPU workload or a
larger reserve can move layers to the CPU and reduce speed. A smaller context frees
VRAM while preserving GPU residency.

The vision projector runs on the CPU. Images use at most 1024 vision tokens by default.
`--image-max-tokens` controls that limit.

## Runtime packages

| Package | Contents |
| --- | --- |
| `#runtime-source` | Source engine and server with the release HIP plugin |
| `#runtime-rocm` | Unmodified ROCm release, repackaged for Nix |
| `#runtime` | Vulkan release, repackaged for Nix |

The source revision and dependency hashes are pinned in `runtime-source.nix` and
`flake.lock`. ROCm benchmark apps are `#bench`, `#bench-rocm`, and `#bench-rocm-release`.
The Vulkan benchmark app is `#bench-vulkan`.
