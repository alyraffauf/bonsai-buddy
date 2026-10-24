"""Serve metadata for launcher tests without loading model weights."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

if os.environ.get("SERVER_FAIL"):
    raise SystemExit(3)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            data = {"status": "ok"}
        elif self.path == "/props":
            data = {
                "model_alias": os.environ["SERVER_MODEL"],
                "default_generation_settings": {
                    "n_ctx": int(os.environ["SERVER_CONTEXT"])
                },
            }
        else:
            self.send_error(404)
            return
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


with HTTPServer(("127.0.0.1", int(os.environ["BONSAI_BUDDY_PORT"])), Handler) as server:
    Path(os.environ["SERVER_CAPTURE"]).write_text(str(os.getpid()))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
