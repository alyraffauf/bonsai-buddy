"""Exercise cached read/edit/test tool loops against local model profiles."""

import argparse
import ast
import json
import os
import signal
import subprocess
import time
import urllib.error
from pathlib import Path

from server import profiles, request_json


def tool(name, description, properties):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


def has_correct_add(source):
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "add":
            return any(
                isinstance(value, ast.Return)
                and isinstance(value.value, ast.BinOp)
                and isinstance(value.value.op, ast.Add)
                and isinstance(value.value.left, ast.Name)
                and value.value.left.id == "a"
                and isinstance(value.value.right, ast.Name)
                and value.value.right.id == "b"
                for value in node.body
            )
    return False


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
    base_url = f"http://127.0.0.1:{options.port}"
    source = "def add(a, b):\n    return a - b\n\n" + "\n\n".join(
        f"def helper_{index}(items):\n    return [item * {index + 1} for item in items if item is not None]"
        for index in range(128)
    )
    tools = [
        tool(
            "read_file", "Read a file before editing it.", {"path": {"type": "string"}}
        ),
        tool(
            "replace_text",
            "Replace exact text in a file.",
            {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
        ),
        tool("run_tests", "Run the unit tests.", {}),
    ]
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
    read_file = False
    tests_passed = False
    options.output.mkdir(parents=True, exist_ok=True)
    with (options.output / f"{name}.log").open("w") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=log, start_new_session=True
        )
        try:
            for attempt in range(120):
                if process.poll() is not None:
                    raise RuntimeError(f"Server exited: {process.returncode}")
                try:
                    if request_json(base_url, "/health").get("status") == "ok":
                        break
                except (urllib.error.URLError, TimeoutError):
                    pass
                time.sleep(1)
            else:
                raise TimeoutError("Server did not start")
            started = time.monotonic()
            for turn in range(8):
                payload = {
                    "messages": messages,
                    "tools": tools,
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
                    result["passed"] = (
                        read_file and tests_passed and has_correct_add(source)
                    )
                    break
                for call in calls:
                    function = call["function"]["name"]
                    parameters = call["function"]["arguments"]
                    if isinstance(parameters, str):
                        parameters = json.loads(parameters)
                    if function == "read_file" and parameters.get("path") == "calc.py":
                        read_file = True
                        output = source
                    elif (
                        function == "replace_text"
                        and read_file
                        and parameters.get("path") == "calc.py"
                    ):
                        old = parameters["old_text"]
                        if old not in source:
                            output = "Error: old_text was not found."
                        else:
                            source = source.replace(old, parameters["new_text"], 1)
                            output = "Replacement applied."
                    elif function == "run_tests":
                        tests_passed = has_correct_add(source)
                        output = (
                            "All tests passed."
                            if tests_passed
                            else "FAIL: add(17, 23) must return 40."
                        )
                    else:
                        output = "Error: invalid call. Read calc.py before editing."
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": output}
                    )
            result["wall_seconds"] = time.monotonic() - started
        except (
            RuntimeError,
            TimeoutError,
            urllib.error.URLError,
            ValueError,
            KeyError,
        ) as error:
            result["error"] = str(error)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    (options.output / f"{name}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        name,
        "PASSED" if result["passed"] else "FAILED",
        result.get("error", ""),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    launcher = parser.add_mutually_exclusive_group(required=True)
    launcher.add_argument("--server")
    launcher.add_argument("--flake")
    parser.add_argument(
        "--models", type=Path, default=Path.home() / ".cache/bonsaid/models"
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/agent"))
    parser.add_argument("--context", type=int, default=8192)
    parser.add_argument("--port", type=int, default=18083)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--ubatch-size", type=int, default=256)
    parser.add_argument("--case", action="append")
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--preserve-reasoning", action="store_true")
    options = parser.parse_args()
    defaults = (
        ["9b", "27b", "9b-rewrite", "27b-prefill"]
        if options.flake
        else ["9b-plain", "9b-mtp1", "9b-dflash", "27b-ptq", "27b-plain"]
    )
    for name in options.case or defaults:
        run_case(options, name)


if __name__ == "__main__":
    main()
