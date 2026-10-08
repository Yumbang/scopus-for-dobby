"""Process liveness, stop and detach: the parts that differ on Windows.

``os.kill(pid, 0)`` is the POSIX "is it alive" idiom. On Windows it is
``TerminateProcess``, so the check killed the very daemon it asked about (and
a missing PID raised a bare ``OSError``). The Windows branch is exercised here
on any OS with a fake ``kernel32``; ``test_detach_and_stop_roundtrip`` runs the
real thing wherever the daemon stack is installed.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from scopus_for_dobby.cli import serve as serve_mod


class TestPidAlivePosix:
    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX branch")
    def test_this_process_is_alive(self):
        assert serve_mod._pid_alive(os.getpid()) is True

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX branch")
    def test_a_finished_process_is_not(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
        child.wait()
        assert serve_mod._pid_alive(child.pid) is False

    def test_nonsense_pids_are_not_alive(self):
        assert serve_mod._pid_alive(0) is False
        assert serve_mod._pid_alive(-5) is False


class _FakeKernel32:
    """Just enough of kernel32 for ``_pid_alive_windows``, scripted per test."""

    def __init__(self, *, handle, last_error=0, exit_code=259):
        self._handle, self._last_error, self._exit_code = handle, last_error, exit_code
        self.opened, self.closed = [], []

        class _Fn:
            restype = None

        self.OpenProcess = _Fn()
        self.OpenProcess.__call__ = None  # replaced below

    # ctypes function objects are called, so expose callables with the same names
    def install(self, monkeypatch):
        outer = self

        class _OpenProcess:
            restype = None

            def __call__(self, access, inherit, pid):
                outer.opened.append((access, inherit, pid))
                return outer._handle

        class _Dll:
            OpenProcess = _OpenProcess()

            @staticmethod
            def GetExitCodeProcess(handle, ref):
                ref._obj.value = outer._exit_code
                return 1

            @staticmethod
            def CloseHandle(handle):
                outer.closed.append(handle)

        monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: _Dll, raising=False)
        monkeypatch.setattr(ctypes, "get_last_error", lambda: outer._last_error, raising=False)


@pytest.fixture
def windows(monkeypatch):
    """Pretend to be Windows, and fail the test if anyone signals a process."""
    monkeypatch.setattr(serve_mod, "_IS_WINDOWS", True)

    def _no_kill(*args, **kwargs):  # pragma: no cover — failing is the point
        raise AssertionError(f"os.kill{args} would terminate the process on Windows")

    monkeypatch.setattr(os, "kill", _no_kill)
    return monkeypatch


class TestPidAliveWindows:
    def test_running_process(self, windows):
        fake = _FakeKernel32(handle=0xBEEF, exit_code=259)  # STILL_ACTIVE
        fake.install(windows)
        assert serve_mod._pid_alive(4242) is True
        assert fake.opened == [(0x1000, False, 4242)]  # query-only: it cannot kill
        assert fake.closed == [0xBEEF]

    def test_exited_process(self, windows):
        fake = _FakeKernel32(handle=0xBEEF, exit_code=0)
        fake.install(windows)
        assert serve_mod._pid_alive(4242) is False
        assert fake.closed == [0xBEEF]

    def test_missing_pid(self, windows):
        _FakeKernel32(handle=0, last_error=87).install(windows)  # ERROR_INVALID_PARAMETER
        assert serve_mod._pid_alive(4242) is False

    def test_someone_elses_process_is_alive(self, windows):
        _FakeKernel32(handle=0, last_error=5).install(windows)  # ERROR_ACCESS_DENIED
        assert serve_mod._pid_alive(4242) is True

    def test_daemon_endpoint_never_signals_on_windows(self, windows, tmp_path):
        pid_file, port_file = tmp_path / "daemon.pid", tmp_path / "daemon.port"
        pid_file.write_text("4242")
        port_file.write_text("18765")
        windows.setattr(serve_mod, "PID_FILE", pid_file)
        windows.setattr(serve_mod, "PORT_FILE", port_file)
        _FakeKernel32(handle=0, last_error=87).install(windows)  # no such process
        assert serve_mod.daemon_endpoint() is None  # and no os.kill, no OSError
        assert not pid_file.exists()  # the stale file was cleared


class TestIdleShutdownOnWindows:
    pytest.importorskip("fastapi")

    def test_windows_raises_the_signal_in_process(self, monkeypatch):
        from scopus_for_dobby.server import app as app_mod

        raised = []
        monkeypatch.setattr(app_mod.sys, "platform", "win32")
        monkeypatch.setattr(app_mod.signal, "raise_signal", raised.append)
        monkeypatch.setattr(
            os, "kill", lambda *a: (_ for _ in ()).throw(AssertionError("os.kill on Windows"))
        )
        app_mod._terminate_self()
        assert raised == [signal.SIGTERM]


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_detach_and_stop_roundtrip(tmp_path):
    """A real daemon: --detach returns once it answers, --stop removes it."""
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    port = _free_port()
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    cli = [sys.executable, "-m", "scopus_for_dobby.cli", "serve"]
    state = Path(tmp_path) / ".scopus-for-dobby"

    started = subprocess.run(  # noqa: S603
        [*cli, "--detach", "--port", str(port)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        assert started.returncode == 0, started.stderr
        assert f"127.0.0.1:{port}" in started.stdout
        assert (state / "daemon.pid").exists() and (state / "daemon.port").exists()

        health = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10)  # noqa: S310
        assert health.status == 200

        # --detach is idempotent, and talking to the daemon (the CLI probes its
        # PID on every command) must not hurt it.
        again = subprocess.run(  # noqa: S603
            [*cli, "--detach", "--port", str(port)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert again.returncode == 0 and "already running" in again.stdout
        stats = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "scopus_for_dobby.cli", "--json", "db", "stats"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert stats.returncode == 0, stats.stderr
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10)  # noqa: S310

        stopped = subprocess.run(  # noqa: S603
            [*cli, "--stop"], env=env, capture_output=True, text=True, timeout=60
        )
        assert stopped.returncode == 0 and "stopped" in stopped.stdout
        assert not (state / "daemon.pid").exists()
        assert not (state / "daemon.port").exists()
        again_stop = subprocess.run(  # noqa: S603
            [*cli, "--stop"], env=env, capture_output=True, text=True, timeout=60
        )
        assert "No daemon" in again_stop.stderr
    finally:
        pid_file = state / "daemon.pid"
        if pid_file.exists():  # pragma: no cover — only if an assertion failed above
            with __import__("contextlib").suppress(OSError, ValueError):
                os.kill(int(pid_file.read_text()), signal.SIGTERM)
            time.sleep(0.5)


class TestBootGrace:
    """A daemon writes its pid file before it binds the port; that gap must not look stale."""

    @pytest.fixture
    def registration(self, tmp_path, monkeypatch):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # noqa: S603
        pid_file, port_file = tmp_path / "daemon.pid", tmp_path / "daemon.port"
        pid_file.write_text(str(child.pid))
        port_file.write_text("1")  # nothing listens on port 1
        monkeypatch.setattr(serve_mod, "PID_FILE", pid_file)
        monkeypatch.setattr(serve_mod, "PORT_FILE", port_file)
        yield pid_file, port_file
        child.kill()
        child.wait()

    def test_a_starting_daemon_keeps_its_files(self, registration):
        pid_file, port_file = registration
        assert serve_mod.daemon_endpoint() is None  # not up yet
        assert pid_file.exists() and port_file.exists()  # but not declared dead

    def test_an_old_silent_pid_is_stale_and_cleared(self, registration):
        pid_file, port_file = registration
        old = time.time() - serve_mod._BOOT_GRACE - 5
        os.utime(pid_file, (old, old))
        assert serve_mod.daemon_endpoint() is None
        assert not pid_file.exists() and not port_file.exists()
