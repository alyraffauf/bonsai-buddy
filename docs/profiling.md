# Profile GPU kernels

Stop other GPU models and run from the checkout. Cache `#9b-plain`, `#9b`, and `#27b`
as needed. These commands reproduce the PQ2 captures in the [performance report](../PERFORMANCE.md#kernel-profiling).

The profiling shell supplies ROCm 7.2.3 and decode markers. Commands preserve an
explicit HSA override; otherwise they use `10.3.0` for the tested RX 6700.

## Test PQ2 matvecs

These gfx1030 probes compare the released HIP kernel with different block sizes,
row grouping, loop unrolling, and Prism's planar PQ2 kernel. Each reports numerical
differences and six timing pairs over rotating real weights. Defaults stay unchanged.

```sh
export HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION-10.3.0}
models_dir=${BONSAI_BUDDY_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsai-buddy/models}
probe=$(nix build --impure --file benchmarks/matvec.nix \
	--argstr repository "$PWD" --no-link --print-out-paths)
"$probe/bin/bonsai-matvec-probe" bandwidth
"$probe/bin/bonsai-matvec-probe" \
	"$models_dir/Ternary-Bonsai-2-9B-PQ2_0.gguf" blk.0.ffn_down.weight 6
```

Pass only a model filename to list its PQ2 and Q8 tensors. Output is JSON Lines
for measurements and plain text for tensor listings. Weights rotate over at least
512 MiB. Reported GB/s counts weight bytes; it is not a DRAM counter.

To compare all logits under one-, two-, and three-token decode batches:

```sh
runtime=$(nix build .#runtime-source --no-link --print-out-paths)
experiment=$(nix build --impure --file benchmarks/matvec.nix \
	--argstr repository "$PWD" --arg interpose true --no-link --print-out-paths)
logits=$(nix build --impure --file benchmarks/logits.nix \
	--argstr repository "$PWD" --no-link --print-out-paths)
mkdir -p benchmarks/results
model="$models_dir/Ternary-Bonsai-2-9B-PQ2_0-MTP-Q8_0.gguf"
"$logits/bin/bonsai-logits" "$model" "$runtime/bin" benchmarks/task.py \
	benchmarks/results/baseline.f32 f16
LD_PRELOAD="$experiment/lib/libbonsai-matvec.so" \
	"$logits/bin/bonsai-logits" "$model" "$runtime/bin" benchmarks/task.py \
	benchmarks/results/rows.f32 f16
cmp benchmarks/results/baseline.f32 benchmarks/results/rows.f32
```

The capture writes 192 full-vocabulary rows after 256 prompt tokens. For HTTP tests,
pass `"$experiment/bin/bonsai-matvec-server"` to `server.py` or `agent.py` with `--server`.
`BONSAI_BUDDY_MATVEC_SINGLE=1` also tests row grouping on small single-token projections.
The wrapper prints captured call counts on exit. No profile loads this library.

## Capture prefill and decode separately

```sh
nix develop .#profiling -c bash <<'SH'
set -euo pipefail
export HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION-10.3.0}
models_dir=${BONSAI_BUDDY_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsai-buddy/models}
mkdir -p benchmarks/results
results=$(mktemp -d benchmarks/results/kernels.XXXXXX)
printf 'Traces: %s\n' "$results"

for size in 9B 27B; do
	batch=2048; microbatch=512; kv=f16
	if [ "$size" = 27B ]; then
		batch=1024; microbatch=256; kv=q8_0
	fi
	for stage in prefill decode; do
		prompt=2048; generation=0; depth=0; tokens=$batch; calls=$((2048 / batch))
		if [ "$stage" = decode ]; then
			prompt=0; generation=64; depth=2048; tokens=1; calls=62
		fi
		directory="$results/$size-$stage"
		mkdir -p "$directory"
		rocprofv3 --preload "$BONSAI_BUDDY_KERNEL_MARKERS" \
			--kernel-trace --hip-runtime-trace --marker-trace --memory-copy-trace \
			--stats --output-format csv --output-directory "$directory" \
			-- "$BONSAI_BUDDY_BENCH" \
			-m "$models_dir/Ternary-Bonsai-2-$size-PQ2_0.gguf" \
			-p "$prompt" -n "$generation" -d "$depth" \
			-b "$batch" -ub "$microbatch" -ctk "$kv" -ctv "$kv" \
			-fa on -ngl 99 -r 1 -o json \
			> "$directory/bench.json" 2> "$directory/run.log"
		python3 benchmarks/kernels.py "$directory" \
			--tokens "$tokens" --last-calls "$calls" > "$directory/summary.json"
	done
done
SH
```

Summaries exclude loading, depth prefill, and warmup. Decode retains the last 62 calls.
Use a fresh directory per capture. Raw `llama-bench` runs plain inference with no
automatic memory fitting or MTP. Increase `-d` for longer active prefixes.

## Capture an MTP coding loop

```sh
nix develop .#profiling -c bash <<'SH'
set -euo pipefail
export HSA_OVERRIDE_GFX_VERSION=${HSA_OVERRIDE_GFX_VERSION-10.3.0}
mkdir -p benchmarks/results
export BONSAI_BUDDY_PROFILE_OUTPUT
BONSAI_BUDDY_PROFILE_OUTPUT=$(mktemp -d benchmarks/results/mtp-kernels.XXXXXX)
cat > "$BONSAI_BUDDY_PROFILE_OUTPUT/server" <<'WRAPPER'
#!/usr/bin/env bash
exec rocprofv3 --preload "$BONSAI_BUDDY_KERNEL_MARKERS" \
	--kernel-trace --hip-runtime-trace --marker-trace --memory-copy-trace \
	--stats --output-format csv --output-directory "$BONSAI_BUDDY_PROFILE_OUTPUT" \
	-- "$BONSAI_BUDDY_SERVER" "$@"
WRAPPER
chmod +x "$BONSAI_BUDDY_PROFILE_OUTPUT/server"
python3 benchmarks/agent.py --server "$BONSAI_BUDDY_PROFILE_OUTPUT/server" \
	--case 9b-mtp1 --context 65536 --batch-size 2048 --ubatch-size 512 \
	--output "$BONSAI_BUDDY_PROFILE_OUTPUT"
python3 benchmarks/kernels.py "$BONSAI_BUDDY_PROFILE_OUTPUT" --tokens 2 --context-index 0 --last-calls 64 \
	> "$BONSAI_BUDDY_PROFILE_OUTPUT/target-summary.json"
python3 benchmarks/kernels.py "$BONSAI_BUDDY_PROFILE_OUTPUT" --tokens 3 --context-index 1 --last-calls 64 \
	> "$BONSAI_BUDDY_PROFILE_OUTPUT/draft-summary.json"
printf 'Traces: %s\n' "$BONSAI_BUDDY_PROFILE_OUTPUT"
SH
```

The measured trace uses context 0 for the target and 1 for the draft. Inspect the
marker CSV before assuming those indices and batch sizes in another workload.

## Collect hardware counters

List counters with `rocprofv3 --list-avail` inside the profiling shell. Add these
options before the application separator `--`, using a separate output directory:

```sh
--kernel-include-regex 'void mul_mat_q<.*' \
--kernel-iteration-range 2-5 \
--pmc OccupancyPercent MemUnitBusy L2CacheHit
```

Iteration ranges apply per kernel symbol. Availability depends on the GPU.

## Repeat the PQ2 tile experiment

Build the gfx1030 experiment:

```sh
experiment=$(nix build --impure --file benchmarks/pq2-tiles.nix \
	--argstr repository "$PWD" --no-link --print-out-paths)
export BONSAI_BUDDY_PQ2_EXPERIMENT="$experiment/lib/libbonsai-pq2-experiment.so"
```

Load it only in the benchmark process:

```sh
nix develop .#profiling -c bash <<'SH'
set -euo pipefail
models_dir=${BONSAI_BUDDY_MODELS_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/bonsai-buddy/models}
for tile in 64 48 32 16; do
	env HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION-10.3.0}" \
		LD_PRELOAD="$BONSAI_BUDDY_PQ2_EXPERIMENT" BONSAI_BUDDY_PQ2_TILE="$tile" \
		"$BONSAI_BUDDY_BENCH" \
		-m "$models_dir/Ternary-Bonsai-2-9B-PQ2_0.gguf" \
		-p 2048 -n 0 -b 2048 -ub 512 -fa on -ngl 99 -r 3 -o json
done
SH
```

Add `--arg rows 64` to test smaller row tiles. Compare against the rebuilt 64-column
control before judging another geometry.

## Read the results

`percent_kernel_time` uses summed kernel durations, not request latency.
`traced_gpu_active_ns` counts overlapping intervals once. `traced_gpu_span_ns` can
include unselected work between the first and last selected dispatches.

The summarizer joins CPU enqueue ranges to GPU dispatches through correlation IDs.
Tracing and counters alter timing, especially HIP graphs. Repeat without the profiler
for normal speed; trace gaps alone do not prove idle time.

See AMD's [rocprofv3 guide](https://rocm.docs.amd.com/projects/rocprofiler-sdk/en/docs-7.2.3/how-to/using-rocprofv3.html)
for CLI options.
