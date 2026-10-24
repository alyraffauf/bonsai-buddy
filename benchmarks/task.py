"""An in-memory coding task with tools that never execute generated code."""

import ast


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


TOOLS = [
    tool("read_file", "Read a file before editing it.", {"path": {"type": "string"}}),
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


class CodingTask:
    def __init__(self):
        self.source = "def add(a, b):\n    return a - b\n\n" + "\n\n".join(
            f"def helper_{index}(items):\n    return [item * {index + 1} for item in items if item is not None]"
            for index in range(128)
        )
        self.original_nodes = ast.parse(self.source).body
        self.has_read_file = False
        self.tests_passed = False

    def is_correct(self):
        try:
            nodes = ast.parse(self.source).body
        except SyntaxError:
            return False
        expected_add = ast.parse("def add(a, b):\n    return a + b\n").body[0]
        return (
            len(nodes) == len(self.original_nodes)
            and ast.dump(nodes[0]) == ast.dump(expected_add)
            and all(
                ast.dump(actual) == ast.dump(original)
                for actual, original in zip(
                    nodes[1:], self.original_nodes[1:], strict=True
                )
            )
        )

    @property
    def passed(self):
        return self.has_read_file and self.tests_passed and self.is_correct()

    def call(self, name, parameters):
        if not isinstance(parameters, dict):
            return "Error: tool arguments must be a JSON object."
        if name == "run_tests":
            self.tests_passed = self.is_correct()
            return (
                "All tests passed."
                if self.tests_passed
                else "FAIL: add must return a + b and preserve the helper functions."
            )
        if parameters.get("path") != "calc.py":
            return "Error: only calc.py exists."
        if name == "read_file":
            self.has_read_file = True
            return self.source
        if name != "replace_text" or not self.has_read_file:
            return "Error: invalid call. Read calc.py before editing."
        old_text = parameters.get("old_text")
        new_text = parameters.get("new_text")
        if (
            not isinstance(old_text, str)
            or not old_text
            or not isinstance(new_text, str)
        ):
            return "Error: old_text must be nonempty and new_text must be a string."
        if self.source.count(old_text) != 1:
            return "Error: old_text must match exactly once."
        self.source = self.source.replace(old_text, new_text, 1)
        self.tests_passed = False
        return "Replacement applied."
