"""Shared fixtures.

The CLI resolves one of two DB backends per process (see
``scopus_for_dobby.cli._client``): in-process DuckDB, or HTTP to a running
daemon. Both must keep working, so:

* ``cli_http_in_process`` (autouse) points the router at the daemon backend
  and serves it from a FastAPI ``TestClient`` — same ASGI stack, no real
  network, no spawned ``serve`` process, no pollution of the user's home.
* Tests marked ``@pytest.mark.in_process`` opt out and exercise the
  in-process backend instead.
* If the optional ``[gui]`` extra is not installed there is no daemon stack
  to test against, so the fixture stands down and the whole suite runs
  in-process — which is exactly how a CLI-only install behaves.
"""

from __future__ import annotations

import contextlib
import importlib.util

import pytest

HAS_DAEMON_STACK = importlib.util.find_spec("fastapi") is not None


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "in_process: run against the in-process DuckDB backend, not the daemon",
    )


@pytest.fixture(autouse=True)
def cli_http_in_process(request, monkeypatch):
    """Route CLI DB calls through an in-process TestClient by default."""
    from scopus_for_dobby.cli import _client as cli_client

    cli_client.reset_backend()

    if not HAS_DAEMON_STACK or request.node.get_closest_marker("in_process"):
        # No factory installed → the router falls through to core.article_db.
        #
        # Neutralize daemon discovery explicitly rather than relying on there
        # being no daemon: `daemon_endpoint()` reads the *developer's real*
        # ~/.scopus-for-dobby/daemon.{pid,port}, so with a daemon running — as
        # any GUI user or anyone mid-`serve` will have — the router would pick
        # the HTTP backend and these tests would fail for reasons that have
        # nothing to do with the code under test.
        monkeypatch.setattr(cli_client, "daemon_endpoint", lambda: None)
        yield
        cli_client.reset_backend()
        return

    from fastapi.testclient import TestClient

    from scopus_for_dobby.cli import _http
    from scopus_for_dobby.server import build_app

    client = TestClient(build_app())

    @contextlib.contextmanager
    def _factory():
        yield client

    monkeypatch.setattr(_http, "_client_factory", _factory)
    yield
    client.close()
    cli_client.reset_backend()
