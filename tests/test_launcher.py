"""Check pinned downloads, checksum failures, and launcher setup boundaries."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.models = self.root / "models"
        self.payload = b"test model contents\n"
        self.checksum = hashlib.sha256(self.payload).hexdigest()
        self.revision = "a" * 40
        self.downloads = self.root / "downloads.jsonl"
        self.server_arguments = self.root / "server.json"
        tools = self.root / "bin"
        tools.mkdir()
        server = self.executable(
            tools / "server",
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['TEST_SERVER_ARGUMENTS']).write_text(json.dumps(sys.argv[1:]))\n",
        )
        self.executable(
            tools / "curl",
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['TEST_DOWNLOADS']).open('a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "payload = b'corrupt' if os.environ.get('TEST_CORRUPT') else b'test model contents\\n'\n"
            "Path(sys.argv[sys.argv.index('--output') + 1]).write_bytes(payload)\n",
        )
        helper = self.executable(tools / "vram", "print(0)\n")
        source = Path(__file__).resolve().parents[1] / "bonsai-buddy.sh"
        script = source.read_text()
        substitutions = {
            "llamaServer": str(server),
            "modelSize": "9b",
            "backend": "rocm",
            "modelFile": "model.gguf",
            "modelSha256": self.checksum,
            "modelRevision": self.revision,
            "draftFile": "",
            "draftSha256": "",
            "extraArgs": "",
            "gpuReserveMb": "512",
            "vramHelper": str(helper),
            "hipLibrary": "/unused/hip.so",
            "contextTokens": "8192",
            "kvType": "f16",
            "thinkingTokens": "1024",
            "maxTokens": "4096",
            "batchSize": "1024",
            "ubatchSize": "256",
        }
        for name, value in substitutions.items():
            script = script.replace(f"@{name}@", value)
        self.assertNotRegex(script, r"@[A-Za-z]+@")
        script = re.sub(
            r'projector_sha256="[a-f0-9]{64}"',
            f'projector_sha256="{self.checksum}"',
            script,
        )
        self.launcher = self.root / "launcher.sh"
        self.launcher.write_text("set -euo pipefail\n" + script)
        self.environment = {
            **os.environ,
            "PATH": f"{tools}:{os.environ['PATH']}",
            "BONSAI_BUDDY_MODELS_DIR": str(self.models),
            "TEST_DOWNLOADS": str(self.downloads),
            "TEST_SERVER_ARGUMENTS": str(self.server_arguments),
        }

    @staticmethod
    def executable(path, content):
        path.write_text(f"#!{sys.executable}\n" + content)
        path.chmod(0o755)
        return path

    def launch(self, *arguments):
        return subprocess.run(
            ["bash", str(self.launcher), *arguments],
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_downloads_use_pinned_revision_and_cached_files_are_reused(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.downloads.read_text().splitlines()]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIn(f"/resolve/{self.revision}/", call[-1])
        self.assertEqual((self.models / "model.gguf").read_bytes(), self.payload)
        self.assertEqual(list(self.models.glob("*.part.*")), [])
        self.environment["TEST_CORRUPT"] = "1"
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.downloads.read_text().splitlines()), 2)

    def test_checksum_failure_removes_partial_download_and_never_starts_server(self):
        self.environment["TEST_CORRUPT"] = "1"
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Checksum mismatch", result.stderr)
        self.assertEqual(list(self.models.iterdir()), [])
        self.assertFalse(self.server_arguments.exists())

    def test_help_skips_downloads_and_model_directory_creation(self):
        result = self.launch("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.server_arguments.read_text()), ["--help"])
        self.assertFalse(self.downloads.exists())
        self.assertFalse(self.models.exists())


if __name__ == "__main__":
    unittest.main()
