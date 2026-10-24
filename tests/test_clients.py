"""Exercise client settings and model-server ownership through the real shell script."""

import json
import os
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


class ClientLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.root = Path(__file__).resolve().parents[1]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.environment = {
            **os.environ,
            "BONSAI_BUDDY_PORT": str(self.port),
            "BONSAI_BUDDY_CTX": "16384",
            "BONSAI_BUDDY_MAX_TOKENS": "4096",
            "BONSAI_BUDDY_THINK_TOKENS": "2048",
            "SERVER_MODEL": "bonsai2:27b",
            "SERVER_CONTEXT": "16384",
            "CLIENT_CAPTURE": str(self.directory / "client.json"),
            "SERVER_CAPTURE": str(self.directory / "server.pid"),
        }

    def render(self, size="27b"):
        fixture = self.root / "tests" / "fixtures"
        config = self.directory / "opencode.json"
        config.write_text(
            json.dumps(
                {
                    "providers": {
                        "bonsai-buddy": {
                            "settings": {},
                            "models": {f"bonsai2:{size}": {"body": {}}},
                        }
                    },
                    "compaction": {},
                }
            )
        )
        substitutions = {
            "clientProgram": shlex.join([sys.executable, str(fixture / "client.py")]),
            "serverProgram": shlex.join(
                [sys.executable, str(fixture / "model_server.py")]
            ),
            "modelSize": size,
            "contextTokens": "16384",
            "maxTokens": "4096",
            "thinkingTokens": "2048",
            "reserveTokens": "4096" if size == "27b" else "8192",
            "opencodeConfig": shlex.quote(str(config)),
        }
        script = (self.root / "client.sh").read_text()
        for key, value in substitutions.items():
            script = script.replace(f"@{key}@", value)
        path = self.directory / "launch.sh"
        path.write_text("set -euo pipefail\n" + script)
        return path

    def launch(self, size="27b", arguments=()):
        return subprocess.run(
            ["bash", str(self.render(size)), *arguments],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def assert_owned_server_stopped(self):
        pid = int(Path(self.environment["SERVER_CAPTURE"]).read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def existing_server(self):
        process = subprocess.Popen(
            [sys.executable, str(self.root / "tests/fixtures/model_server.py")],
            env=self.environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self.stop_existing_server, process)
        for _ in range(100):
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/health", timeout=1
                ):
                    return process
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.02)
        self.fail("Fixture server did not start")

    @staticmethod
    def stop_existing_server(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)

    def test_opencode_limits_and_owned_server_cleanup(self):
        result = self.launch(arguments=("run", "Hello"))
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(Path(self.environment["CLIENT_CAPTURE"]).read_text())
        model = record["config"]["providers"]["bonsai-buddy"]["models"]["bonsai2:27b"]
        self.assertEqual(
            model["limit"], {"context": 16384, "input": 12288, "output": 4096}
        )
        self.assertEqual(model["body"]["reasoning_budget_tokens"], 2048)
        self.assertEqual(record["config"]["compaction"]["buffer"], 4096)
        self.assertEqual(record["config"]["compaction"]["keep"]["tokens"], 4096)
        self.assertEqual(record["arguments"], ["run", "Hello", "--standalone"])
        self.assert_owned_server_stopped()

    def test_9b_context_and_compaction(self):
        self.environment.update(
            BONSAI_BUDDY_CTX="65536",
            BONSAI_BUDDY_MAX_TOKENS="8192",
            BONSAI_BUDDY_THINK_TOKENS="1024",
            SERVER_MODEL="bonsai2:9b",
            SERVER_CONTEXT="65536",
        )
        result = self.launch("9b")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(Path(self.environment["CLIENT_CAPTURE"]).read_text())[
            "config"
        ]
        limits = config["providers"]["bonsai-buddy"]["models"]["bonsai2:9b"]["limit"]
        self.assertEqual(limits, {"context": 65536, "input": 57344, "output": 8192})
        self.assertEqual(config["compaction"]["buffer"], 8192)
        self.assertEqual(limits["input"] - config["compaction"]["buffer"], 49152)
        self.assert_owned_server_stopped()

    def test_long_context_limits_follow_each_model_capacity(self):
        for size, context, output, reserve in [
            ("9b", 131072, 8192, 8192),
            ("27b", 32768, 4096, 4096),
            ("27b", 65536, 4096, 4096),
        ]:
            with self.subTest(size=size):
                self.environment.update(
                    BONSAI_BUDDY_CTX=str(context),
                    BONSAI_BUDDY_MAX_TOKENS=str(output),
                    BONSAI_BUDDY_THINK_TOKENS="1024" if size == "9b" else "2048",
                    SERVER_MODEL=f"bonsai2:{size}",
                    SERVER_CONTEXT=str(context),
                )
                result = self.launch(size)
                self.assertEqual(result.returncode, 0, result.stderr)
                config = json.loads(
                    Path(self.environment["CLIENT_CAPTURE"]).read_text()
                )["config"]
                model = config["providers"]["bonsai-buddy"]["models"][f"bonsai2:{size}"]
                self.assertEqual(
                    model["limit"],
                    {
                        "context": context,
                        "input": context - output,
                        "output": output,
                    },
                )
                self.assertEqual(config["compaction"]["buffer"], reserve)
                self.assertEqual(
                    model["body"]["reasoning_budget_tokens"],
                    1024 if size == "9b" else 2048,
                )
                self.assert_owned_server_stopped()

    def test_reused_server_survives_client_exit(self):
        process = self.existing_server()
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(process.poll())

    def test_mismatched_server_is_rejected_and_left_running(self):
        self.environment["SERVER_MODEL"] = "bonsai2:9b"
        process = self.existing_server()
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("this launcher needs", result.stderr)
        self.assertFalse(Path(self.environment["CLIENT_CAPTURE"]).exists())
        self.assertIsNone(process.poll())

    def test_failed_client_still_stops_owned_server(self):
        self.environment["CLIENT_EXIT_CODE"] = "9"
        result = self.launch()
        self.assertEqual(result.returncode, 9)
        self.assert_owned_server_stopped()

    def test_reused_server_with_wrong_context_is_rejected(self):
        self.environment["SERVER_CONTEXT"] = "8192"
        process = self.existing_server()
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("with 8192 context tokens", result.stderr)
        self.assertFalse(Path(self.environment["CLIENT_CAPTURE"]).exists())
        self.assertIsNone(process.poll())

    def test_model_start_failure_does_not_open_the_client(self):
        self.environment["SERVER_FAIL"] = "1"
        result = self.launch()
        self.assertEqual(result.returncode, 1)
        self.assertIn("did not become ready", result.stderr)
        self.assertFalse(Path(self.environment["CLIENT_CAPTURE"]).exists())

    def test_invalid_limits_do_not_start_anything(self):
        self.environment["BONSAI_BUDDY_THINK_TOKENS"] = "4096"
        result = self.launch()
        self.assertEqual(result.returncode, 2)
        self.assertFalse(Path(self.environment["SERVER_CAPTURE"]).exists())

    def test_help_does_not_start_a_server(self):
        result = self.launch(arguments=("--help",))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(Path(self.environment["SERVER_CAPTURE"]).exists())


if __name__ == "__main__":
    unittest.main()
