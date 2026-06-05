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
# uvicorn cold-start budget. The first /health triggers DuckDB init + an FTS
# extension install (possibly a network download), so the default is generous
# and overridable via SCOPUS_FOR_DOBBY_BOOT_TIMEOUT.
BOOT_TIMEOUT = 15.0  # seconds
HEALTH_POLL = 0.05
HEALTH_TIMEOUT = 2.0  # per-request /health budget — first call does FTS install
PORT_RETRIES = 3  # bounded attempts when a candidate port loses a TOCTOU race


def _boot_timeout() -> float:
    """Boot budget, overridable via ``SCOPUS_FOR_DOBBY_BOOT_TIMEOUT``."""
    raw = os.environ.get("SCOPUS_FOR_DOBBY_BOOT_TIMEOUT")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return BOOT_TIMEOUT


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
            r = httpx.get(f"{base_url}/health", timeout=HEALTH_TIMEOUT)
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
    # The daemon log can echo request paths/params; keep it owner-only, mirroring
    # config.json (utils/api_client.py).
    with contextlib.suppress(OSError):
        os.chmod(LOG_FILE, 0o600)
    cmd = [
        sys.executable,
        "-m",
        "scopus_for_dobby.cli",
        "serve",
        "--background",
        "--port",
        str(port),
    ]
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

        # Hold the lock through spawn + health so a concurrently waiting CLI
        # never observes "no endpoint" and forks a duplicate. _port_free() ->
        # _spawn() is non-atomic, so if a candidate port is claimed between the
        # check and the bind, retry with the next port (bounded).
        boot_timeout = _boot_timeout()
        last_error = ""
        for attempt in range(PORT_RETRIES):
            candidate = port + attempt
            if not _port_free(candidate):
                last_error = f"port {candidate} is in use but no daemon PID file is registered"
                continue

            _spawn(candidate)

            base_url = f"http://127.0.0.1:{candidate}"
            deadline = time.monotonic() + boot_timeout
            if _wait_for_health(base_url, deadline):
                # Health only answers once uvicorn is serving, which the daemon
                # reaches strictly after writing its pid/port file — so the
                # endpoint is registered and visible to siblings by now.
                return base_url
            last_error = f"daemon on port {candidate} did not become healthy within {boot_timeout}s"

        raise DaemonSpawnError(
            f"could not start daemon after {PORT_RETRIES} attempt(s): "
            f"{last_error}. Check {LOG_FILE} for errors."
        )


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
