"""Record launcher arguments without running an agent."""

import json
import os
import sys
from pathlib import Path

record = {"arguments": sys.argv[1:]}
if os.environ.get("OPENCODE_CONFIG"):
    record["config"] = json.loads(Path(os.environ["OPENCODE_CONFIG"]).read_text())
Path(os.environ["CLIENT_CAPTURE"]).write_text(json.dumps(record))
raise SystemExit(int(os.environ.get("CLIENT_EXIT_CODE", "0")))
