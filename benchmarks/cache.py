"""Measure prefix reuse after common changes to a coding-agent transcript."""

import argparse
import copy
import json
import re
import time
from pathlib import Path

from common import port_number, positive_integer, request_json, running_server
from task import TOOLS, CodingTask, tool


def mutate_history(messages, variant):
    history = copy.deepcopy(messages)
    if variant == "strip-reasoning":
        for message in history:
            message.pop("reasoning_content", None)
    elif variant in {"format-arguments", "reorder-arguments"}:
        function = history[2]["tool_calls"][0]["function"]
        arguments = json.loads(function["arguments"])
        if variant == "reorder-arguments":
            arguments = dict(reversed(list(arguments.items())))
        function["arguments"] = json.dumps(arguments, indent=2)
    elif variant == "early-edit":
        history[0]["content"] += " Keep the change small."
    return history


def run_case(options, size):
    tools = [
        tool(
            "read_file",
            "Read lines from a file.",
            {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
        )
    ]
    source = CodingTask().source
    seed = [
        {"role": "system", "content": "You are a coding agent. Make minimal fixes."},
        {"role": "user", "content": "Find the bug in calc.py's add function."},
        {
            "role": "assistant",
            "content": None,
            "reasoning_content": "I need to read calc.py before deciding what to change.",
            "tool_calls": [
                {
                    "id": "call_read",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"calc.py","start_line":1,"end_line":1000}',
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_read", "content": source},
        {
            "role": "user",
            "content": "Briefly explain the bug. Do not call another tool yet.",
        },
    ]
    if options.continuation == "tool":
        tools += TOOLS[1:]
        seed = seed[:-1]
        seed[1]["content"] = (
            "Fix calc.py's add function using replace_text, then run_tests."
        )
    variants = [
        "stable",
        "strip-reasoning",
        "format-arguments",
        "reorder-arguments",
        "early-edit",
        "cache-off",
    ]
    command = [
        "nix",
        "run",
        f"{options.flake}#{size}",
        "--",
        "--port",
        str(options.port),
        "--no-webui",
        "--log-verbosity",
        "4",
        "--cache-ram",
        str(options.cache_ram),
    ]
    result = {
        "model": size,
        "repetitions": options.repetitions,
        "cache_ram_mb": options.cache_ram,
        "continuation": options.continuation,
        "requests": [],
    }
    options.output.mkdir(parents=True, exist_ok=True)
    with running_server(command, options.port, options.output / f"{size}.log") as url:
        props = request_json(url, "/props")
        result["context"] = props["default_generation_settings"]["n_ctx"]
        startup = (options.output / f"{size}.log").read_text()
        result["gpu_placement"] = re.findall(r"offloaded (\d+/\d+) layers", startup)
        result["gdn_fusion_disabled"] = (
            "Gated Delta Net (chunked) not supported" in startup
        )

        def chat(messages, cache_prompt=True, thinking=False, edit=False):
            payload = {
                "messages": messages,
                "tools": tools,
                "tool_choice": (
                    {"type": "function", "function": {"name": "replace_text"}}
                    if edit
                    else "auto"
                    if options.continuation == "tool"
                    else "none"
                ),
                "temperature": 0,
                "max_tokens": 256 if thinking else 32,
                "reasoning_budget_tokens": 64 if thinking else 0,
                "chat_template_kwargs": {
                    "enable_thinking": thinking,
                    "preserve_thinking": True,
                    "reasoning_effort": "medium",
                },
                "cache_prompt": cache_prompt,
            }
            if not thinking:
                payload["reasoning_effort"] = "none"
            return request_json(url, "/v1/chat/completions", payload)

        for repetition in range(options.repetitions):
            order = variants if repetition % 2 == 0 else list(reversed(variants))
            for variant in order:
                warm = chat(seed, thinking=True, edit=options.continuation == "tool")
                assistant = {
                    key: value
                    for key, value in warm["choices"][0]["message"].items()
                    if key in {"role", "content", "reasoning_content", "tool_calls"}
                }
                if options.continuation == "tool":
                    calls = assistant.get("tool_calls", [])
                    if (
                        len(calls) != 1
                        or calls[0]["function"]["name"] != "replace_text"
                    ):
                        raise RuntimeError(f"Expected one edit call: {assistant}")
                    continuation = {
                        "role": "tool",
                        "tool_call_id": calls[0]["id"],
                        "content": "Replacement applied.",
                    }
                else:
                    continuation = {
                        "role": "user",
                        "content": "Reply only with the corrected expression.",
                    }
                messages = [*seed, assistant, continuation]
                started = time.monotonic()
                response = chat(
                    mutate_history(messages, variant), variant != "cache-off", True
                )
                row = {
                    "variant": variant,
                    "repetition": repetition,
                    "wall_seconds": time.monotonic() - started,
                    "warm_timings": warm.get("timings", {}),
                    "timings": response.get("timings", {}),
                    "warm_reasoning_tokens_present": bool(
                        assistant.get("reasoning_content")
                    ),
                    "answer": response["choices"][0]["message"].get("content", ""),
                    "tool_calls": response["choices"][0]["message"].get(
                        "tool_calls", []
                    ),
                }
                result["requests"].append(row)
                print(size, variant, repetition, row["timings"], flush=True)
                (options.output / f"{size}.json").write_text(
                    json.dumps(result, indent=2) + "\n"
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flake", default=".")
    parser.add_argument("--case", action="append", choices=["9b", "27b"])
    parser.add_argument("--port", type=port_number, default=18085)
    parser.add_argument("--repetitions", type=positive_integer, default=3)
    parser.add_argument("--cache-ram", type=int, default=0)
    parser.add_argument("--continuation", choices=["tool", "user"], default="tool")
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/cache"))
    options = parser.parse_args()
    for size in options.case or ["9b", "27b"]:
        run_case(options, size)


if __name__ == "__main__":
    main()
