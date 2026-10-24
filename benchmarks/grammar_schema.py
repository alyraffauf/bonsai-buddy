"""Print a synthetic 107-tool schema for the grammar-cloning benchmark."""

import json
import sys


def schema(index):
    return {
        "type": "object",
        "properties": {
            "name": {"const": f"tool_{index}"},
            "arguments": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "query": {"type": "string"},
                    "options": {
                        "type": "object",
                        "properties": {
                            "recursive": {"type": "boolean"},
                            "limit": {"type": "integer"},
                            "patterns": {"type": "array", "items": {"type": "string"}},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["path", "query"],
                "additionalProperties": False,
            },
        },
        "required": ["name", "arguments"],
        "additionalProperties": False,
    }


json.dump({"oneOf": [schema(index) for index in range(107)]}, sys.stdout)
