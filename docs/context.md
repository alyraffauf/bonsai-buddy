# Context tradeoffs

| Model | Server and OpenCode window | KV cache | OpenCode compaction |
| --- | ---: | --- | ---: |
| 9B | 131072 tokens | F16 | 114688 tokens |
| 27B | 16384 tokens | Q8_0 | 8192 tokens |

Both models declare a native 262144-token window. These defaults balance memory,
speed, and cache precision on the 10 GB RX 6700.

9B retains F16 KV and MTP. At 128K capacity, the target cache uses 4096 MiB and the
draft cache adds 512 MiB. It passed a 69935-token retrieval test.

27B uses PQ2 weights at 16K for faster prefill. The 64K PTQ/Q4 experiment fit, but its
coding task took 39.27 seconds. The restored 16K preset took 21.77 seconds.

The launcher accounts for desktop VRAM and can move layers to the CPU. Moving an
early transformer block can disable GDN fusions. A short conversation costs less
attention work than a filled window; stable prefixes let later turns reuse cached tokens.

The [performance report](../PERFORMANCE.md#larger-context-tests) records the capacity
experiments and their limits. These retrieval checks do not establish general coding
quality. Use the [benchmark guide](../benchmarks/README.md#check-context) to test a workload.

[Memory overrides](configuration.md#environment-variables) also apply when OpenCode
starts the server. Its context, input limit, and compaction threshold adjust together.
