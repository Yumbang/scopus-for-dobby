"""`scopus-for-dobby serve` — run the HTTP daemon.

The daemon owns the only DuckDB connection; CLI mutations and the GUI
both attach via HTTP. Bind to 127.0.0.1 by default — this is a personal
machine tool, not a multi-user service.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
from pathlib import Path

import click

PID_FILE = Path.home() / ".scopus-for-dobby" / "daemon.pid"
PORT_FILE = Path.home() / ".scopus-for-dobby" / "daemon.port"


def _write_pid(port: int) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    PORT_FILE.write_text(str(port))


def _clear_pid() -> None:
    for f in (PID_FILE, PORT_FILE):
        with contextlib.suppress(FileNotFoundError):
            f.unlink()


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
    return f"http://127.0.0.1:{port}"


def register(cli):
    @cli.command(name="serve")
    @click.option("--host", default="127.0.0.1", show_default=True)
    @click.option("--port", default=8765, type=int, show_default=True)
    @click.option("--reload", is_flag=True, help="(dev) auto-reload on file changes")
    @click.option("--background", is_flag=True, hidden=True,
                  help="Internal: spawned by lazy-spawn; suppresses TTY banner.")
    @click.option("--idle-timeout", default=0.0, type=float,
                  help="Self-shutdown after N seconds with no requests "
                       "(0 = run forever). Default 600 in --background mode.")
    def serve(host: str, port: int, reload: bool, background: bool,
              idle_timeout: float):
        """Run the HTTP daemon. CLI/GUI clients attach to it for all DB access."""
        try:
            import uvicorn
        except ImportError:
            click.echo(
                "uvicorn not installed. Install with: "
                "uv pip install -e '.[gui-support]'",
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

        try:
            if not background:
                click.echo(f"scopus-for-dobby daemon → http://{host}:{port}")
            uvicorn.run(
                build_app(idle_timeout=effective_timeout or None),
                host=host,
                port=port,
                log_level="warning" if background else "info",
                reload=reload,
            )
        finally:
            _clear_pid()
