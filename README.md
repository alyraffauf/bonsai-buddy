# Run Bonsai 2 locally

Choose a model from any directory:

```sh
nix run /home/aly/src/bonsaid#9b
nix run /home/aly/src/bonsaid#27b
```

Open http://localhost:8080. Press Ctrl+C in the terminal to stop the server.

Running `nix run /home/aly/src/bonsaid` selects 9B by default.
The flake uses Prism's Vulkan runtime on x86_64 Linux, with PQ2_0 for 9B and PTQ1_0 for 27B.
It starts a foreground process without installing a service or changing Ollama.
The OpenAI-compatible API is at http://localhost:8080/v1.
Use model name `bonsai2:9b` or `bonsai2:27b`, matching the selected app.

The first run downloads and verifies the selected model into
`${XDG_CACHE_HOME:-$HOME/.cache}/bonsaid/models`. The 9B files total about 3.0 GB,
and the 27B files total about 6.6 GB. Later runs reuse those files.
Set `BONSAI_MODELS_DIR` to use another model directory.

To change the port or context size, set `BONSAI_PORT` or `BONSAI_CTX`.
The defaults are port 8080 and 8192 context tokens. To use a different port, run:

```sh
BONSAI_PORT=8081 nix run /home/aly/src/bonsaid#27b
```

Arguments after `--` pass to llama-server.

The vision projector runs on the CPU to save VRAM. Large images are downscaled
to 1024 vision tokens. Pass `--image-max-tokens 4096` for more image detail.

Runtime source: [Prism's pinned release](https://github.com/PrismML-Eng/llama.cpp/releases/tag/prism-b10787-73bfe6c).
Model sources: [Bonsai 2 9B GGUF](https://huggingface.co/prism-ml/Ternary-Bonsai-2-9B-gguf),
[Bonsai 2 27B GGUF](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf).
