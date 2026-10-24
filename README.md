# bonsaid

Run Prism's Bonsai 2 9B and 27B models with Nix. Each profile starts a foreground
server with a web UI and an OpenAI-compatible API.

The defaults target coding agents on a Radeon RX 6700 with 10 GB of VRAM.
They combine ROCm, prompt caching, and a pinned Prism runtime with faster tool-grammar
handling. The 9B profile also uses multi-token prediction, or MTP, to accelerate generation.

## Measured improvements

On the RX 6700, the tuned profiles completed a synthetic read/edit/test loop faster
than the initial Vulkan configuration:

| Model and profile | Vulkan baseline | Tuned profile | Speedup | Configured context |
| --- | ---: | ---: | ---: | ---: |
| 9B, `#9b` | 21.91 s | 7.05 s | 3.1× | 8K to 64K |
| 27B, `#27b` | 45.29 s | 22.70 s | 2.0× | 8K to 16K |

These are individual runs of a small coding task, with greedy sampling and thinking
disabled. Model loading is excluded. The task uses about 3500 tokens of source code;
the context column describes capacity, not a full-context test.

The shipped defaults keep thinking enabled with a 1024-token budget. Thinking can
change the number of tool calls and total latency. These measurements describe
latency on one machine, not general coding quality. The selected 27B profile passed
three thinking-enabled runs in 32.0 to 65.2 s, with a median of 34.3 s.

See the [performance report](PERFORMANCE.md) for inference rates, cache measurements,
tradeoffs, and the [measurement records](benchmarks/measurements/agent.json).

## Run a model

Use x86_64 Linux with Nix and flakes enabled. The ROCm profiles require access to the
AMD GPU through the host driver. The tested machine has 32 GB of RAM and a Ryzen 5 5600X;
the source runtime requires AVX2, FMA, and F16C.

From the repository root, choose one model:

```sh
nix run .#9b
```

```sh
nix run .#27b
```

Open [the web UI](http://localhost:8080). Press Ctrl+C to stop the server.
Plain `nix run` selects 9B. Run one model at a time on the tested 10 GB GPU.

The first run builds the server and web UI, then downloads and verifies the model
files. Later runs reuse the Nix store and model cache. The launcher runs in your
terminal and requires no system service.

## Connect an agent

Set your client's base URL to `http://localhost:8080/v1` and its model to
`bonsai2:9b` or `bonsai2:27b`. Match the client's context limit to the selected profile
and enable history compaction.

The main profiles provide 64K context for 9B and 16K for 27B, with an 8192-token output
limit. Thinking uses at most 1024 generated tokens by default, followed by a short
transition to the answer or next tool call. Leave room for both in the client's output limit.
Clients can override generation settings per request.

The default ROCm override is `HSA_OVERRIDE_GFX_VERSION=10.3.0`. To supply another value,
set the standard ROCm variable when you run the model:

```sh
HSA_OVERRIDE_GFX_VERSION=10.3.0 nix run .#9b
```

See [configuration](docs/configuration.md) for all profiles, cache paths, environment
variables, Vulkan alternatives, and settings for other GPUs.

## Develop and benchmark

Run the automated checks:

```sh
nix flake check
```

Follow [the benchmark guide](benchmarks/README.md) to measure inference or run the
simulated agent task. The Python tools use only the standard library.

## License and upstream projects

The launcher, Nix definitions, benchmark tools, and documentation use the [MIT license](LICENSE).
The runtime comes from [Prism's llama.cpp fork](https://github.com/PrismML-Eng/llama.cpp).
Model weights come from Prism's [9B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-9B-gguf)
and [27B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf) repositories.
Runtime dependencies and model weights retain their upstream licenses.
