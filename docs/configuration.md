# Configuration reference

The flake supports `x86_64-linux`. Defaults target the RX 6700 with 10 GB of VRAM.

## Model profiles

| App | Context tokens | Weight format | KV cache | Decoding | Reasoning budget | Output limit |
| --- | ---: | --- | --- | --- | ---: | ---: |
| `#9b` | 131072 | PQ2_0 | F16 | MTP, depth 1 | 1024 | 8192 |
| `#27b` | 16384 | PQ2_0 | Q8_0 | Standard | 2048 | 4096 |
| `#9b-plain` | 131072 | PQ2_0 | F16 | Standard | 1024 | 8192 |
| `#9b-rewrite` | 8192 | PQ2_0 | F16 | DFlash2, draft length 16 | 1024 | 4096 |
| `#9b-vulkan` | 32768 | PQ2_0 | F16 | Standard | 1024 | 8192 |
| `#27b-vulkan` | 8192 | PTQ1_0 | F16 | Standard | 1024 | 4096 |

`#9b` is the default. All profiles use one slot and flash attention. The primary
ROCm profiles use microbatch 256. [Context capacity](context.md) explains the tradeoffs.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `BONSAI_BUDDY_PORT` | `8080` | Localhost port |
| `BONSAI_BUDDY_CTX` | Profile context | Context capacity |
| `BONSAI_BUDDY_KV_TYPE` | Profile format | Both KV cache formats |
| `BONSAI_BUDDY_KV_TYPE_K` | Common KV format | Key-cache override |
| `BONSAI_BUDDY_KV_TYPE_V` | Common KV format | Value-cache override |
| `BONSAI_BUDDY_UBATCH_SIZE` | Profile microbatch | Physical batch size |
| `BONSAI_BUDDY_THINK_TOKENS` | Profile budget | Reasoning-token cap |
| `BONSAI_BUDDY_MAX_TOKENS` | Profile output limit | Total output-token cap |
| `BONSAI_BUDDY_CACHE_MB` | `1024` | Host prompt cache, MiB |
| `BONSAI_BUDDY_GPU_RESERVE_MB` | 9B: `512`; 27B: `256` | Additional VRAM reserve, MiB |
| `BONSAI_BUDDY_MODELS_DIR` | Cache path below | Weights and projectors |
| `HSA_OVERRIDE_GFX_VERSION` | `10.3.0` | ROCm architecture override |

Per-key and per-value overrides fall back to `BONSAI_BUDDY_KV_TYPE`, then the
profile format. The ROCm override preserves explicit values, including an empty
value. Its default is specific to the tested RDNA2 card.

Arguments after `--` override server defaults. `--help` and `--version` skip model
setup. For example: `nix run .#9b -- --image-max-tokens 4096`.

## Model cache

The first nonempty setting wins:

1. `BONSAI_BUDDY_MODELS_DIR`.
2. `$XDG_CACHE_HOME/bonsai-buddy/models`.
3. `$HOME/.cache/bonsai-buddy/models`.

The launcher verifies new downloads against pinned SHA-256 checksums before moving
them into the cache. It reuses nonempty cached files without rehashing.

## API behavior

The endpoint is `http://localhost:8080/v1`; aliases are `bonsai2:9b` and `bonsai2:27b`.
Reasoning is returned as `reasoning_content`. The output cap includes reasoning and
the answer or tool call. Requests can override both caps:

```json
{
	"reasoning_budget_tokens": 2048,
	"max_tokens": 4096
}
```

At the reasoning cap, the runtime inserts a transition message. That text can push
reported reasoning usage above the generated-token budget. The 27B templates use
`medium` effort and map unsupported effort values to `medium`.

Prompt caching uses 32 checkpoints and 1024 MiB of host RAM. Stable prefixes and
preserved `reasoning_content` improve reuse. [Client launchers](clients.md) configure compaction.

## Memory and vision

ROCm fitting adds desktop VRAM to the reserve when a single readable DRM counter
is available. If the HIP query fails, it adds all reported physical usage instead.
Other systems use the configured reserve. Memory pressure can move layers to the CPU.

The vision projector runs on the CPU. `--image-max-tokens` defaults to 1024.

## Runtime packages

| Package | Contents |
| --- | --- |
| `#runtime-source` | Source engine with the release HIP plugin |
| `#runtime-rocm` | Pinned ROCm release |
| `#runtime` | Pinned Vulkan release |
| `#kernel-markers` | Decode markers for profiling |

Revisions and hashes live in [runtime-source.nix](../runtime-source.nix) and
[flake.lock](../flake.lock). Benchmark apps are `#bench`, `#bench-rocm`,
`#bench-rocm-release`, and `#bench-vulkan`. The `#profiling` shell supplies `rocprofv3`;
see [GPU profiling](profiling.md).
