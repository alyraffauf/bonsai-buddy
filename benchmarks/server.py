"""Compare speculative decoding with identical local HTTP workloads."""

import argparse
import json
import time
from pathlib import Path

from common import (
    default_models_directory,
    port_number,
    positive_integer,
    request_json,
    running_server,
)
from profiles import profiles


def run_profile(options, name, arguments):
    command = [
        options.server,
        *arguments,
        "--host",
        "127.0.0.1",
        "--port",
        str(options.port),
        "--ctx-size",
        str(options.context),
        "--parallel",
        "1",
        "--gpu-layers",
        "99",
        "--flash-attn",
        "on",
        "--batch-size",
        "1024",
        "--ubatch-size",
        "256",
        "--ctx-checkpoints",
        str(options.checkpoints),
        "--cache-ram",
        str(options.cache_ram),
        "--no-webui",
        "--no-mmproj",
        "--reasoning-budget",
        "1024",
        "--reasoning-format",
        "deepseek",
    ]
    if options.kv_type:
        command += [
            "--cache-type-k",
            options.kv_type,
            "--cache-type-v",
            options.kv_type,
        ]
    result = {"profile": name, "command": command, "requests": []}
    options.output.mkdir(parents=True, exist_ok=True)
    try:
        with running_server(
            command, options.port, options.output / f"{name}.log"
        ) as base_url:
            loaded = request_json(base_url, "/props")["model_path"]
            expected = arguments[arguments.index("--model") + 1]
            if Path(loaded).resolve() != Path(expected).resolve():
                raise RuntimeError(f"Wrong model on benchmark port: {loaded}")

            def chat(prompt, max_tokens):
                return request_json(
                    base_url,
                    "/v1/chat/completions",
                    {
                        "messages": [{"role": "user", "content": prompt}],
                        "reasoning_effort": "none",
                        "chat_template_kwargs": {"enable_thinking": False},
                        "temperature": 0,
                        "max_tokens": max_tokens,
                        "cache_prompt": options.cache_prompt,
                    },
                )

            check = chat("What is 17 times 23? Reply only with the number.", 32)
            answer = check["choices"][0]["message"].get("content", "")
            if answer.strip() != "391":
                raise RuntimeError(f"Arithmetic check failed: {answer!r}")
            code = "\n\n".join(
                f"def transform_{index}(items):\n    return [item * {index + 1} for item in items if item is not None]"
                for index in range(options.code_functions)
            )
            prompts = {
                "explanation": "Explain how a CPU cache works, covering locality, cache lines, associativity, write policies, and multicore coherence. Use concrete examples and write about 700 words.",
                "code-edit": "Return this Python code with every function renamed from transform_N to process_N. Preserve the function bodies. Output only the edited code.\n\n"
                + code,
            }
            for workload, prompt in prompts.items():
                for repetition in range(options.repetitions):
                    started = time.monotonic()
                    response = chat(prompt, options.tokens)
                    row = {
                        "workload": workload,
                        "repetition": repetition,
                        "wall_seconds": time.monotonic() - started,
                        "timings": response.get("timings", {}),
                        "usage": response.get("usage", {}),
                        "answer": response["choices"][0]["message"].get("content", ""),
                    }
                    result["requests"].append(row)
                    print(name, workload, repetition, row["timings"], flush=True)
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        result["error"] = str(error)
        print(name, "FAILED", error, flush=True)
    (options.output / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")
    return "error" not in result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--models", type=Path, default=default_models_directory())
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/api"))
    parser.add_argument("--port", type=port_number, default=18082)
    parser.add_argument("--tokens", type=positive_integer, default=192)
    parser.add_argument("--repetitions", type=positive_integer, default=2)
    parser.add_argument("--context", type=positive_integer, default=8192)
    parser.add_argument("--checkpoints", type=int, default=0)
    parser.add_argument("--cache-ram", type=int, default=0)
    parser.add_argument("--cache-prompt", action="store_true")
    parser.add_argument("--code-functions", type=positive_integer, default=24)
    parser.add_argument("--kv-type", choices=["f16", "q8_0", "q4_0"])
    parser.add_argument("--case", action="append")
    options = parser.parse_args()
    available = profiles(options.models)
    names = options.case or list(available)
    for name in names:
        if name not in available:
            parser.error(f"Unknown case {name!r}")
    results = []
    for name in names:
        results.append(run_profile(options, name, available[name]))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
