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
import subprocess
import sys
import time
from pathlib import Path

import click
from click.core import ParameterSource

PID_FILE = Path.home() / ".scopus-for-dobby" / "daemon.pid"
PORT_FILE = Path.home() / ".scopus-for-dobby" / "daemon.port"
LOG_FILE = Path.home() / ".scopus-for-dobby" / "daemon.log"

# The log is genuinely useful — a real one grew to 3.9 MB of DuckDB lock
# failures and enrichment errors, which is exactly what you want to find
# after the fact. It just has to stop growing forever: cap it and keep two
# generations (~6 MB worst case).
MAX_LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 2

# Fast liveness probe budget — a recycled PID passes the "is this PID alive"
# check but won't answer on the recorded port, so we confirm the port is
# actually accepting.
_PROBE_TIMEOUT = 0.5  # seconds

_IS_WINDOWS = sys.platform == "win32"

# A daemon writes its pid file just before uvicorn binds the port, so for a
# moment "pid alive, port silent" means "still starting", not "recycled PID".
# Inside this window the stale-state cleanup leaves the files alone; without it
# any CLI command run during boot deleted the daemon's own registration.
_BOOT_GRACE = 30.0  # seconds

# Silence is "run forever" only when asked for; a background daemon with no
# explicit --idle-timeout shuts itself down after this long without requests.
_BACKGROUND_IDLE_DEFAULT = 600.0


def _pid_alive(pid: int) -> bool:
    """Whether a process with this PID exists — without disturbing it.

    ``os.kill(pid, 0)`` is the POSIX idiom, and it is fatal on Windows: there
    every signal except the console Ctrl events is ``TerminateProcess``, so the
    "probe" kills the daemon it was asking about, and a PID that does not exist
    raises a bare ``OSError`` rather than ``ProcessLookupError``. Windows asks
    the kernel instead.
    """
    if pid <= 0:
        return False
    if not _IS_WINDOWS:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, just not ours to signal
        return True
    return _pid_alive_windows(pid)


def _pid_alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        # Access denied means the process exists and belongs to someone else.
        return ctypes.get_last_error() == error_access_denied
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def detached_popen_kwargs() -> dict:
    """``subprocess.Popen`` options that let a child outlive this process.

    POSIX starts a new session; Windows has no sessions, so the child gets its
    own console-less process group instead (``start_new_session`` is ignored).
    """
    if _IS_WINDOWS:
        return {
            "creationflags": (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        }
    return {"start_new_session": True}


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


def _port_is_free(port: int) -> bool:
    """True if we could bind this local port right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _first_free_port(start: int, tries: int = 4) -> int | None:
    """First bindable port at or after ``start``. None if all are taken."""
    for candidate in range(start, start + tries):
        if _port_is_free(candidate):
            return candidate
    return None


def _is_booting() -> bool:
    """True if the pid file is young enough that its daemon may not be listening yet."""
    try:
        return time.time() - PID_FILE.stat().st_mtime < _BOOT_GRACE
    except OSError:
        return False


def daemon_endpoint() -> str | None:
    """Return ``http://127.0.0.1:<port>`` if a live daemon PID file exists."""
    if not PID_FILE.exists() or not PORT_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
        port = int(PORT_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    if not _pid_alive(pid):
        _clear_pid()
        return None
    # A recycled PID passes the liveness check but belongs to an unrelated
    # process that won't answer on our port. Confirm the port is live before
    # reporting the daemon up; otherwise treat it as dead and clear stale state.
    # (Our own PID can never be a recycled foreign process, so skip the probe
    # there — this also keeps the in-process discovery path cheap.)
    if pid != os.getpid() and not _port_responds(port):
        if not _is_booting():
            _clear_pid()
        return None
    return f"http://127.0.0.1:{port}"


def stop_daemon(timeout: float = 10.0) -> bool:
    """Stop the running daemon and clear its files. True if one was stopped.

    A daemon is only signalled when its port answers, so a recycled PID is
    never killed. On Windows ``SIGTERM`` is ``TerminateProcess``: the daemon
    gets no chance to remove its own pid/port files, so they are cleared here.
    """
    if daemon_endpoint() is None:  # also clears stale files
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return False
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and _pid_alive(pid):
        time.sleep(0.1)
    stopped = not _pid_alive(pid)
    if stopped:
        _clear_pid()
    return stopped


def spawn_detached(port: int | None) -> subprocess.Popen:
    """Start ``serve --background`` as a detached child that never idles out."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "ab")  # noqa: SIM115 — handed to the child
    with contextlib.suppress(OSError):
        os.chmod(LOG_FILE, 0o600)
    cmd = [sys.executable, "-m", "scopus_for_dobby.cli", "serve", "--background"]
    cmd += ["--idle-timeout", "0"]
    if port is not None:
        cmd += ["--port", str(port)]
    return subprocess.Popen(  # noqa: S603
        cmd,
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        **detached_popen_kwargs(),
    )


def _detach(ctx: click.Context, port: int, boot_timeout: float = 30.0) -> None:
    """``serve --detach``: spawn the daemon, wait until it answers, report."""
    existing = daemon_endpoint()
    if existing:
        click.echo(f"Daemon already running at {existing}")
        return
    explicit = ctx.get_parameter_source("port") is ParameterSource.COMMANDLINE
    child = spawn_detached(port if explicit else None)
    deadline = time.monotonic() + boot_timeout
    while time.monotonic() < deadline:
        endpoint = daemon_endpoint()
        if endpoint:
            click.echo(f"Daemon started at {endpoint}")
            return
        if child.poll() is not None:
            break  # the child exited: it will not come up
        time.sleep(0.2)
    click.echo(
        f"The daemon did not come up within {boot_timeout:.0f}s. See {LOG_FILE} for why.",
        err=True,
    )
    sys.exit(1)


def _human_bytes(n: int | None) -> str:
    if n is None:
        return "?"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"  # pragma: no cover


def _format_status(d: dict) -> str:
    up = d["uptime_s"]
    lines = [
        f"Daemon {d['version']} | pid {d['pid']} | up {up // 86400}d {up % 86400 // 3600}h "
        f"{up % 3600 // 60}m",
        f"Database   {_human_bytes(d['db']['size_bytes'])} "
        f"(+{_human_bytes(d['db']['wal_bytes'])} WAL)  {d['db']['path']}",
    ]
    r = d["requests"]
    codes = " ".join(f"{k} {v}" for k, v in sorted(r["by_status"].items())) or "none yet"
    lines.append(f"Requests   {r['total']} total | {r['in_flight']} in flight | {codes}")
    if r["slow_recent"]:
        lines.append(f"Slow (over {r['slow_after_s']:g}s), most recent last:")
        lines += [
            f"   {x['at']}  {x['method']} {x['path']} -> {x['status']}  {x['seconds']}s"
            for x in r["slow_recent"][-8:]
        ]
    else:
        lines.append(f"Slow       none (over {r['slow_after_s']:g}s) since the daemon started")
    w = d["writer"]
    lines.append(
        f"Writers    {w['waiting']} waiting | {w['busy_rejections']} told to retry "
        f"(a writer queues at most {w['wait_limit_s']:g}s)"
    )
    f = d["fts"]
    state = "STALE" if f["stale"] else "fresh"
    if f["stale"] and f["behind"] is not None:
        state += f" ({f['behind']} events behind)"
    if f["rebuilding"]:
        state += ", rebuilding now"
    cost = (
        f"last rebuild {f['last_rebuild_ms'] / 1000:.1f}s for {f['rows']} rows at {f['built_at']}"
        if f["built_at"]
        else "never built"
    )
    worker = "background worker on" if f["background_worker"] else "no background worker"
    lines.append(f"Search idx {state} | {cost} | {worker}")
    if f.get("last_error"):
        lines.append(f"           last rebuild error: {f['last_error']}")
    if d["rate"]:
        lines.append(
            "Rate slots "
            + " | ".join(f"{k}: {v['granted']} granted" for k, v in d["rate"].items())
        )
    return "\n".join(lines)


def _show_status() -> None:
    import httpx

    from ._output import output
    from ._state import state

    endpoint = daemon_endpoint()
    if not endpoint:
        click.echo("No daemon is running.", err=True)
        sys.exit(1)
    try:
        r = httpx.get(f"{endpoint}/admin/status", timeout=10.0)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        click.echo(f"The daemon did not report its status: {exc}", err=True)
        sys.exit(1)
    data = r.json()
    if state.json_output:
        output(data)
    else:
        click.echo(_format_status(data))


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
    @click.option(
        "--detach",
        is_flag=True,
        help="Start the daemon in the background and return once it answers "
        "(works on macOS, Linux and Windows). It runs until `serve --stop`.",
    )
    @click.option("--stop", is_flag=True, help="Stop the running daemon and exit.")
    @click.option(
        "--status",
        is_flag=True,
        help="Show what the running daemon is doing (load, slow requests, writer queue, "
        "search index, rate limits) and exit.",
    )
    @click.pass_context
    def serve(
        ctx,
        host: str,
        port: int,
        reload: bool,
        background: bool,
        idle_timeout: float,
        detach: bool,
        stop: bool,
        status: bool,
    ):
        """Run the HTTP daemon. CLI/GUI clients attach to it for all DB access."""
        if sum([stop, detach, status]) > 1:
            raise click.UsageError("--stop, --detach and --status are mutually exclusive.")
        if status:
            _show_status()
            return
        if stop:
            if stop_daemon():
                click.echo("Daemon stopped.")
            else:
                click.echo("No daemon is running.", err=True)
            return
        if detach:
            _detach(ctx, port)
            return
        try:
            import uvicorn
        except ImportError:
            click.echo(
                "Starting a daemon requires the optional [gui] extra.\n"
                "Install it with: uv pip install -e '.[gui]'",
                err=True,
            )
            sys.exit(1)

        from scopus_for_dobby.server import build_app

        existing = daemon_endpoint()
        if existing:
            click.echo(f"Daemon already running at {existing}", err=True)
            sys.exit(1)

        # The default port is a guess, not a request: 8765 is popular and this
        # machine may already have something on it. An explicit --port is a
        # request, so it is left to fail loudly rather than silently moving.
        # `daemon.port` is what clients read, so a shifted port is still found.
        if ctx.get_parameter_source("port") is not ParameterSource.COMMANDLINE:
            free = _first_free_port(port)
            if free is None:
                click.echo(
                    f"Ports {port}-{port + 3} are all in use. "
                    f"Free one, or pass --port explicitly.",
                    err=True,
                )
                sys.exit(1)
            if free != port:
                click.echo(f"Port {port} is busy; using {free}.", err=True)
                port = free

        _write_pid(port)

        def _on_exit(signum, frame):
            _clear_pid()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _on_exit)
        signal.signal(signal.SIGINT, _on_exit)

        effective_timeout = idle_timeout
        idle_given = ctx.get_parameter_source("idle_timeout") is ParameterSource.COMMANDLINE
        if background and not idle_given:
            effective_timeout = _BACKGROUND_IDLE_DEFAULT  # the old lazy-spawn window

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
                build_app(idle_timeout=effective_timeout or None, fts_worker=True),
                host=host,
                port=port,
                log_level="warning" if background else "info",
                reload=reload,
                **log_kwargs,
            )
        finally:
            _clear_pid()
