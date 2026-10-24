# Repeat the benchmarks

Run these commands from `~/src/bonsaid` with other GPU models stopped.
Model files must already be in `~/.cache/bonsaid/models`.
Raw outputs belong in `benchmarks/results/`, which Git ignores.

To measure plain inference, run:

```sh
mkdir -p benchmarks/results
nix run .#bench -- \
	-m ~/.cache/bonsaid/models/Ternary-Bonsai-2-9B-PQ2_0.gguf \
	-p 512 -n 128 -b 2048 -ub 512 -fa on -ngl 99 -r 3 -o json \
	> benchmarks/results/9b-repeat.json
```

Use `#bench-vulkan` for Vulkan or `#bench-rocm-release` for the original HIP release.
`llama-bench` excludes tokenization, sampling, chat templating, and tool parsing.
Use the HTTP benchmarks for end-to-end generation and speculative decoding.

To repeat a read/edit/test loop through the actual flake defaults, run:

```sh
nix develop -c python3 benchmarks/agent.py --flake . --case 9b --case 27b
```

The test uses an in-memory Python file and simulated tools. It does not execute
model-generated code or modify your source files. A successful result prints `PASSED`.
The command above disables thinking for a controlled speed comparison. To test the
shipped thinking defaults and preserve reasoning in subsequent requests, run:

```sh
nix develop -c python3 benchmarks/agent.py --flake . \
	--thinking --preserve-reasoning --case 9b --case 27b \
	--output benchmarks/results/agent-thinking
```

Omit `--preserve-reasoning` to compare a client that discards previous reasoning.

To compare raw speculative modes with identical HTTP workloads, run:

```sh
runtime=$(nix build .#runtime-source --no-link --print-out-paths)
nix develop -c python3 benchmarks/server.py \
	--server "$runtime/bin/llama-server" \
	--case 9b-plain --case 9b-mtp1 --case 9b-dflash
```

To measure long-prefix reuse, add `--checkpoints 32 --cache-ram 1024 --cache-prompt`
and set `--code-functions 128`. Compare `cache_n`, `prompt_n`, and `prompt_ms`
between the first and second requests. Cold and cached token rates are different measurements.

To repeat the grammar-cloning test, enter the dev shell:

```sh
nix develop
```

Generate the grammar, compile the benchmark, and compare both libraries:

```sh
mkdir -p benchmarks/results
prism_source=$(nix eval --raw .#packages.x86_64-linux.runtime-source.src.outPath)
python3 benchmarks/grammar_schema.py > benchmarks/results/grammar-schema.json
python3 "$prism_source/examples/json_schema_to_grammar.py" \
	benchmarks/results/grammar-schema.json > benchmarks/results/grammar.gbnf
c++ -O2 -std=c++17 benchmarks/grammar.cpp -I"$BONSAID_INCLUDE" \
	-L"$BONSAID_RELEASE_LIB" -Wl,-rpath,"$BONSAID_RELEASE_LIB" \
	-l:libllama.so.0 -o benchmarks/results/grammar-bench
benchmarks/results/grammar-bench \
	~/.cache/bonsaid/models/Ternary-Bonsai-2-9B-PQ2_0.gguf \
	benchmarks/results/grammar.gbnf
LD_LIBRARY_PATH="$BONSAID_SOURCE_LIB" benchmarks/results/grammar-bench \
	~/.cache/bonsaid/models/Ternary-Bonsai-2-9B-PQ2_0.gguf \
	benchmarks/results/grammar.gbnf
```

The output reports milliseconds per clone. Exit the shell when finished.

`benchmarks/results/` contains the local experiment records from this tuning session.
The top-level [performance report](../PERFORMANCE.md) describes which figures are comparable.
