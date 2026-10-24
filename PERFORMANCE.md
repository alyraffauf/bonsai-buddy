# RX 6700 performance

Measurements from 2026-10-23 and 2026-10-24 used a Radeon RX 6700, Ryzen 5 5600X,
32 GB RAM, and PCIe 4.0 x16 on NixOS. Agent timings exclude startup. Each agent
result is one small synthetic task, not a general coding-quality evaluation.

## Coding-agent latency

The task reads about 3500 source tokens, fixes `add`, preserves helper functions,
and runs simulated tests. AST checks enforce the edit and tool order.

| Model | Original Vulkan, 8K | Current ROCm | Current capacity | Speedup |
| --- | ---: | ---: | ---: | ---: |
| 9B | 21.91 s | 7.64 s | 128K | 2.9× |
| 27B | 45.29 s | 21.77 s | 16K | 2.1× |

Both greedy runs passed. Thinking-enabled runs with preserved reasoning also passed:
12.11 s for 9B and 53.99 s for 27B. Their reasoning budgets were 1024 and 2048
tokens; the thinking test allowed 4096 total output tokens per request.

[Current records](benchmarks/measurements/agent-current.json) include each tool turn.
[Earlier records](benchmarks/measurements/agent.json) preserve the initial tuning runs.

## Larger context tests

9B keeps F16 KV at 128K. The 27B default returns to PQ2/Q8 at 16K: the 64K PTQ/Q4
configuration took 39.27 s on the coding task, versus 21.77 s after restoration.

| Capacity experiment | Prompt tokens | Cold prefill tokens/s | Generation tokens/s |
| --- | ---: | ---: | ---: |
| 9B, 128K F16, 512 MiB reserve | 69935 | 514.8 | 46.5 |
| 9B, 128K F16, 256 MiB reserve | 69935 | 536.9 | 33.2 |
| 27B, 64K PTQ/Q4 | 54923 | 125.5 | 9.1 |

Each recovered three route codes across a synthetic Python module in one constrained
tool call. Each generated 75 tokens without thinking or prompt-cache reuse. These are
retrieval checks; changing desktop VRAM and short samples limit speed comparisons.

The 64K 27B request needed 437.68 s of cold prefill. Its Q4 cache used 1152 MiB.
PTQ reduced the GPU weight buffer by about 1144 MiB, but slower prefill outweighed
that capacity benefit for the default. Q4 can also change model output.

Automatic fitting can move transformer blocks to the CPU and disable GDN fusions.
All 27B layers fit during the 64K test; the first 9B run used 31 of 34 GPU layers.
A smaller reserve enabled full placement without a consistent generation-speed gain.

The [capacity records](benchmarks/measurements/context.json) also cover mixed caches,
CPU output projection, mean-centering, and 256K allocation probes. The restored 16K 27B preset also passed a 14221-token retrieval check. Allocation
and arithmetic checks alone do not validate long-history retrieval.

## Speculative decoding

These earlier 8K HTTP tests used greedy sampling, 192 output tokens, and two
repetitions. Rates exclude prefill.

| 9B mode | Explanation tokens/s | Code-edit tokens/s |
| --- | ---: | ---: |
| Plain PQ2 | 83.2 | 82.5 |
| Plain PTQ | 86.2 | 85.8 |
| MTP depth 1 | 95.5 | 113.0 |
| MTP depth 2 | 81.3 | 110.2 |
| MTP depth 4 | 59.5 | 117.6 |
| DFlash2, draft length 16 | 49.5 | 162.6 |

MTP depth 1 balanced prose and edits. DFlash2 favored repetitive rewrites but slowed
cold prompts and the agent task. N-gram modes gave no consistent gain; a separate
2B drafter slowed 27B to roughly 9 to 13 tokens/s.

## Prefix reuse

A repeated 3532-token code request reused 3528 tokens at 8K capacity, with one slot,
32 checkpoints, a 1 GiB host cache, batch 1024, microbatch 256, and F16 KV.

| Mode | Cold prefill | Cached prefill |
| --- | ---: | ---: |
| 9B plain | 4.15 s | 27 ms |
| 9B MTP | 4.34 s | 30 ms |
| 9B DFlash2 | 8.84 s | 38 ms |
| 27B PQ2 | 14.29 s | 80 ms |

All profiles enable prompt caching. Stable system prompts, tool order, and preserved
reasoning help retain prefixes. One slot queues concurrent sessions.
The [HTTP records](benchmarks/measurements/http.json) contain individual requests.

A seeded tool conversation also tested history changes at the default capacities.
Two reversed-order repeats disabled the RAM prompt store and measured newly processed tokens:

| Model | Stable history | Reasoning removed | Argument keys reordered |
| --- | ---: | ---: | ---: |
| 9B | 18 to 19 | 3680 | 3745 |
| 27B | 19 | 3712 | 3749 |

Whitespace-only argument changes retained the prefix. Within a tool loop, preserve
reasoning and argument order. For a new user turn, 9B's template drops earlier
reasoning. Desktop VRAM forced partial CPU offload during these tests; compare token
work, not absolute throughput. [Cache records](benchmarks/measurements/cache.json) include every repeat.

## Kernel profiling

These PQ2 captures used ROCm 7.2.3, with F16 KV for 9B and Q8 for 27B.
Percentages describe selected GPU kernel durations, not request latency.

| Workload | Active prefix | PQ2 matrix kernels | Flash attention | GDN |
| --- | ---: | ---: | ---: | ---: |
| 9B prefill | 0 | 78.0% | 2.4% | 8.0% |
| 27B prefill | 0 | 82.8% | 1.6% | 5.6% |
| 9B plain decode | 2048 | 74.7% | 3.2% | 2.6% |
| 27B plain decode | 2048 | 79.0% | 6.1% | 2.4% |
| 9B plain decode | 32768 | 55.8% | 27.3% | 1.9% |
| 27B plain decode | 8192 | 69.0% | 17.9% | 2.1% |

Prefill processed 2048 tokens. Summaries exclude initialization and warmup. Matrix
operations dominate short-context work; attention takes more time as history grows.
Sampled prefill dispatches used 248 vector registers and reported 23% to 25% occupancy.
These few counter samples do not establish workload-wide occupancy or bandwidth.

Tracing slowed 9B decode from 81.3 to 18.5 tokens/s and 27B from 24.9 to 9.0.
Trace gaps therefore do not prove equivalent stalls during normal inference.
The [kernel records](benchmarks/measurements/kernels.json) include dispatch summaries,
counters, and unprofiled controls. See the [profiling guide](docs/profiling.md).

## PQ2 matvec experiments

Untraced stream reads reached about 315 to 317 GB/s with 1 and 2 GiB buffers.
A sweep tested 468 kernel configurations across 12 real tensors, with six timing
pairs each. Grouping four rows sped up large three-token PQ2 calls by roughly
1.3× to 2.1×. The smallest attention projections regressed and need the original kernel.

Selected row grouping preserved all 47,677,440 captured logits per model.
In an 8K HTTP ABBA test, 9B MTP generation rose from 101.5 to 105.6 tokens/s on
prose and 115.1 to 120.0 on code, about 4%. Text and acceptance counts matched.
The 27B single-token candidate gave no reliable gain. All 20 coding tasks passed,
but intermittent stalls obscured latency gains, including after warmup. These are
experimental kernels; the profiles keep the released HIP plugin.
[Matvec records](benchmarks/measurements/matvec.json)
contain all kernel pairs, logit hashes, HTTP samples, and coding-task repeats.

## Tuning decisions

| Test | Finding |
| --- | --- |
| ROCm vs Vulkan | Earlier plain 9B generation rose from about 43 to 83 tokens/s. |
| 27B packing | PQ2 prefill reached 277 tokens/s versus 152 for PTQ on the 512-token test. |
| Smaller PQ2 tiles | Rebuilt 9B prefill fell from 960.4 to 905.1, 820.4, or 601.2 tokens/s. |
| Long-history 9B KV | At 32K, F16 decoded at 64.0 tokens/s versus 44.8 for Q8. |
| Graph optimization, Q8 F16 staging | Screening runs slowed; defaults leave these switches off. |
| CPU threads | One thread hurt 27B; counts above six gave no clear gain. |

The source runtime pins `b87ca7225` and reuses the release HIP plugin. Its seven
post-release commits contain no GPU changes. Grammar cloning fell from 1.271 to
0.089 ms per clone in a 107-tool test, about 14× faster for that CPU operation.

[Inference records](benchmarks/measurements/inference.json) and
[grammar records](benchmarks/measurements/grammar.json) preserve parameters and samples.
Host clocks and power limits stayed unchanged. Tests do not cover broad coding quality
or an exhaustive compiler and shader sweep. See [reproduction commands](benchmarks/README.md).
