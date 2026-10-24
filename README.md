# Bonsai Buddy

Run Prism's Bonsai 2 9B and 27B models with Nix. Each profile starts a foreground
server with a web UI and an OpenAI-compatible Chat Completions API.

The defaults target coding agents on a Radeon RX 6700 with 10 GB of VRAM.
They combine ROCm, prompt caching, and a pinned Prism runtime with faster tool-grammar
handling. The `#9b` profile also uses multi-token prediction, or MTP, to accelerate
generation.

## Measured improvements

On the RX 6700, the tuned profiles completed a synthetic coding task faster than
the initial Vulkan configurations:

| Model and profile | Baseline time | Tuned time | Speedup | Baseline to tuned context |
| --- | ---: | ---: | ---: | ---: |
| 9B, `#9b` | 21.91 s | 7.05 s | 3.1× | 8K to 64K |
| 27B, `#27b` | 45.29 s | 22.70 s | 2.0× | 8K to 16K |

Each result comes from one run of a small coding task with greedy sampling and
thinking disabled. The timings exclude model loading. The task uses about 3500 tokens
of source code. The context column shows configured capacity, not the amount of context
used in the test.

The thinking-enabled benchmarks used a 1024-token reasoning budget. Thinking can
change the number of tool calls and total latency. These measurements describe
latency on one machine, not general coding quality. The `#27b` profile passed three
thinking-enabled runs in 32.0 to 65.2 s, with a median of 34.3 s.

See the [performance report](PERFORMANCE.md) for test conditions and more measurements.
The [agent measurement records](benchmarks/measurements/agent.json) contain per-turn timings.

## Run a model

Use x86_64 Linux with Nix and flakes enabled. The ROCm profiles require access to the
AMD GPU through the host driver. Tests ran on NixOS with 32 GB of RAM and a Ryzen 5 5600X.
The source runtime requires AVX2, FMA, and F16C.

From the repository root, choose one model:

```sh
nix run .#9b
```

```sh
nix run .#27b
```

Open [the web UI](http://localhost:8080). Press Ctrl+C to stop the server.
Running `nix run` without an app selects `#9b`. Run only one model at a time on the
tested 10 GB GPU.

The first run builds the server and web UI, then downloads and verifies the model
files. Later runs reuse the Nix store and model cache. The launcher runs in your
terminal and requires no system service.

## Connect an agent

Open a client with the matching model and context settings:

```sh
nix run .#opencode-9b
nix run .#opencode-27b
```

Each command starts the model if the port is free, then opens the client. It stops a
server it started when you exit. See [client launchers](docs/clients.md) for reuse,
compaction, and commands from another project directory.

Set your client's base URL to `http://localhost:8080/v1`. Set its model to
`bonsai2:9b` or `bonsai2:27b`. Match the client's context limit to the profile you run.
Enable history compaction.

The `#9b` profile provides 64K context and an 8192-token output limit. The `#27b`
profile provides 16K context and a 4096-token output limit. The reasoning budget
uses 1024 tokens for 9B and 2048 for 27B. At the budget, the runtime adds a short
transition before the answer or next tool call. The client's output limit must cover
reasoning and the answer or tool call.
Clients can override generation settings per request.

The ROCm runtime sets `HSA_OVERRIDE_GFX_VERSION=10.3.0` unless the variable is already set.

See the [configuration reference](docs/configuration.md) for all profiles, cache paths,
environment variables, Vulkan alternatives, and settings for other GPUs.

## Develop and benchmark

Run the automated checks:

```sh
nix flake check
```

Follow [the benchmark guide](benchmarks/README.md) to measure inference or run the
simulated agent task. The Python tools use only the standard library.

## License and upstream projects

The [MIT license](LICENSE) covers the launcher, Nix definitions, benchmark tools,
and documentation.
The runtime comes from [Prism's llama.cpp fork](https://github.com/PrismML-Eng/llama.cpp).
Model weights come from Prism's [9B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-9B-gguf)
and [27B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf) repositories.
Runtime dependencies and model weights retain their upstream licenses.
