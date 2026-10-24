# Run the benchmarks

Run these commands from the repository root with other GPU models stopped.
Build the required profiles and populate the model cache first: start each profile
with `nix run .#PROFILE`, wait until it is ready, then stop it with Ctrl+C.

The tools use `BONSAI_MODELS_DIR`, then `$XDG_CACHE_HOME/bonsaid/models`, then
`$HOME/.cache/bonsaid/models`. `--models DIRECTORY` overrides that path for a benchmark.
New logs and responses go to `benchmarks/results/`, which Git ignores.
Failed benchmarks exit with a nonzero status and include an `error` in their JSON record.

## Measure plain inference

Cache the `#9b-plain` model before this test. Set the path and run `llama-bench`:

```sh
models_dir=${BONSAI_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsaid/models}
mkdir -p benchmarks/results
nix run .#bench -- \
	-m "$models_dir/Ternary-Bonsai-2-9B-PQ2_0.gguf" \
	-p 512 -n 128 -b 2048 -ub 512 -fa on -ngl 99 -r 3 -o json \
	> benchmarks/results/9b-repeat.json
```

Use `#bench-vulkan` for Vulkan or `#bench-rocm-release` for the pinned HIP release.
`llama-bench` excludes tokenization, sampling, chat templating, and tool parsing.
Use the HTTP tests below for generation through the API and speculative decoding.

## Run a coding-agent loop

Cache the `#9b` and `#27b` models. To test the shipped thinking defaults and preserve
reasoning in subsequent requests, run:

```sh
nix develop -c python3 benchmarks/agent.py --flake . \
	--thinking --preserve-reasoning --case 9b --case 27b \
	--output benchmarks/results/agent-thinking
```

To measure greedy generation with thinking disabled, run:

```sh
nix develop -c python3 benchmarks/agent.py --flake . --case 9b --case 27b
```

The test uses an in-memory Python file and simulated tools. It parses the resulting
code without executing it or modifying your source files. A pass requires reading
the file, fixing `add`, preserving the helper functions, and testing after the last edit.
The task allows eight turns. A successful run prints `PASSED`.

Omit `--preserve-reasoning` to compare a client that discards previous reasoning.
The default port is 18083. Use `--port` to select another free port.

## Compare speculative decoding

Cache the `#9b-plain`, `#9b`, and `#9b-rewrite` models, then run:

```sh
runtime=$(nix build .#runtime-source --no-link --print-out-paths)
nix develop -c python3 benchmarks/server.py \
	--server "$runtime/bin/llama-server" \
	--case 9b-plain --case 9b-mtp1 --case 9b-dflash
```

This test uses an 8K context, greedy sampling, and two repetitions per workload.
The default port is 18082. `--help` lists options for context, output length, caching,
and KV precision. The raw-runtime cases use names such as `9b-mtp1` and `27b-ptq`;
the agent test's `--flake` mode uses app names such as `9b` and `27b`.

To measure long-prefix reuse, add `--checkpoints 32 --cache-ram 1024 --cache-prompt`
and `--code-functions 128`. Compare `cache_n`, `prompt_n`, and `prompt_ms` between the
first and second requests. Cold and cached prefill are separate measurements.

## Compare grammar cloning

Cache the `#9b-plain` model, then enter the dev shell:

```sh
nix develop
```

Generate the grammar, compile the benchmark, and compare both libraries:

```sh
models_dir=${BONSAI_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsaid/models}
mkdir -p benchmarks/results
prism_source=$(nix eval --raw .#packages.x86_64-linux.runtime-source.src.outPath)
python3 benchmarks/grammar_schema.py > benchmarks/results/grammar-schema.json
python3 "$prism_source/examples/json_schema_to_grammar.py" \
	benchmarks/results/grammar-schema.json > benchmarks/results/grammar.gbnf
c++ -O2 -std=c++17 benchmarks/grammar.cpp -I"$BONSAID_INCLUDE" \
	-L"$BONSAID_RELEASE_LIB" -Wl,-rpath,"$BONSAID_RELEASE_LIB" \
	-l:libllama.so.0 -o benchmarks/results/grammar-bench
benchmarks/results/grammar-bench \
	"$models_dir/Ternary-Bonsai-2-9B-PQ2_0.gguf" benchmarks/results/grammar.gbnf
LD_LIBRARY_PATH="$BONSAID_SOURCE_LIB" benchmarks/results/grammar-bench \
	"$models_dir/Ternary-Bonsai-2-9B-PQ2_0.gguf" benchmarks/results/grammar.gbnf
```

The output reports milliseconds per clone. Exit the shell when finished.

## Check the Python tools

`nix flake check` runs Ruff's formatter and linter, `ty`, and the regression tests.
To run each check directly:

```sh
nix develop -c ruff format --check benchmarks tests
nix develop -c ruff check benchmarks tests
nix develop -c ty check --extra-search-path benchmarks benchmarks tests
nix develop -c env PYTHONPATH=benchmarks python3 -m unittest discover -s tests -v
```

## Published measurements

The [performance report](../PERFORMANCE.md) explains the test conditions and which
figures can be compared. The committed records contain numeric results with local
paths, response text, and process commands removed:

- [Agent loops](measurements/agent.json), including per-turn timings and success checks.
- [HTTP workloads](measurements/http.json), including speculative decoding and prefix reuse.
- [Plain inference](measurements/inference.json), including samples and principal benchmark parameters.
- [Grammar cloning](measurements/grammar.json), including the warmup and measured clone counts.

These files preserve measurements from 2026-10-23. New runs write to the ignored
results directory and do not overwrite the published records.
