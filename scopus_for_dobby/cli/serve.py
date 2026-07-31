"""`scopus-for-dobby serve` — run the HTTP daemon.

The daemon owns the only DuckDB connection; CLI mutations and the GUI
both attach via HTTP. Bind to 127.0.0.1 by default — this is a personal
machine tool, not a multi-user service.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import socket
import sys
from pathlib import Path

import click

PID_FILE = Path.home() / ".scopus-for-dobby" / "daemon.pid"
PORT_FILE = Path.home() / ".scopus-for-dobby" / "daemon.port"
LOG_FILE = Path.home() / ".scopus-for-dobby" / "daemon.log"

# The log is genuinely useful — a real one grew to 3.9 MB of DuckDB lock
# failures and enrichment errors, which is exactly what you want to find
# after the fact. It just has to stop growing forever: cap it and keep two
# generations (~6 MB worst case).
MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 2

# Fast liveness probe budget — a recycled PID passes os.kill(pid, 0) but won't
# answer on the recorded port, so we confirm the port is actually accepting.
_PROBE_TIMEOUT = 0.5  # seconds


def _write_pid(port: int) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    PORT_FILE.write_text(str(port))


def _clear_pid() -> None:
    for f in (PID_FILE, PORT_FILE):
        with contextlib.suppress(FileNotFoundError):
            f.unlink()


def configure_file_logging() -> logging.Handler:
    """Send this process's logs to a size-capped, rotating ``daemon.log``.

    The daemon runs detached, so its logs are the only diagnostic available.
    Whoever spawns it may or may not redirect stdout/stderr — the macOS GUI
    sends both to /dev/null — so the daemon takes responsibility for its own
    log rather than relying on the parent's redirection.
    """
    from logging.handlers import RotatingFileHandler

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # The log echoes request paths and error detail; keep it owner-only,
    # mirroring config.json (utils/api_client.py).
    with contextlib.suppress(OSError):
        os.chmod(LOG_FILE, 0o600)
    return handler


def _port_responds(port: int) -> bool:
    """Return True if something accepts a TCP connection on the local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(_PROBE_TIMEOUT)
        try:
            s.connect(("127.0.0.1", port))
        except OSError:
            return False
    return True


def daemon_endpoint() -> str | None:
    """Return ``http://127.0.0.1:<port>`` if a live daemon PID file exists."""
    if not PID_FILE.exists() or not PORT_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        port = int(PORT_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        _clear_pid()
        return None
    except PermissionError:
        # Process exists but we can't signal it — assume alive.
        pass
    # A recycled PID survives os.kill(pid, 0) but belongs to an unrelated
    # process that won't answer on our port. Confirm the port is live before
    # reporting the daemon up; otherwise treat it as dead and clear stale state.
    # (Our own PID can never be a recycled foreign process, so skip the probe
    # there — this also keeps the in-process discovery path cheap.)
    if pid != os.getpid() and not _port_responds(port):
        _clear_pid()
        return None
    return f"http://127.0.0.1:{port}"


def register(cli):
    @cli.command(name="serve")
    @click.option("--host", default="127.0.0.1", show_default=True)
    @click.option("--port", default=8765, type=int, show_default=True)
    @click.option("--reload", is_flag=True, help="(dev) auto-reload on file changes")
    @click.option(
        "--background",
        is_flag=True,
        hidden=True,
        help="Internal: spawned by lazy-spawn; suppresses TTY banner.",
    )
    @click.option(
        "--idle-timeout",
        default=0.0,
        type=float,
        help="Self-shutdown after N seconds with no requests "
        "(0 = run forever). Default 600 in --background mode.",
    )
    def serve(host: str, port: int, reload: bool, background: bool, idle_timeout: float):
        """Run the HTTP daemon. CLI/GUI clients attach to it for all DB access."""
        try:
            import uvicorn
        except ImportError:
            click.echo(
                "The daemon requires the optional [gui] extra.\n"
                "Install it with: uv pip install -e '.[cli,export,gui]'",
                err=True,
            )
            sys.exit(1)

        from scopus_for_dobby.server import build_app

        existing = daemon_endpoint()
        if existing:
            click.echo(f"Daemon already running at {existing}", err=True)
            sys.exit(1)

        _write_pid(port)

        def _on_exit(signum, frame):
            _clear_pid()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _on_exit)
        signal.signal(signal.SIGINT, _on_exit)

        effective_timeout = idle_timeout
        if background and effective_timeout == 0.0:
            effective_timeout = 600.0  # 10-minute idle window for lazy-spawn

        log_kwargs = {}
        if background:
            # Detached: own the log file so it rotates instead of growing
            # without bound, and so it works even when the spawner throws our
            # stdout away (the macOS GUI does). log_config=None stops uvicorn
            # from replacing the handler we just installed.
            configure_file_logging()
            log_kwargs["log_config"] = None
        else:
            click.echo(f"scopus-for-dobby daemon → http://{host}:{port}")

        try:
            uvicorn.run(
                build_app(idle_timeout=effective_timeout or None),
                host=host,
                port=port,
                log_level="warning" if background else "info",
                reload=reload,
                **log_kwargs,
            )
        finally:
            _clear_pid()
