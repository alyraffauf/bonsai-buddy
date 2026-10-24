# Run Bonsai 2 locally

From any directory, run:

```sh
nix run /home/aly/src/bonsaid
```

Open http://localhost:8080. Press Ctrl+C in the terminal to stop the server.

The flake runs Bonsai 2 27B with Prism's Vulkan runtime on x86_64 Linux.
It starts a foreground process without installing a service or changing Ollama.
The OpenAI-compatible API is at http://localhost:8080/v1, with model name `bonsai2:27b`.

The first run downloads and verifies about 6.6 GB of model files into
`${XDG_CACHE_HOME:-$HOME/.cache}/bonsaid/models`. Later runs reuse those files.
Set `BONSAI_MODELS_DIR` to use another model directory.

To change the port or context size, set `BONSAI_PORT` or `BONSAI_CTX`.
The defaults are port 8080 and 8192 context tokens. Extra arguments pass to llama-server:

```sh
nix run /home/aly/src/bonsaid -- --port 8081
```

The vision projector runs on the CPU to save VRAM. Large images are downscaled
to 1024 vision tokens. Pass `--image-max-tokens 4096` for more image detail.

Runtime source: [Prism's pinned release](https://github.com/PrismML-Eng/llama.cpp/releases/tag/prism-b10787-73bfe6c).
Model source: [Bonsai 2 27B GGUF](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf).
