"""Daemon discovery + lazy-spawn tests (ADR-7).

The old daemon-guard refused CLI commands when the daemon was up. Under
ADR-7 there is no guard: every subcommand routes through HTTP, the
daemon is lazy-spawned on demand. These tests cover the discovery
helpers (``daemon_endpoint``, ``ensure_daemon``) which gate that flow.
"""

from __future__ import annotations

import os

import pytest

from scopus_for_dobby.cli import _daemon as daemon_mod
from scopus_for_dobby.cli import serve as serve_mod


@pytest.fixture
def patched_paths(tmp_path, monkeypatch):
    pid = tmp_path / "daemon.pid"
    port = tmp_path / "daemon.port"
    lock = tmp_path / "daemon.lock"
    log = tmp_path / "daemon.log"
    monkeypatch.setattr(serve_mod, "PID_FILE", pid)
    monkeypatch.setattr(serve_mod, "PORT_FILE", port)
    monkeypatch.setattr(daemon_mod, "PID_FILE", pid)
    monkeypatch.setattr(daemon_mod, "PORT_FILE", port)
    monkeypatch.setattr(daemon_mod, "LOCK_FILE", lock)
    monkeypatch.setattr(daemon_mod, "LOG_FILE", log)
    return pid, port


def test_daemon_endpoint_returns_url_when_pid_alive(patched_paths):
    pid_file, port_file = patched_paths
    pid_file.write_text(str(os.getpid()))
    port_file.write_text("18765")
    assert serve_mod.daemon_endpoint() == "http://127.0.0.1:18765"


def test_daemon_endpoint_clears_stale_pid(patched_paths):
    pid_file, port_file = patched_paths
    pid_file.write_text("999999")
    port_file.write_text("18765")
    assert serve_mod.daemon_endpoint() is None
    assert not pid_file.exists()


def test_ensure_daemon_returns_existing_endpoint_without_spawn(
    patched_paths, monkeypatch,
):
    pid_file, port_file = patched_paths
    pid_file.write_text(str(os.getpid()))
    port_file.write_text("18765")

    spawned = []
    monkeypatch.setattr(daemon_mod, "_spawn",
                        lambda port: spawned.append(port))

    assert daemon_mod.ensure_daemon() == "http://127.0.0.1:18765"
    assert spawned == []  # short-circuited; no fork attempted
