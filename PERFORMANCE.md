# Bonsai Buddy performance on the RX 6700

This report uses measurements from 2026-10-23. The NixOS test system had a Radeon RX 6700
with 10 GB of VRAM, a Ryzen 5 5600X, 32 GB of RAM, and PCIe 4.0 x16. The tuning target
was latency for coding agents that make repeated tool calls.

## End-to-end agent results

The test reads a Python file of roughly 3500 tokens, fixes a subtraction bug with an
exact replacement, runs simulated unit tests, and returns a final response. Tool arguments
must parse as JSON. A pass requires the expected AST for `add`, unchanged helper functions,
a read before the edit, and tests after the last edit. The speed comparison uses greedy
requests with thinking disabled. This small synthetic task does not measure general coding quality.

| Configuration | Context capacity | Coding-task time |
| --- | ---: | ---: |
| 9B baseline, Vulkan, batch 256, microbatch 128 | 8K | 21.91 s |
| Tuned `#9b`, ROCm, MTP depth 1 | 64K | 7.05 s |
| 27B baseline, Vulkan, PTQ1_0 | 8K | 45.29 s |
| 27B comparison, ROCm, PTQ1_0, Q8 KV | 32K | 36.64 s |
| Tuned `#27b`, ROCm, PQ2_0, Q8 KV | 16K | 22.70 s |

All five cases passed. The timings exclude startup and model loading. `#9b` was about
3.1 times faster than its Vulkan baseline and used a 64K context instead of 8K. `#27b`
completed the task about twice as fast as its Vulkan baseline. The 32K PTQ1_0 comparison
provided more context than `#27b`, but its slower prefill raised the task time to 36.64 s.

The context sizes are configured capacities. The agent test does not fill them.
Generation slows as the active context grows.

The [agent measurement records](benchmarks/measurements/agent.json) include per-turn
timings. The table uses runs with no other model using the GPU. An earlier run that
shared the GPU with another model was excluded.

The thinking-enabled measurements used a 1024-token reasoning budget. When the client
preserved previous `reasoning_content`, `#27b` passed three runs in 32.01, 34.28, and
65.20 s. The median was 34.28 s. The two shorter runs used four turns. The longer run
used seven turns, including an extra file read and repeated test calls. A single
thinking-enabled `#9b` run passed in 10.88 s.

The earlier 32K PTQ1_0 configuration passed a thinking-enabled run in 42.10 s.
These few runs do not establish a precise speed ratio. Replaying the eight original saved
transcripts with the stricter checker confirmed that each preserved the helper functions
and ran tests after its last edit.

## Backend, packing, and batching

The tested RX 6700 uses `HSA_OVERRIDE_GFX_VERSION=10.3.0`. The pinned HIP kernels
worked with that override. Both Vulkan and ROCm remain available in the flake. Set
`HSA_OVERRIDE_GFX_VERSION` to a different value for other hardware.

The first Vulkan 9B baseline measured 272 prefill tokens/s and 43 generation tokens/s
with a 512-token prompt and 64 generated tokens. Increasing the microbatch from 128
to 256 or 512 raised prefill to 663 to 684 tokens/s in the controlled batch sweep.
Generation stayed near 43 tokens/s.

ROCm 9B prefill reached about 926 tokens/s on the 512-token test and about
960 tokens/s with a 2048-token prompt and microbatch 512. Without speculative decoding,
9B HTTP generation was about 83 tokens/s on the explanation and code-edit workloads.
These prefill figures come from separate tests with different prompt lengths.

For 27B on ROCm, PQ2_0 reached about 277 prefill tokens/s on the 512-token test,
compared with 152 for PTQ1_0. Decode was about 28 tokens/s for PQ2_0 and 27 tokens/s
for PTQ1_0. The PQ2_0 weights are about 1.3 GB larger on disk and in GPU memory.
The 32K comparison used PTQ1_0 to leave room for a longer context.

A follow-up capacity test found that the PQ2_0 profile fit a 16K context with all
65 layers on the GPU. The 16K PQ2_0 configuration completed the task in 22.70 s,
compared with 23.07 s for the 8K configuration. The `#27b` profile therefore uses
PQ2_0 at 16K. A 16K PTQ1_0 test with F16 KV took 39.03 s and also kept all layers
on the GPU. With PQ2_0 at 32K, automatic fitting placed only 61 of 65 layers on the
GPU. Fitting also disabled the fused Gated Delta Net, or GDN. The task took 32.99 s,
and the last two turns decoded at about 15 tokens/s. Desktop VRAM usage can change
the largest context that keeps every layer on the GPU. The 16K result does not guarantee
the same layer placement on another machine.

The `#9b` profile uses batch 2048 and microbatch 512. Microbatch 1024 offered little
improvement over 512. The 27B profiles use batch 1024 and microbatch 256. Larger
microbatches used more memory without a useful speed gain. A separate 9B Q2_0
screening run measured about 550 prefill tokens/s and 80 generation tokens/s with
a 256-token prompt and 64 generated tokens. PQ2_0 remains the selected format based
on the batching and HTTP tests. The [inference records](benchmarks/measurements/inference.json)
include samples and benchmark parameters.

## Speculative decoding depends on the workload

These HTTP tests generated 192 tokens per request with greedy sampling and thinking
disabled. They used an 8K context and two repetitions per workload. The rates exclude
prefill. The [HTTP records](benchmarks/measurements/http.json) include individual requests
and cache tests.

| 9B decoding mode | Explanation tokens/s | Code-edit tokens/s |
| --- | ---: | ---: |
| Plain PQ2_0 | 83.2 | 82.5 |
| Plain PTQ1_0 | 86.2 | 85.8 |
| MTP depth 1 | 95.5 | 113.0 |
| MTP depth 2 | 81.3 | 110.2 |
| MTP depth 4 | 59.5 | 117.6 |
| DFlash2, draft length 16 | 49.5 | 162.6 |

The `#9b` profile uses MTP depth 1. MTP improves decode without adding a separate
full draft model. MTP depth 1 retained prompt-cache reuse in the cache tests and produced
valid tool calls in the agent test.

DFlash2 is useful for repetitive rewrites. It was slower on prose, cold prefill, and
the coding-agent loop. Larger DFlash2 context allocations also slowed cold prefill.
The separate `#9b-rewrite` profile keeps an 8K context. Use `#9b` for agent history.

Tests covered both the default n-gram mode and a shorter-lookup n-gram configuration.
Neither provided a consistent gain across these workloads. A 2B autoregressive drafter
for 27B reduced generation to roughly 9 tokens/s on prose and 13 on edits, so no profile
enables it.

## Prefix reuse gave the largest gain on later turns

These cache tests used an 8K context, batch 1024, microbatch 256, F16 KV, one slot,
32 checkpoints, and a 1 GiB host cache. A repeated 3532-token code request reused
3528 tokens. The server still evaluates a short suffix for logits.

| Mode | Cold prefill | Cached prefill |
| --- | ---: | ---: |
| 9B plain | 4.15 s | 27 ms |
| 9B MTP depth 1 | 4.34 s | 30 ms |
| 9B DFlash2 | 8.84 s | 38 ms |
| 27B PQ2_0 | 14.29 s | 80 ms |

A longer 7244-token request reused 7240 tokens at 64K capacity for 9B and at
32K capacity for the PTQ1_0 comparison. Cached prefill was about 35 ms for 9B MTP
at 64K capacity and 130 ms for the 27B PTQ1_0 comparison at 32K capacity with Q8 KV.
Stable system prompts, tool ordering, and conversation prefixes preserve the prefix
across turns.

All model profiles use `--parallel 1`, `--ctx-checkpoints 32`, `--cache-prompt`, and
`--cache-ram 1024`. These settings favor one active coding session. Concurrent agents
can share the server, but one slot queues their work instead of maximizing batch throughput.
History compaction remains the client's responsibility.

Preserving previous assistant `reasoning_content` reduced the suffix that needed
evaluation on later tool turns. In the thinking-enabled `#9b` test, the request after
the test result evaluated 19 new tokens with reasoning preserved and 98 with reasoning
omitted. Both runs passed. The preserved run took 10.88 s, compared with 9.91 s when
the client omitted previous reasoning. The preserved run reused more of the prefix but
took longer overall.

## KV precision and context

In `llama-bench` tests with `n_depth = 2048`, 9B F16 KV decoded at about 80 tokens/s,
Q8 at 77, and Q4 at 73. The 9B profiles keep F16 because it fit in memory and was faster
in these tests. Disabling flash attention reduced 9B decode to about 73 tokens/s.

The `#27b` profile uses Q8 KV to fit PQ2_0 weights and a 16K context while the desktop
uses VRAM. The earlier PTQ1_0 comparison also used Q8 at 32K. No profile enables Q4
by default. The small correctness tests here do not establish Q4's effect on model quality.

On the tested system, the launcher reserves 512 MiB for 9B and 256 MiB for 27B in
addition to desktop VRAM. HIP's free-memory report does not fully account for the desktop
allocations observed here. If another model is resident, automatic fitting can move layers
onto the CPU and reduce decode speed. The layer-residency and capacity checks require
a GPU with no other model resident.

The `#27b` configuration nearly fills the RX 6700's 10 GB of VRAM. A larger reserve can
move a transformer layer onto the CPU and disable the fused Gated Delta Net path.
A smaller context frees VRAM and can keep every layer on the GPU.

## Runtime changes for coding agents

The server and common libraries are pinned to
[`b87ca7225`](https://github.com/PrismML-Eng/llama.cpp/commit/b87ca7225456b06b0975b8239c66b5aecf07e37c),
seven commits beyond release `prism-b10787-73bfe6c`.
Those commits include faster grammar cloning, handling for malformed UTF-8,
and fixes for some schema-generator inputs.

The source build compiles the server, CPU code, and common libraries, then reuses the
release's GPU plugin. The seven later commits do not change GPU code or the backend ABI.
Both runtime versions are available for comparison. The [grammar measurements](benchmarks/measurements/grammar.json)
record the CPU benchmark below.

On this CPU, cloning a synthetic 107-tool grammar 100 times averaged
1.271 ms per clone in the release and 0.089 ms in the source build, about 14 times faster.
The 14-fold speedup applies only to CPU grammar cloning, not to an entire agent task.
The relevant [upstream change](https://github.com/PrismML-Eng/llama.cpp/commit/a75f770c2a09ba0764e3373d688c4585db879d6d)
replaces a linear rule search during cloning with a binary search.

The server returns reasoning separately from the answer as `reasoning_content`.
The `#27b` profile defaults to a 2048-token reasoning budget. The other profiles default
to 1024 tokens. The published thinking-enabled measurements predate that increase and
used a 1024-token budget. At the budget, the runtime injects a short transition to the
answer or next tool call. Forced 64-token budget checks returned a clean final answer
for both models. The returned `reasoning_content` includes the transition text, so its
token count can exceed the budget.

The 27B profiles map unsupported reasoning-effort values to `medium`, so clients can
send `high` without triggering the model template's error. Clients can request different
budgets. Manual checks of `#9b` and `#27b` confirmed all 34 layers on the GPU for 9B
and all 65 for 27B. The checks also verified the expected context capacities and arithmetic.
The 9B web UI check and the image-color request also passed.

## Other tuning options

| Option | Finding |
| --- | --- |
| CPU threads 1, 2, 4, 6, 12 | One thread slowed 27B. Thread counts above six gave no clear gain in the short screening runs. |
| `GGML_CUDA_GRAPH_OPT=1` | This setting slowed the sampled runs, so the profiles leave it off. |
| Disabling HIP graphs | The short tests found no clear improvement. |
| Q8 prefill F16 staging | The 27B screening test was slower, so the profiles leave this option off. |
| Hadamard and GDN fusions | The release already enables these fusions, and the profiles retain them. |
| Newer fork GPU changes | The seven post-release commits used here contain no GPU changes. |
| Open RDNA4 kernel work | This work targets different hardware and older quantization paths. The RDNA2 profiles do not include it. |
| CPU offload | CPU offload is a capacity fallback, not a fast-decode option. Manual checks verify all-GPU placement for `#9b` and `#27b`. |
| NUMA and PCIe tuning | The system has one NUMA node and an active PCIe 4.0 x16 link. The tests required no configuration change. |
| Clocks and power limits | The firmware cap was already at its exposed maximum. Host clocks and power limits stayed unchanged. |
| Shorter prompts and fewer tool schemas | Shorter prompts and fewer tool schemas can help clients. The server does not rewrite agent prompts. |
| GPU vision encoding | The tests did not tune vision encoding. The projector stays on the CPU to reserve VRAM for coding context. |
| Concurrent-batch throughput | The profiles favor interactive latency and one-session cache reuse over concurrent-batch throughput. |

The measurements do not cover an exhaustive shader-toggle sweep, source builds with different compiler kernels,
larger multi-request throughput sweeps, or full coding-quality evaluations.

See the [benchmark guide](benchmarks/README.md) to repeat the agent, HTTP, inference,
and grammar measurements.
