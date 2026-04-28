"""Shared pytest fixtures.

The CLI now routes every subcommand through HTTP (ADR-7). For tests
this would mean lazy-spawning an actual ``scopus-for-dobby serve``
process, which is slow, flaky, and pollutes the user's home directory.

Instead, ``cli_http_in_process`` (autouse) installs a factory that
returns a FastAPI ``TestClient`` bound to ``build_app()`` — same
ASGI stack, no real network, no real subprocess.
"""

from __future__ import annotations

import contextlib

import pytest


@pytest.fixture(autouse=True)
def cli_http_in_process(monkeypatch):
    """Route every CLI HTTP call through an in-process TestClient."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from scopus_for_dobby.cli import _client as cli_client
    from scopus_for_dobby.server import build_app

    client = TestClient(build_app())

    @contextlib.contextmanager
    def _factory():
        yield client

    monkeypatch.setattr(cli_client, "_client_factory", _factory)
    yield
    client.close()
