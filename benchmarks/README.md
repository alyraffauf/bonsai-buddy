# Run benchmarks

Stop other GPU models. Run commands from the checkout. Cache each required model by
starting its profile once, waiting until ready, and pressing Ctrl+C.

Results go to the ignored `benchmarks/results/` directory. Failed cases exit nonzero.
Model paths follow the [cache settings](../docs/configuration.md#model-cache).
`agent.py` and `server.py` also accept `--models DIRECTORY`.

## Measure plain inference

Cache `#9b-plain`, then run:

```sh
models_dir=${BONSAI_BUDDY_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsai-buddy/models}
mkdir -p benchmarks/results
nix run .#bench -- \
	-m "$models_dir/Ternary-Bonsai-2-9B-PQ2_0.gguf" \
	-p 512 -n 128 -b 2048 -ub 512 -fa on -ngl 99 -r 3 -o json \
	> benchmarks/results/9b-repeat.json
```

Use `#bench-vulkan` or `#bench-rocm-release` for backend comparisons. This test excludes
sampling and HTTP overhead. [GPU profiling](../docs/profiling.md) measures individual kernels.

## Run a coding-agent loop

```sh
nix develop -c python3 benchmarks/agent.py --flake . \
	--thinking --preserve-reasoning --case 9b --case 27b \
	--output benchmarks/results/agent-thinking
```

Omit `--thinking --preserve-reasoning` for the greedy baseline. The thinking test caps
output at 4096 tokens per request. Simulated tools edit an in-memory Python file;
AST checks enforce the fix, preserved helpers, and tests after the last edit.
The runner allows eight turns and prints `PASSED` on success. Its default port is 18083.
Add `--warmup` to measure a warm server. The separate warmup duration stays in the result.

For the original Vulkan baseline, cache `#9b-plain` and `#27b-vulkan`:

```sh
runtime=$(nix build .#runtime --no-link --print-out-paths)
nix develop -c python3 benchmarks/agent.py \
	--server "$runtime/bin/llama-server" --case 9b-plain --case 27b-ptq \
	--context 8192 --batch-size 256 --ubatch-size 128 \
	--output benchmarks/results/agent-vulkan
```

## Check context

```sh
nix develop -c python3 benchmarks/context.py --case 9b \
	--context 131072 --prompt-tokens 70000 --output benchmarks/results/context-9b
nix develop -c python3 benchmarks/context.py --case 27b \
	--context 16384 --prompt-tokens 14000 --output benchmarks/results/context-27b
```

The test retrieves three literals across a synthetic module through a constrained
tool call. It checks the allocated context and exact values, not general coding quality.

## Compare speculative decoding

Cache `#9b-plain`, `#9b`, and `#9b-rewrite`:

```sh
runtime=$(nix build .#runtime-source --no-link --print-out-paths)
nix develop -c python3 benchmarks/server.py \
	--server "$runtime/bin/llama-server" \
	--case 9b-plain --case 9b-mtp1 --case 9b-dflash
```

These raw-runtime cases use 8K context and port 18082. Add
`--checkpoints 32 --cache-ram 1024 --cache-prompt --code-functions 128` to test prefix
reuse. Compare `cache_n`, `prompt_n`, and `prompt_ms` across repetitions.

## Check transcript reuse

```sh
nix develop -c python3 benchmarks/cache.py --case 9b --case 27b
```

This seeded tool conversation compares stable history, removed reasoning, changed
argument formatting, reordered keys, and cache misses. The RAM prompt store is
disabled to isolate the live prefix. Add `--continuation user` to test a new user turn.

For real-weight matvec sweeps and full-vocabulary comparisons, see
[PQ2 kernel experiments](../docs/profiling.md#test-pq2-matvecs).

## Compare grammar cloning

Cache `#9b-plain`, then compile and compare both libraries:

```sh
nix develop -c bash <<'SH'
set -euo pipefail
models_dir=${BONSAI_BUDDY_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsai-buddy/models}
mkdir -p benchmarks/results
prism_source=$(nix eval --raw .#packages.x86_64-linux.runtime-source.src.outPath)
python3 benchmarks/grammar_schema.py > benchmarks/results/grammar-schema.json
python3 "$prism_source/examples/json_schema_to_grammar.py" \
	benchmarks/results/grammar-schema.json > benchmarks/results/grammar.gbnf
c++ -O2 -std=c++17 benchmarks/grammar.cpp -I"$BONSAI_BUDDY_INCLUDE" \
	-L"$BONSAI_BUDDY_RELEASE_LIB" -Wl,-rpath,"$BONSAI_BUDDY_RELEASE_LIB" \
	-l:libllama.so.0 -o benchmarks/results/grammar-bench
benchmarks/results/grammar-bench \
	"$models_dir/Ternary-Bonsai-2-9B-PQ2_0.gguf" benchmarks/results/grammar.gbnf
LD_LIBRARY_PATH="$BONSAI_BUDDY_SOURCE_LIB" benchmarks/results/grammar-bench \
	"$models_dir/Ternary-Bonsai-2-9B-PQ2_0.gguf" benchmarks/results/grammar.gbnf
SH
```

The output reports milliseconds per clone.

## Checks and records

`nix flake check` runs Ruff, ty, and regression tests. The
[performance report](../PERFORMANCE.md) links published JSON records and explains
which measurements are comparable. New runs leave those records unchanged.
