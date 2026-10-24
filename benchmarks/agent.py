"""Exercise cached read/edit/test tool loops against local model profiles."""

import argparse
import json
import os
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
from task import TOOLS, CodingTask


def run_case(options, name):
    if options.flake:
        command = [
            "nix",
            "run",
            f"{options.flake}#{name}",
            "--",
            "--port",
            str(options.port),
            "--log-verbosity",
            "4",
        ]
    else:
        arguments = profiles(options.models)[name]
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
            "--batch-size",
            str(options.batch_size),
            "--ubatch-size",
            str(options.ubatch_size),
            "--flash-attn",
            "on",
            "--cache-ram",
            "1024",
            "--ctx-checkpoints",
            "32",
            "--no-mmproj",
            "--no-webui",
        ]
    task = CodingTask()
    messages = [
        {
            "role": "system",
            "content": "You are a coding agent. Read the file, make a minimal edit, and run tests. Finish only after the tests pass.",
        },
        {
            "role": "user",
            "content": "Fix the add function in calc.py. It currently subtracts instead of adding. Preserve the helper functions and verify the fix with tests.",
        },
    ]
    result = {
        "profile": name,
        "command": command,
        "turns": [],
        "passed": False,
        "thinking": options.thinking,
        "preserve_reasoning": options.preserve_reasoning,
    }
    options.output.mkdir(parents=True, exist_ok=True)
    try:
        with running_server(
            command,
            options.port,
            options.output / f"{name}.log",
            env={**os.environ, "BONSAI_MODELS_DIR": str(options.models)},
        ) as base_url:
            started = time.monotonic()
            for turn in range(8):
                payload = {
                    "messages": messages,
                    "tools": TOOLS,
                    "temperature": 1.0 if options.thinking else 0,
                    "max_tokens": 4096 if options.thinking else 512,
                    "cache_prompt": True,
                }
                if not options.thinking:
                    payload.update(
                        reasoning_effort="none",
                        chat_template_kwargs={"enable_thinking": False},
                    )
                response = request_json(
                    base_url,
                    "/v1/chat/completions",
                    payload,
                )
                message = response["choices"][0]["message"]
                result["turns"].append(
                    {"message": message, "timings": response.get("timings", {})}
                )
                calls = message.get("tool_calls", [])
                print(
                    name,
                    "turn",
                    turn,
                    [call["function"]["name"] for call in calls],
                    response.get("timings", {}),
                    flush=True,
                )
                messages.append(
                    {
                        key: value
                        for key, value in message.items()
                        if key in ["role", "content", "tool_calls"]
                        or (options.preserve_reasoning and key == "reasoning_content")
                    }
                )
                if not calls:
                    result["passed"] = task.passed
                    break
                for call in calls:
                    function = call["function"]["name"]
                    parameters = call["function"]["arguments"]
                    if isinstance(parameters, str):
                        parameters = json.loads(parameters)
                    output = task.call(function, parameters)
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": output}
                    )
            result["wall_seconds"] = time.monotonic() - started
            if not result["passed"]:
                result["error"] = (
                    "Agent did not finish with a verified fix within eight turns"
                )
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        result["error"] = str(error)
    (options.output / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        name,
        "PASSED" if result["passed"] else "FAILED",
        result.get("error", ""),
        flush=True,
    )
    return result["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    launcher = parser.add_mutually_exclusive_group(required=True)
    launcher.add_argument("--server")
    launcher.add_argument("--flake")
    parser.add_argument("--models", type=Path, default=default_models_directory())
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/agent"))
    parser.add_argument("--context", type=positive_integer, default=8192)
    parser.add_argument("--port", type=port_number, default=18083)
    parser.add_argument("--batch-size", type=positive_integer, default=1024)
    parser.add_argument("--ubatch-size", type=positive_integer, default=256)
    parser.add_argument("--case", action="append")
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--preserve-reasoning", action="store_true")
    options = parser.parse_args()
    defaults = (
        ["9b", "27b", "9b-rewrite"]
        if options.flake
        else ["9b-plain", "9b-mtp1", "9b-dflash", "27b-ptq", "27b-plain"]
    )
    names = options.case or defaults
    available = (
        {
            "9b",
            "27b",
            "9b-plain",
            "9b-rewrite",
            "9b-vulkan",
            "27b-vulkan",
        }
        if options.flake
        else profiles(options.models)
    )
    for name in names:
        if name not in available:
            parser.error(f"Unknown case {name!r}")
    results = [run_case(options, name) for name in names]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
