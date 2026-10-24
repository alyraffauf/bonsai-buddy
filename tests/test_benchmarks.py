"""Check benchmark isolation, failure reporting, and simulated tool correctness."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from common import default_models_directory, running_server
from task import CodingTask


class CacheTests(unittest.TestCase):
    def test_environment_precedence(self):
        with patch.dict(
            os.environ,
            {"BONSAI_BUDDY_MODELS_DIR": "/models", "XDG_CACHE_HOME": "/cache"},
        ):
            self.assertEqual(default_models_directory(), Path("/models"))
        with patch.dict(
            os.environ, {"BONSAI_BUDDY_MODELS_DIR": "", "XDG_CACHE_HOME": "/cache"}
        ):
            self.assertEqual(
                default_models_directory(), Path("/cache/bonsai-buddy/models")
            )
        with patch.dict(
            os.environ, {"BONSAI_BUDDY_MODELS_DIR": "", "XDG_CACHE_HOME": ""}
        ):
            self.assertEqual(
                default_models_directory(), Path.home() / ".cache/bonsai-buddy/models"
            )


class ServerTests(unittest.TestCase):
    def test_recently_closed_connections_do_not_block_the_next_run(self):
        with socket.socket() as listener, socket.socket() as client:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            client.connect(("127.0.0.1", port))
            connection, _ = listener.accept()
            connection.close()
            client.settimeout(1)
            self.assertEqual(client.recv(1), b"")
        with tempfile.TemporaryDirectory() as directory:
            with patch("common.subprocess.Popen") as launch:
                launch.return_value.poll.return_value = 1
                launch.return_value.returncode = 1
                with self.assertRaisesRegex(RuntimeError, "Server exited"):
                    with running_server(
                        ["unused"], port, Path(directory) / "server.log"
                    ):
                        self.fail("The fake process must exit before serving")
                launch.assert_called_once()

    def test_occupied_port_never_starts_or_probes_a_server(self):
        with socket.socket() as listener, tempfile.TemporaryDirectory() as directory:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with (
                patch("common.subprocess.Popen") as launch,
                patch("common.request_json") as request,
            ):
                with self.assertRaisesRegex(RuntimeError, "unavailable"):
                    with running_server(
                        ["unused"],
                        listener.getsockname()[1],
                        Path(directory) / "server.log",
                    ):
                        self.fail("An occupied port must not become ready")
                launch.assert_not_called()
                request.assert_not_called()

    def test_request_failure_stops_only_the_launched_process(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("common.subprocess.Popen") as launch,
                patch("common.request_json", return_value={"status": "ok"}),
                patch("common.stop_server") as stop,
            ):
                launch.return_value.poll.return_value = None
                with self.assertRaises(urllib.error.URLError):
                    with running_server(
                        ["unused"], port, Path(directory) / "server.log"
                    ):
                        raise urllib.error.URLError("request failed")
                stop.assert_called_once_with(launch.return_value)

    def test_startup_failure_returns_nonzero_and_writes_results(self):
        scripts = Path(__file__).resolve().parents[1] / "benchmarks"
        for script in ("agent.py", "server.py"):
            with (
                self.subTest(script=script),
                tempfile.TemporaryDirectory() as directory,
            ):
                result = subprocess.run(
                    [
                        sys.executable,
                        str(scripts / script),
                        "--server",
                        "/nonexistent/bonsai-buddy-test-server",
                        "--case",
                        "9b-plain",
                        "--output",
                        directory,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                record = json.loads((Path(directory) / "9b-plain.json").read_text())
                self.assertIn("error", record)


class CodingTaskTests(unittest.TestCase):
    def setUp(self):
        self.task = CodingTask()

    def apply_fix(self):
        self.task.call("read_file", {"path": "calc.py"})
        self.task.call(
            "replace_text",
            {"path": "calc.py", "old_text": "return a - b", "new_text": "return a + b"},
        )

    def test_fix_requires_read_then_tests(self):
        self.assertFalse(self.task.passed)
        self.apply_fix()
        self.assertTrue(self.task.is_correct())
        self.assertFalse(self.task.passed)
        self.assertEqual(self.task.call("run_tests", {}), "All tests passed.")
        self.assertTrue(self.task.passed)

    def test_edit_invalidates_previous_test_result(self):
        self.apply_fix()
        self.task.call("run_tests", {})
        self.task.call(
            "replace_text",
            {"path": "calc.py", "old_text": "return a + b", "new_text": "return a - b"},
        )
        self.assertFalse(self.task.passed)

    def test_helper_deletion_or_change_fails(self):
        self.apply_fix()
        corrected = self.task.source
        for changed in (
            "def add(a, b):\n    return a + b\n",
            corrected.replace("item * 128", "item * 999"),
        ):
            with self.subTest(source=changed[:50]):
                self.task.source = changed
                self.assertFalse(self.task.is_correct())

    def test_unread_file_cannot_be_edited(self):
        original = self.task.source
        self.task.call(
            "replace_text",
            {"path": "calc.py", "old_text": "return a - b", "new_text": "return a + b"},
        )
        self.assertEqual(self.task.source, original)

    def test_invalid_arguments_do_not_mutate_the_file(self):
        self.task.call("read_file", {"path": "calc.py"})
        original = self.task.source
        for parameters in (
            None,
            [],
            {"path": "calc.py"},
            {"path": "calc.py", "old_text": "", "new_text": "broken"},
        ):
            with self.subTest(parameters=parameters):
                self.assertTrue(
                    self.task.call("replace_text", parameters).startswith("Error:")
                )
                self.assertEqual(self.task.source, original)


if __name__ == "__main__":
    unittest.main()
