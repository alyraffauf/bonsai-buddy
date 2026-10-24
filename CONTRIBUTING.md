# Contribute

Run `nix flake check` before submitting changes. It checks Ruff formatting, lint,
types with ty, and regression tests without a GPU or model downloads.

Use `nix develop` for the Python and C++ tools. Format Nix with `nix fmt` and Python
with `ruff format benchmarks tests` inside the development shell.

For inference changes, follow the [benchmark guide](benchmarks/README.md). Record
the hardware, runtime revision, model, context, KV format, and every timing sample.
Keep experiments separate from defaults until correctness and repeated measurements
support the change. Report prefill, generation, and whole-task latency separately.

Keep raw traces and model files out of Git. Published measurements belong in
`benchmarks/measurements/`; remove local paths and include the reproduction method.
