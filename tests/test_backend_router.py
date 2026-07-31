"""Backend selection: in-process DuckDB vs. a running HTTP daemon.

The CLI ships without the daemon stack (``[gui]`` extra). ``cli/_client.py``
resolves which backend fulfils each subcommand's DB calls, once per process:
in-process by default, HTTP only when a daemon is already listening. These
tests pin that rule and prove real subcommands work over the in-process path.
"""

import json

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import _client, _output
from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import article_db as db_mod

SAMPLE = {
    "dc:title": "Router sample",
    "dc:creator": "Tester",
    "prism:publicationName": "J",
    "prism:coverDate": "2025-01-01",
    "prism:doi": "10.0/router",
    "eid": "2-s2.0-router-1",
    "dc:identifier": "SCOPUS_ID:router-1",
    "citedby-count": "7",
    "openaccess": "0",
    "prism:aggregationType": "Journal",
}


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    state.json_output = False
    state.repl_mode = False
    yield db_file
    db_mod.close_cached_connections()
    state.json_output = False


@pytest.fixture
def runner():
    return CliRunner()


class TestBackendSelection:
    def test_in_process_when_no_daemon(self, monkeypatch):
        """No daemon registered → calls go straight to core.article_db."""
        from scopus_for_dobby.cli import _http

        monkeypatch.setattr(_http, "_client_factory", None)
        monkeypatch.setattr(_client, "daemon_endpoint", lambda: None)
        _client.reset_backend()

        assert _client.backend() is db_mod
        assert _client.backend_name() == "in-process"

    def test_daemon_when_endpoint_live(self, monkeypatch):
        """A registered daemon owns the DuckDB file, so we must go through it."""
        from scopus_for_dobby.cli import _http

        monkeypatch.setattr(_http, "_client_factory", None)
        monkeypatch.setattr(_client, "daemon_endpoint", lambda: "http://127.0.0.1:8765")
        _client.reset_backend()

        assert _client.backend() is _http
        assert _client.backend_name() == "daemon"

    def test_resolution_is_cached(self, monkeypatch):
        """daemon_endpoint() may probe a TCP port — never do that per call."""
        from scopus_for_dobby.cli import _http

        monkeypatch.setattr(_http, "_client_factory", None)
        calls = []

        def _probe():
            calls.append(1)
            return None

        monkeypatch.setattr(_client, "daemon_endpoint", _probe)
        _client.reset_backend()

        _client.backend()
        _client.backend()
        getattr(_client, "list_articles")  # attribute access must not re-resolve  # noqa: B009
        assert len(calls) == 1

    def test_reset_backend_reresolves(self, monkeypatch):
        from scopus_for_dobby.cli import _http

        monkeypatch.setattr(_http, "_client_factory", None)
        monkeypatch.setattr(_client, "daemon_endpoint", lambda: None)
        _client.reset_backend()
        assert _client.backend() is db_mod

        monkeypatch.setattr(_client, "daemon_endpoint", lambda: "http://127.0.0.1:8765")
        _client.reset_backend()
        assert _client.backend() is _http

    def test_both_backends_implement_the_whole_api(self):
        """A name missing from one backend would work in-process and 500 over HTTP."""
        from scopus_for_dobby.cli import _http

        for name in _client._API:
            assert callable(getattr(db_mod, name, None)), f"core.article_db lacks {name}"
            assert callable(getattr(_http, name, None)), f"_http lacks {name}"

    def test_unknown_attribute_rejected(self):
        """Typos must not silently resolve off whichever backend happens to win."""
        with pytest.raises(AttributeError, match="_API"):
            getattr(_client, "DB_PATH")  # noqa: B009 — the lookup is what's under test


@pytest.mark.in_process
class TestSubcommandsInProcess:
    """End-to-end through Click with no daemon and no HTTP stack involved."""

    def test_backend_is_in_process(self, tmp_db):
        assert _client.backend_name() == "in-process"

    def test_add_list_roundtrip(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        result = runner.invoke(root_cli, ["--json", "db", "list"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert any(a["eid"] == SAMPLE["eid"] for a in data["articles"])

    def test_stats(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        result = runner.invoke(root_cli, ["--json", "db", "stats"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["total_articles"] == 1

    def test_mutation_roundtrip(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        result = runner.invoke(
            root_cli, ["--json", "db", "tag", "--eid", SAMPLE["eid"], "unread"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["tagged"] == 1
        assert "unread" in db_mod.get_article(SAMPLE["eid"])["_tags"]

    def test_collection_roundtrip(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        result = runner.invoke(
            root_cli, ["--json", "collection", "add", "c1", "--eid", SAMPLE["eid"]]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["added"] == 1
        assert "c1" in db_mod.list_collections()["collections"]


class TestLockErrorMessage:
    """The cost of running in-process: a second writer hits DuckDB's file lock."""

    def test_lock_error_is_actionable(self):
        msg = _output._friendly(
            RuntimeError("Could not set lock on file /x/articles.duckdb: Resource busy")
        )
        assert "locked by another process" in msg
        assert "scopus-for-dobby serve" in msg
        # The original text stays available for debugging.
        assert "Resource busy" in msg

    def test_unrelated_errors_pass_through(self):
        assert _output._friendly(ValueError("nope")) == "nope"
