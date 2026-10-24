# Bonsai performance on the RX 6700

Measurements taken on 2026-10-23, with a Radeon RX 6700, 10 GB VRAM,
Ryzen 5 5600X, 32 GB system RAM, and PCIe 4.0 x16.
The target workload is coding with long-running tool loops.

## End-to-end agent results

The test reads a roughly 3500-token Python file, fixes a subtraction bug through
an exact replacement, runs simulated unit tests, and produces a final response.
Tool arguments must parse as JSON and the resulting function must contain the correct AST.
The speed comparison uses greedy non-thinking requests, so thinking latency is excluded.
These are small synthetic tasks, not a coding-quality evaluation suite.

| Configuration | Context capacity | Read/edit/test loop |
| --- | ---: | ---: |
| Original 9B, Vulkan, batch 256 / microbatch 128 | 8K | 21.91 s |
| Final `#9b`, ROCm, MTP depth 1 | 64K | 7.05 s |
| Original 27B, Vulkan, PTQ1_0 | 8K | 45.29 s |
| Final `#27b`, ROCm, PTQ1_0, Q8 KV | 32K | 36.64 s |
| `#27b-prefill`, ROCm, PQ2_0, Q8 KV | 8K | 23.07 s |

All five cases passed. Startup and model loading are excluded from these timings.
The main 9B profile is about 3.1 times faster on this task while allowing more history.
The main 27B profile trades some cold-prefill speed for a larger context that fits this GPU.
The shorter 27B profile completes this task about twice as fast as the original setup.

The 64K and 32K numbers are configured capacities. The agent test does not fill them.
A separate test used a 7244-token prompt and verified prefix reuse at those capacities.
Generation slows as the active context grows.

Raw records are under `benchmarks/results/agent-final/` and
`benchmarks/results/agent-vulkan-baseline/`. A shared-GPU final test was discarded;
the table uses the subsequent isolated run.

The shipped defaults keep thinking enabled with a 1024-token budget. Separate tests
using those defaults passed the same tool loop in 10.88 s for 9B and 42.10 s for 27B,
with previous `reasoning_content` included in the conversation. These are single
sampled runs, so they do not establish a precise speed ratio against the greedy tests.
Their raw records are under `benchmarks/results/thinking-preserved/`.

## Backend, packing, and batching

ROCm works with `HSA_OVERRIDE_GFX_VERSION=10.3.0`, matching
[Hoenn's Petalburg configuration](../pokeworld/hoenn/nix/hosts/nixos/petalburg/ollama.nix).
The release's current HIP kernels work on this card despite older reports of RDNA2 failures.
Both Vulkan and ROCm remain available in the flake.

The first Vulkan 9B baseline measured 272 prefill tokens/s and 43 generation tokens/s
with a 512-token prompt and 64 generated tokens. Increasing the microbatch from 128
to 256 or 512 raised prefill to 663 to 684 tokens/s in the controlled batch sweep.
Generation stayed near 43 tokens/s.

ROCm 9B prefill reached about 926 tokens/s on the 512-token test and about
960 tokens/s with a 2048-token prompt and microbatch 512. Plain 9B HTTP generation
was about 83 tokens/s on the explanation and code-edit workloads.
The larger prompt length matters; these prefill figures are separate measurements.

For 27B on ROCm, PQ2_0 reached about 277 prefill tokens/s versus 152 for PTQ1_0
on the 512-token test. Decode was similar, roughly 28 versus 27 tokens/s.
PQ2_0 occupies about 1.3 GB more disk space and GPU weight memory, so the main 27B
profile uses PTQ1_0 to leave room for a longer agent context.

The main 9B preset uses batch 2048 / microbatch 512. Microbatch 1024 added little.
The 27B presets use 1024 / 256; larger microbatches increased memory use without a useful gain.
Q2_0 was also tested on 9B and did not beat PQ2_0 as a combined prefill/decode choice.

## Speculative decoding depends on the workload

These HTTP tests used 192 generated tokens, greedy non-thinking sampling,
an 8K context, and two repetitions per workload. Prefill is excluded from the rates.

| 9B decoding mode | Explanation tokens/s | Code-edit tokens/s |
| --- | ---: | ---: |
| Plain PQ2_0 | 83.2 | 82.5 |
| Plain PTQ1_0 | 86.2 | 85.8 |
| MTP depth 1 | 95.5 | 113.0 |
| MTP depth 2 | 81.3 | 110.2 |
| MTP depth 4 | 59.5 | 117.6 |
| DFlash2, draft length 16 | 49.5 | 162.6 |

MTP depth 1 is the main 9B choice. It improves decode without adding a separate
full draft model, and it preserved prompt-cache reuse and valid tool calls in the tests.

DFlash is useful for repetitive rewrites. It was slower on prose, cold prefill,
and the read/edit/test loop. Larger DFlash context allocations also hurt cold prefill.
Its separate `#9b-rewrite` preset keeps an 8K context; use the main profile for agent history.

Both the default n-gram mode and a shorter-lookup n-gram configuration were tested.
They did not provide a consistent gain across these workloads. A 2B autoregressive
drafter for 27B reduced generation to roughly 9 tokens/s on prose and 13 on edits,
so it is not enabled.

## Prefix reuse is the largest recurring-turn gain

With one slot, checkpoints enabled, and a 1 GiB host cache, a repeated 3532-token
code request reused 3528 tokens. The server still evaluates a short suffix for logits.

| Mode | Cold prefill | Cached prefill |
| --- | ---: | ---: |
| 9B plain | 4.15 s | 27 ms |
| 9B MTP depth 1 | 4.35 s | 30 ms |
| 9B DFlash | 8.84 s | 38 ms |
| 27B PQ2_0 | 14.29 s | 80 ms |

A longer 7244-token request at the main context capacities reused 7240 tokens.
Cached prefill was about 35 ms for 9B MTP and 130 ms for 27B PTQ1_0 with Q8 KV.
Stable system prompts, tool ordering, and conversation prefixes matter more than
small kernel changes once an agent has a long history.

The presets keep `--parallel 1`, `--ctx-checkpoints 32`, `--cache-prompt`, and
`--cache-ram 1024`. These favor one active coding session. Concurrent agents can
share the server, but this configuration queues work rather than maximizing batch throughput.
History compaction remains the client's responsibility.

Preserving previous assistant `reasoning_content` reduced the suffix that needed
evaluation on subsequent tool turns. In the thinking-enabled 9B test, the test-result
turn evaluated 19 new tokens with reasoning preserved versus 98 with reasoning omitted.
Both approaches passed. The preserved run took 10.88 s versus 9.91 s without it,
so this small test demonstrates additional prefix reuse rather than lower total latency.

## KV precision and context

At depth 2048, 9B F16 KV decoded around 80 tokens/s, Q8 around 77, and Q4 around 73.
F16 remains the 9B default because it fits and was faster here.
Flash attention off also reduced 9B decode to around 73 tokens/s.

27B uses Q8 KV to fit a 32K context with the desktop still using VRAM.
This is a memory/precision tradeoff. Q4 was benchmarked but is not a default;
its quality effects need more than the small correctness tests used here.
Prism also recommends a calibration workflow for its experimental Q4 KV mode.

The launcher reserves 512 MiB for 9B and 256 MiB for 27B beyond desktop VRAM on this workstation.
HIP's free-memory report does not fully account for the desktop allocations observed here.
If another model is resident, automatic fitting can move layers onto the CPU and decode can slow sharply.
The full-profile checks must run with the GPU otherwise clear.
27B is close to this card's capacity. A larger reserve can move a transformer layer
onto the CPU and disable the fused Gated Delta Net path. Lower the context if you
need more headroom while keeping all layers on the GPU.

## Agent-runtime improvements

The server and common libraries are pinned to
[`b87ca7225`](https://github.com/PrismML-Eng/llama.cpp/commit/b87ca7225456b06b0975b8239c66b5aecf07e37c),
seven commits beyond release `prism-b10787-73bfe6c`.
Those commits include faster grammar cloning, handling for malformed UTF-8,
and fixes for some schema-generator inputs.

The GPU plugin remains from that release. The intervening commits change no GPU code
or backend ABI; the source build rebuilds the engine and CPU/common code and reuses
the pinned HIP plugin. Both runtime versions are available for comparison.

On this CPU, cloning a synthetic 107-tool grammar 100 times averaged
1.271 ms per clone in the release and 0.089 ms in the source build, about 14 times faster.
This is a CPU operation, not a 14-fold improvement to an entire agent task.
The relevant [upstream change](https://github.com/PrismML-Eng/llama.cpp/commit/a75f770c2a09ba0764e3373d688c4585db879d6d)
replaces a linear rule search during cloning with a binary search.

Thinking is capped at 1024 tokens by default and is returned separately from the answer.
At the cap, the runtime injects a short transition to the answer or next tool call.
Forced 64-token budget checks returned a clean final answer for both models;
the reported reasoning includes the transition text in addition to the generated budget.
The longer main contexts and finite output limits replace the original 8K/unlimited setup.
27B also maps unsupported reasoning-effort values to `medium`, avoiding the model template's
error for clients that send `high`. Clients can request different budgets.
Final main-profile checks confirmed 34/34 layers on the GPU for 9B and 65/65 for 27B,
the expected context capacities, and correct arithmetic. The 9B web UI and a simple
image-color request also passed.

## Other routes examined

| Route | Finding |
| --- | --- |
| CPU threads 1, 2, 4, 6, 12 | One thread hurt 27B; more than the six physical cores gave no useful sustained gain |
| `GGML_CUDA_GRAPH_OPT=1` | Slower in the sampled runs; left off |
| Disabling CUDA/HIP graphs | No useful sustained improvement found |
| Q8 prefill F16 staging | Slower in the 27B screening test; left off |
| Hadamard and GDN fusions | Already enabled in the release; retained |
| Newer fork GPU changes | No GPU changes in the seven post-release commits used here |
| Open RDNA4 kernel work | Targets different hardware and older quantization paths; not applied to this RDNA2 preset |
| CPU offload | Capacity fallback, not the target for fast decode; all-GPU placement is checked for the main presets |
| NUMA / PCIe tuning | One NUMA node and an active PCIe 4.0 x16 link; no configuration change needed |
| Clocks / power limits | Firmware cap was already at its exposed maximum; no host clock or power changes made |
| Prompt shortening / fewer tool schemas | Useful client-side work; not implemented by rewriting the agent's prompts in this server |
| GPU vision encoding | Not tuned here; the projector stays on CPU to reserve VRAM for coding context |
| Concurrent-batch throughput | Not selected over interactive latency and one-session cache reuse |

Unmeasured shader toggles, source builds with different compiler kernels, larger multi-request
throughput sweeps, and full coding-quality evaluations remain further experiments.
This report does not claim a globally optimal configuration.

See [benchmark commands](benchmarks/README.md) to repeat the measurements.
