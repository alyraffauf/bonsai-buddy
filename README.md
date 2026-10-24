# Bonsai Buddy

Run Prism's Bonsai 2 models with Nix, a local web UI, and a Chat Completions API.
The defaults target coding agents on the Radeon RX 6700 with 10 GB of VRAM.
9B uses multi-token prediction to accelerate generation.

## Run

Use x86_64 Linux with Nix, flakes, and access to the AMD GPU. The source runtime
requires AVX2, FMA, and F16C. Choose one command:

| Model | Context | Server | OpenCode |
| --- | ---: | --- | --- |
| 9B | 128K | `nix run github:alyraffauf/bonsai-buddy#9b` | `nix run github:alyraffauf/bonsai-buddy#opencode-9b` |
| 27B | 16K | `nix run github:alyraffauf/bonsai-buddy#27b` | `nix run github:alyraffauf/bonsai-buddy#opencode-27b` |

Open the [web UI](http://localhost:8080). Ctrl+C stops the server. The first run
builds the runtime and downloads verified weights; later runs reuse the cache.
Run one GPU model at a time. From a checkout, use `nix run .#9b` or the other
profile names above. `nix run` selects 9B.

Downloads for the default profiles are about 3.3 GB for 9B and 7.8 GB for 27B,
including the vision projector. The runtime build needs additional disk space.

OpenCode starts a server when needed and stops servers it owns on exit.
See [client limits](docs/clients.md) for compaction and server reuse.

Other clients use `http://localhost:8080/v1`, with model alias `bonsai2:9b` or
`bonsai2:27b`. See [configuration](docs/configuration.md) for budgets, overrides,
Vulkan profiles, and the card-specific ROCm override.

## Measured results

| Model | Original Vulkan | Tuned ROCm | Speedup | Context change |
| --- | ---: | ---: | ---: | --- |
| 9B | 21.91 s | 7.64 s | 2.9× | 8K to 128K |
| 27B | 45.29 s | 21.77 s | 2.1× | 8K to 16K |

Each figure is one synthetic coding-task run with thinking disabled. The task uses
about 3500 source tokens; timings exclude startup. These results measure latency
on one machine, not general coding quality. Thinking-enabled runs also passed.

The [performance report](PERFORMANCE.md) includes methods, context tradeoffs,
kernel findings, and JSON records. Use the [benchmark guide](benchmarks/README.md)
to repeat the tests. Run `nix flake check` for Ruff, ty, and regression tests.
See [contributing](CONTRIBUTING.md) for development checks.

## License

[MIT](LICENSE) covers this repository. The [Prism runtime](https://github.com/PrismML-Eng/llama.cpp/blob/b87ca7225456b06b0975b8239c66b5aecf07e37c/LICENSE)
is also MIT-licensed. The
[9B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-9B-gguf/blob/5b2abb02362efbed46bbe204014b02837778b2c2/LICENSE)
and [27B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf/blob/b072e1d3b35a0a630cece372c2127528e0994386/LICENSE)
weights use Apache-2.0. Weights are downloaded separately.
See [upstream notices](NOTICE) for the kernel experiments.
