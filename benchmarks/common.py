"""Shared cache paths, HTTP requests, and benchmark server lifetime."""

import argparse
import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def default_models_directory() -> Path:
    configured = os.environ.get("BONSAI_MODELS_DIR")
    if configured:
        return Path(configured)
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "bonsaid" / "models"


def positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def port_number(value: str) -> int:
    number = positive_integer(value)
    if number > 65535:
        raise argparse.ArgumentTypeError("must be at most 65535")
    return number


def request_json(
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 600,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base_url + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise TypeError("Expected a JSON object from the server")
    return result


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


@contextmanager
def running_server(
    command: list[str],
    port: int,
    log_path: Path,
    *,
    startup_timeout: float = 120,
    env: dict[str, str] | None = None,
) -> Generator[str]:
    # Refuse occupied ports before launching, rather than probing an unrelated model.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(
                f"Benchmark port {port} is unavailable: {error}"
            ) from error

    base_url = f"http://127.0.0.1:{port}"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=log, start_new_session=True, env=env
        )
        try:
            deadline = time.monotonic() + startup_timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Server exited with status {process.returncode}"
                    )
                try:
                    healthy = (
                        request_json(base_url, "/health", timeout=1).get("status")
                        == "ok"
                    )
                except (urllib.error.URLError, TimeoutError):
                    healthy = False
                if healthy and process.poll() is None:
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError(f"Server startup exceeded {startup_timeout} seconds")
            yield base_url
        finally:
            stop_server(process)
