"""Lazy-spawn helper: ensure the HTTP daemon is running for CLI calls.

ADR-7 — every CLI subcommand goes through HTTP. ``ensure_daemon()`` checks
``~/.scopus-for-dobby/daemon.{pid,port}``; if no live daemon exists it
forks ``scopus-for-dobby serve --background``, waits up to ``BOOT_TIMEOUT``
on ``GET /health``, and returns the base URL. A file lock prevents two
concurrent CLIs from both spawning a daemon.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .serve import PID_FILE, PORT_FILE, daemon_endpoint

LOCK_FILE = Path.home() / ".scopus-for-dobby" / "daemon.lock"
LOG_FILE = Path.home() / ".scopus-for-dobby" / "daemon.log"
DEFAULT_PORT = 8765
BOOT_TIMEOUT = 5.0  # seconds — uvicorn cold-start budget
HEALTH_POLL = 0.05


class DaemonSpawnError(RuntimeError):
    """Raised when the daemon could not be spawned or did not become healthy."""


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _wait_for_health(base_url: str, deadline: float) -> bool:
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=0.5)
            if r.status_code == 200:
                return True
        except (httpx.RequestError, OSError):
            pass
        time.sleep(HEALTH_POLL)
    return False


def _spawn(port: int) -> None:
    """Fork ``scopus-for-dobby serve --background`` as a detached process."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "ab")  # noqa: SIM115 — handed to subprocess
    cmd = [sys.executable, "-m", "scopus_for_dobby.cli", "serve",
           "--background", "--port", str(port)]
    subprocess.Popen(  # noqa: S603
        cmd,
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def ensure_daemon(port: int = DEFAULT_PORT) -> str:
    """Return ``http://127.0.0.1:<port>`` for a live daemon, spawning if needed."""
    existing = daemon_endpoint()
    if existing:
        return existing

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lf:
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        except OSError as e:  # pragma: no cover — fcntl rarely fails locally
            raise DaemonSpawnError(f"could not acquire daemon lock: {e}") from e

        # Re-check under lock — a sibling CLI may have spawned it while we waited.
        existing = daemon_endpoint()
        if existing:
            return existing

        if not _port_free(port):
            raise DaemonSpawnError(
                f"port {port} is in use but no daemon PID file is registered. "
                f"Stop whatever is using {port} or wait for it to clear."
            )

        _spawn(port)

        base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + BOOT_TIMEOUT
        if not _wait_for_health(base_url, deadline):
            raise DaemonSpawnError(
                f"daemon did not become healthy within {BOOT_TIMEOUT}s. "
                f"Check {LOG_FILE} for errors."
            )
        return base_url


def stop_daemon(timeout: float = 5.0) -> bool:
    """Send SIGTERM to a running daemon. Returns True if a daemon was stopped."""
    import signal
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        with contextlib.suppress(FileNotFoundError):
            PID_FILE.unlink()
            PORT_FILE.unlink()
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError as e:
            if e.errno == errno.ESRCH:
                return True
        time.sleep(0.05)
    return False
