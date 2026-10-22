"""Helpers for browser tests: a subprocess NiceGUI harness and a Playwright page."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

HARNESS = Path(__file__).with_name("harness_app.py")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def harness(html: str = "", *, readonly: bool = False, commenting: bool = False):
    port = free_port()
    with tempfile.TemporaryDirectory() as tmp:
        html_file = Path(tmp) / "doc.html"
        html_file.write_text(html)
        # NiceGUI's ui.run() does nothing under pytest, and a child process inherits this marker.
        base = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
        env = {**base, "PORT": str(port), "HARNESS_HTML": str(html_file),
               "HARNESS_READONLY": "1" if readonly else "0", "HARNESS_COMMENTING": "1" if commenting else "0"}
        proc = subprocess.Popen([sys.executable, str(HARNESS)], env=env, cwd=tmp,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.3)
            else:
                raise RuntimeError("harness did not start")
            yield f"http://127.0.0.1:{port}/"
        finally:
            proc.terminate()
            proc.wait(timeout=10)


@contextmanager
def app_server():
    """The real app (fake model) on a fresh seeded database. Yields (url, db_path)."""
    port = free_port()
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "e2e.db")
        base = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
        env = {**base, "PORT": str(port), "E2E_DB": db}
        sink = None if os.environ.get("CTX_E2E_LOG") else subprocess.DEVNULL  # CTX_E2E_LOG=1 shows server output
        proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("e2e_app.py"))], env=env, cwd=tmp,
                                stdout=sink, stderr=sink)
        try:
            deadline = time.time() + 40
            while time.time() < deadline:
                try:
                    if httpx.get(f"http://127.0.0.1:{port}/", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.3)
            else:
                raise RuntimeError("app did not start")
            yield f"http://127.0.0.1:{port}/", db
        finally:
            proc.terminate()
            proc.wait(timeout=10)
