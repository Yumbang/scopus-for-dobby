"""Daemon idle-shutdown watchdog.

`serve --background` always passes an idle timeout, so this is the only
configuration the daemon ever runs in production — yet nothing covered it:
every test built the app with ``idle_timeout=None``. A regression here (the
handler failing to register, or never firing) would leave a uvicorn process
alive forever, or kill a daemon that is still in use.

``os.kill`` is patched out — the watchdog signals its own PID, which is the
test runner.
"""

import os
import signal
import time

import pytest

from scopus_for_dobby.core import article_db as db_mod

pytest.importorskip("fastapi")


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "articles.duckdb")
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield
    db_mod.close_cached_connections()


@pytest.fixture
def kills(monkeypatch):
    """Capture signals the watchdog sends instead of killing pytest."""
    sent = []
    real_kill = os.kill

    def _fake_kill(pid, sig):
        if pid == os.getpid():
            sent.append(sig)
            return
        real_kill(pid, sig)  # pragma: no cover — never happens in these tests

    monkeypatch.setattr(os, "kill", _fake_kill)
    return sent


def _client(idle_timeout):
    from fastapi.testclient import TestClient

    from scopus_for_dobby.server import build_app

    return TestClient(build_app(idle_timeout=idle_timeout))


def _wait_for(predicate, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class TestIdleWatchdog:
    def test_fires_after_idle_window(self, tmp_db, kills):
        with _client(0.2) as c:
            c.get("/health")
            assert _wait_for(lambda: kills), "watchdog never signalled"
        assert kills[0] == signal.SIGTERM

    def test_activity_defers_shutdown(self, tmp_db, kills):
        """Requests inside the window must keep pushing the deadline out."""
        with _client(0.6) as c:
            for _ in range(6):
                c.get("/health")
                time.sleep(0.1)
            # ~0.6 s of steady traffic, none of it a 0.6 s gap.
            assert not kills
            # Then go quiet and it should fire.
            assert _wait_for(lambda: kills)

    def test_disabled_when_no_timeout(self, tmp_db, kills):
        """Foreground `serve` and the tests pass None — must run forever."""
        with _client(None) as c:
            c.get("/health")
            time.sleep(0.4)
        assert not kills

    def test_zero_timeout_disabled(self, tmp_db, kills):
        """`--idle-timeout 0` documents 'run forever'."""
        with _client(0) as c:
            c.get("/health")
            time.sleep(0.4)
        assert not kills

    # NOT COVERED: the `activity["streams"] > 0` guard that keeps the daemon
    # alive while an SSE client is attached. `/events/stream` is an endless
    # generator, so `TestClient` blocks on teardown waiting for it to finish —
    # even after an explicit `response.close()`. Testing it needs either a
    # cancellable ASGI transport (pytest-asyncio) or a real spawned daemon;
    # both cost more than the guard is worth right now. Verify by hand with
    # `curl -N localhost:8765/events/stream` against a short --idle-timeout.

    def test_no_deprecation_warning(self, tmp_db, recwarn):
        """The startup hook must not go back to the deprecated on_event API."""
        with _client(0.2):
            pass
        messages = [str(w.message) for w in recwarn]
        assert not [m for m in messages if "on_event is deprecated" in m], messages
