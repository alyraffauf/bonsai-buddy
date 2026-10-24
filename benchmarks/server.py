"""Compare speculative decoding with identical local HTTP workloads."""

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def request_json(base_url, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base_url + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def profiles(models):
    nine = str(models / "Ternary-Bonsai-2-9B-PQ2_0.gguf")
    twenty_seven = str(models / "Ternary-Bonsai-2-27B-PQ2_0.gguf")
    ptq = str(models / "Ternary-Bonsai-2-27B-PTQ1_0.gguf")
    return {
        "9b-plain": ["--model", nine],
        "9b-ptq": ["--model", str(models / "Ternary-Bonsai-2-9B-PTQ1_0.gguf")],
        "9b-mtp1": [
            "--model",
            str(models / "Ternary-Bonsai-2-9B-PQ2_0-MTP-Q8_0.gguf"),
            "--spec-type",
            "draft-mtp",
            "--spec-draft-n-max",
            "1",
            "--spec-draft-p-min",
            "0",
        ],
        "9b-mtp2": [
            "--model",
            str(models / "Ternary-Bonsai-2-9B-PQ2_0-MTP-Q8_0.gguf"),
            "--spec-type",
            "draft-mtp",
            "--spec-draft-n-max",
            "2",
            "--spec-draft-p-min",
            "0",
        ],
        "9b-mtp4": [
            "--model",
            str(models / "Ternary-Bonsai-2-9B-PQ2_0-MTP-Q8_0.gguf"),
            "--spec-type",
            "draft-mtp",
            "--spec-draft-n-max",
            "4",
            "--spec-draft-p-min",
            "0",
        ],
        "9b-dflash": [
            "--model",
            nine,
            "--model-draft",
            str(models / "Ternary-Bonsai-2-9B-DFlash2-Q8_0.gguf"),
            "--spec-type",
            "draft-dflash",
            "--spec-draft-n-max",
            "16",
        ],
        "9b-ngram": ["--model", nine, "--spec-type", "ngram-mod"],
        "9b-ngram-tuned": [
            "--model",
            nine,
            "--spec-type",
            "ngram-simple",
            "--spec-ngram-simple-size-n",
            "8",
            "--spec-ngram-simple-size-m",
            "32",
        ],
        "27b-plain": ["--model", twenty_seven],
        "27b-ptq": ["--model", ptq],
        "27b-ngram": ["--model", twenty_seven, "--spec-type", "ngram-mod"],
        "27b-ngram-tuned": [
            "--model",
            twenty_seven,
            "--spec-type",
            "ngram-simple",
            "--spec-ngram-simple-size-n",
            "8",
            "--spec-ngram-simple-size-m",
            "32",
        ],
        "27b-draft2b": [
            "--model",
            ptq,
            "--model-draft",
            str(models / "Ternary-Bonsai-2-2B-PQ2_0.gguf"),
            "--spec-type",
            "draft-simple",
            "--spec-draft-n-max",
            "4",
        ],
    }


def run_profile(options, name, arguments):
    base_url = f"http://127.0.0.1:{options.port}"
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
    with (options.output / f"{name}.log").open("w") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=log, start_new_session=True
        )
        try:
            for attempt in range(120):
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Server exited with status {process.returncode}"
                    )
                try:
                    if request_json(base_url, "/health").get("status") == "ok":
                        break
                except (urllib.error.URLError, TimeoutError):
                    pass
                time.sleep(1)
            else:
                raise TimeoutError("Server startup exceeded 120 seconds")
            loaded = request_json(base_url, "/props")["model_path"]
            if loaded != arguments[arguments.index("--model") + 1]:
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
            if "391" not in answer:
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
        except (RuntimeError, TimeoutError, urllib.error.URLError) as error:
            result["error"] = str(error)
            print(name, "FAILED", error, flush=True)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    (options.output / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument(
        "--models", type=Path, default=Path.home() / ".cache/bonsaid/models"
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/api"))
    parser.add_argument("--port", type=int, default=18082)
    parser.add_argument("--tokens", type=int, default=192)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--checkpoints", type=int, default=0)
    parser.add_argument("--cache-ram", type=int, default=0)
    parser.add_argument("--cache-prompt", action="store_true")
    parser.add_argument("--code-functions", type=int, default=24)
    parser.add_argument("--kv-type", choices=["f16", "q8_0", "q4_0"])
    parser.add_argument("--case", action="append")
    options = parser.parse_args()
    available = profiles(options.models)
    for name in options.case or available:
        if name not in available:
            parser.error(f"Unknown case {name!r}")
        run_profile(options, name, available[name])


if __name__ == "__main__":
    main()
