"""Check a tool call that retrieves three literals across a long Python module."""

import argparse
import json
import os
from pathlib import Path

from common import port_number, positive_integer, request_json, running_server

EXPECTED = {"north": "plum-472901", "central": "teal-683275", "south": "moss-129048"}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "report_routes",
            "description": "Report the three literal route codes defined in the module.",
            "parameters": {
                "type": "object",
                "properties": {name: {"type": "string"} for name in EXPECTED},
                "required": list(EXPECTED),
                "additionalProperties": False,
            },
        },
    }
]


def build_prompt(functions):
    sections = [
        "Read this module and call report_routes with the exact string values of "
        "ROUTE_NORTH, ROUTE_CENTRAL, and ROUTE_SOUTH.\n\n```python",
        f"ROUTE_NORTH = {EXPECTED['north']!r}",
    ]
    for index in range(functions):
        if index == functions // 2:
            sections.append(f"ROUTE_CENTRAL = {EXPECTED['central']!r}")
        sections.append(
            f"def transform_{index:05d}(value):\n"
            f"    return (value * {index + 17} + {index + 31}) % 65521"
        )
    sections += [
        f"ROUTE_SOUTH = {EXPECTED['south']!r}",
        "```\nCall report_routes now. Copy each route code exactly.",
    ]
    return "\n\n".join(sections)


def long_prompt(base_url, target_tokens):
    functions = max(2, target_tokens // 30)
    for _ in range(6):
        prompt = build_prompt(functions)
        count = len(request_json(base_url, "/tokenize", {"content": prompt})["tokens"])
        if target_tokens * 0.98 <= count <= target_tokens:
            return prompt, count
        functions = max(2, int(functions * (target_tokens - 64) / count))
    raise RuntimeError(
        "Could not size the synthetic prompt to the requested token count"
    )


def correct_tool_call(message):
    calls = message.get("tool_calls", [])
    if len(calls) != 1:
        return False
    function = calls[0]["function"]
    return (
        function["name"] == "report_routes"
        and json.loads(function["arguments"]) == EXPECTED
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flake", default=".")
    parser.add_argument(
        "--case",
        choices=["9b", "9b-plain", "27b"],
        required=True,
    )
    parser.add_argument("--context", type=positive_integer, required=True)
    parser.add_argument("--prompt-tokens", type=positive_integer, required=True)
    parser.add_argument("--kv-type", choices=["f16", "q8_0", "q4_0"])
    cache_types = ["f16", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl"]
    parser.add_argument("--kv-type-k", choices=cache_types)
    parser.add_argument("--kv-type-v", choices=cache_types)
    parser.add_argument("--ubatch-size", type=positive_integer)
    parser.add_argument("--kv-mean-center", type=Path)
    parser.add_argument("--cpu-output", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/results/context")
    )
    parser.add_argument("--port", type=port_number, default=18084)
    options = parser.parse_args()
    if options.prompt_tokens > options.context - 1024:
        parser.error("Leave at least 1024 tokens for the template, tools, and output")
    command = [
        "nix",
        "run",
        f"{options.flake}#{options.case}",
        "--",
        "--port",
        str(options.port),
        "--ctx-size",
        str(options.context),
        "--no-mmproj",
        "--no-webui",
        "--log-verbosity",
        "4",
    ]
    if options.kv_type:
        command += [
            "--cache-type-k",
            options.kv_type,
            "--cache-type-v",
            options.kv_type,
        ]
    if options.kv_type_k:
        command += ["--cache-type-k", options.kv_type_k]
    if options.kv_type_v:
        command += ["--cache-type-v", options.kv_type_v]
    if options.ubatch_size:
        command += ["--ubatch-size", str(options.ubatch_size)]
    if options.kv_mean_center:
        command += ["--kv-mean-center", str(options.kv_mean_center.resolve())]
    if options.cpu_output:
        command += ["--override-tensor", r"^output\.weight$=CPU"]
    options.output.mkdir(parents=True, exist_ok=True)
    settings = [
        "CTX",
        "KV_TYPE",
        "KV_TYPE_K",
        "KV_TYPE_V",
        "UBATCH_SIZE",
        "GPU_RESERVE_MB",
        "MAX_TOKENS",
        "THINK_TOKENS",
    ]
    environment = {
        f"BONSAI_BUDDY_{name}": os.environ[f"BONSAI_BUDDY_{name}"]
        for name in settings
        if f"BONSAI_BUDDY_{name}" in os.environ
    }
    result = {
        "profile": options.case,
        "command": command,
        "environment": environment,
        "passed": False,
    }
    try:
        with running_server(
            command,
            options.port,
            options.output / f"{options.case}.log",
            startup_timeout=240,
        ) as base_url:
            actual = request_json(base_url, "/props")["default_generation_settings"][
                "n_ctx"
            ]
            result["context_capacity"] = actual
            if actual != options.context:
                raise RuntimeError(
                    f"Requested {options.context} context tokens, got {actual}"
                )
            prompt, count = long_prompt(base_url, options.prompt_tokens)
            result["prompt_tokens_before_template"] = count
            (options.output / "prompt.txt").write_text(prompt)
            response = request_json(
                base_url,
                "/v1/chat/completions",
                {
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": TOOLS,
                    "tool_choice": "required",
                    "temperature": 0,
                    "reasoning_effort": "none",
                    "chat_template_kwargs": {"enable_thinking": False},
                    "max_tokens": 256,
                    "cache_prompt": False,
                },
                timeout=1800,
            )
            message = response["choices"][0]["message"]
            result.update(message=message, timings=response.get("timings", {}))
            result["passed"] = correct_tool_call(message)
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        result["error"] = str(error)
    (options.output / f"{options.case}.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
