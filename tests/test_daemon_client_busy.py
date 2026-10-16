"""The CLI's side of the scheduler: waiting out a busy daemon, shared rate slots, --status."""

from __future__ import annotations

import httpx
import pytest

from scopus_for_dobby.cli import _http, serve
from scopus_for_dobby.utils import api_client


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=self)  # type: ignore[arg-type]


class _Scripted:
    """A stand-in httpx client that answers from a list, then repeats the last answer."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def request(self, method, path, **kwargs):
        self.calls += 1
        answer = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def no_sleep(monkeypatch):
    naps = []
    monkeypatch.setattr(_http.time, "sleep", naps.append)
    return naps


class TestBusyDaemon:
    def test_a_busy_answer_is_waited_out_and_retried(self, monkeypatch, no_sleep):
        client = _Scripted(
            [_Resp(503, headers={"Retry-After": "2"}), _Resp(503), _Resp(200, {"added": 1})]
        )
        monkeypatch.setattr(_http, "_client_factory", client)
        assert _http._post("/articles", {"entries": []}) == {"added": 1}
        assert client.calls == 3
        assert len(no_sleep) == 2 and all(0.5 <= n <= 8 for n in no_sleep)

    def test_a_daemon_that_never_frees_up_ends_in_a_clear_error(self, monkeypatch, no_sleep):
        client = _Scripted([_Resp(503)])
        monkeypatch.setattr(_http, "_client_factory", client)
        with pytest.raises(_http.DaemonBusyError, match="stayed busy"):
            _http._post("/articles", {})
        assert client.calls == _http._BUSY_RETRIES + 1

    def test_a_timeout_names_the_status_command(self, monkeypatch):
        monkeypatch.setattr(_http, "_client_factory", _Scripted([httpx.ReadTimeout("slow")]))
        with pytest.raises(_http.DaemonBusyError, match=r"serve --status"):
            _http._get("/articles")

    def test_ordinary_errors_still_map_as_before(self, monkeypatch):
        monkeypatch.setattr(
            _http, "_client_factory", _Scripted([_Resp(400, {"error": "Project not found: x"})])
        )
        with pytest.raises(ValueError, match="Project not found: x"):
            _http._get("/articles", project="x")

    def test_a_good_answer_is_not_retried(self, monkeypatch, no_sleep):
        client = _Scripted([_Resp(200, {"ok": True})])
        monkeypatch.setattr(_http, "_client_factory", client)
        assert _http._get("/health") == {"ok": True}
        assert client.calls == 1 and no_sleep == []


class TestSharedRateSlots:
    @pytest.fixture(autouse=True)
    def reset(self, monkeypatch):
        monkeypatch.setattr(_http, "_slot_endpoint", None)
        monkeypatch.setattr(api_client, "_slot_provider", None)
        monkeypatch.setattr(api_client, "_last_call", {})

    def test_no_daemon_means_no_answer(self, monkeypatch):
        monkeypatch.setattr(_http, "daemon_endpoint", lambda: None)
        assert _http.reserve_slot("/content/article/x") is None

    def test_the_daemons_answer_is_returned(self, monkeypatch):
        monkeypatch.setattr(_http, "daemon_endpoint", lambda: "http://127.0.0.1:1")
        posted = []

        def fake_post(url, json, timeout):
            posted.append((url, json))
            return _Resp(200, {"wait": 0.25})

        monkeypatch.setattr(httpx, "post", fake_post)
        assert _http.reserve_slot("/content/article/x") == 0.25
        assert posted == [("http://127.0.0.1:1/scheduler/slot", {"endpoint": "/content/article/x"})]

    def test_a_failing_daemon_is_given_up_on_for_the_process(self, monkeypatch):
        monkeypatch.setattr(_http, "daemon_endpoint", lambda: "http://127.0.0.1:1")
        attempts = []

        def failing(*a, **k):
            attempts.append(1)
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "post", failing)
        assert _http.reserve_slot("/x") is None
        assert _http.reserve_slot("/x") is None
        assert len(attempts) == 1  # not retried on every API call

    def test_an_absurd_wait_is_capped(self, monkeypatch):
        monkeypatch.setattr(_http, "daemon_endpoint", lambda: "http://127.0.0.1:1")
        monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(200, {"wait": 9999}))
        assert _http.reserve_slot("/x") == 30.0

    def test_throttle_obeys_the_provider(self, monkeypatch):
        naps = []
        monkeypatch.setattr(api_client.time, "sleep", naps.append)
        api_client.set_slot_provider(lambda endpoint: 0.4)
        api_client._throttle("/content/article/x")
        assert naps == [0.4]
        assert api_client._last_call == {}  # the local timer was not used

    def test_throttle_falls_back_to_its_own_timer(self, monkeypatch):
        naps = []
        monkeypatch.setattr(api_client.time, "sleep", naps.append)
        api_client.set_slot_provider(lambda endpoint: None)
        api_client._throttle("/content/article/x")
        api_client._throttle("/content/article/x")  # back to back: the local timer waits
        assert len(naps) == 1 and 0 < naps[0] <= 0.11
        assert "/content/article" in api_client._last_call


class TestStatusCommand:
    SAMPLE = {
        "version": "1.0.0",
        "pid": 4242,
        "uptime_s": 90061,
        "db": {"path": "/x/articles.duckdb", "size_bytes": 7_747_000_000, "wal_bytes": 600_000},
        "requests": {
            "total": 1234,
            "in_flight": 2,
            "by_status": {"2xx": 1200, "5xx": 4},
            "slow_after_s": 1.0,
            "slow_recent": [
                {
                    "at": "15:09:51",
                    "method": "POST",
                    "path": "/articles",
                    "status": 200,
                    "seconds": 4.2,
                }
            ],
        },
        "writer": {"waiting": 1, "busy_rejections": 3, "wait_limit_s": 20.0},
        "fts": {
            "stale": True,
            "behind": 12,
            "rebuilding": False,
            "last_rebuild_ms": 4200.0,
            "rows": 20441,
            "built_at": "2026-10-16 15:01:02",
            "background_worker": True,
            "last_error": None,
        },
        "rate": {"/content/article": {"interval_s": 0.11, "granted": 77, "queued_s": 0.0}},
    }

    def test_human_format_has_the_numbers_you_would_look_for(self):
        text = serve._format_status(self.SAMPLE)
        for needle in (
            "pid 4242",
            "up 1d 1h 1m",
            "7.2 GB",
            "1234 total",
            "2 in flight",
            "POST /articles -> 200  4.2s",
            "1 waiting · 3 told to retry",
            "STALE (12 events behind)",
            "last rebuild 4.2s for 20441 rows",
            "background worker on",
            "/content/article: 77 granted",
        ):
            assert needle in text, needle

    def test_a_fresh_idle_daemon(self):
        sample = {
            **self.SAMPLE,
            "requests": {**self.SAMPLE["requests"], "slow_recent": []},
            "fts": {**self.SAMPLE["fts"], "stale": False, "built_at": None},
            "rate": {},
        }
        text = serve._format_status(sample)
        assert "none (≥1s) since the daemon started" in text
        assert "fresh" in text and "never built" in text

    def test_no_daemon_is_reported(self, monkeypatch, capsys):
        monkeypatch.setattr(serve, "daemon_endpoint", lambda: None)
        with pytest.raises(SystemExit) as exc:
            serve._show_status()
        assert exc.value.code == 1
        assert "No daemon is running" in capsys.readouterr().err


def test_status_via_the_real_cli_against_a_real_app(monkeypatch, tmp_path):
    """`serve --status` end to end, through the router's test factory."""
    pytest.importorskip("fastapi")
    from click.testing import CliRunner
    from fastapi.testclient import TestClient

    from scopus_for_dobby.cli import cli
    from scopus_for_dobby.core import article_db as db_mod
    from scopus_for_dobby.server import build_app

    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "articles.duckdb")
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    with TestClient(build_app()) as app_client:
        monkeypatch.setattr(serve, "daemon_endpoint", lambda: "http://testserver")
        monkeypatch.setattr(
            httpx, "get", lambda url, timeout: app_client.get(url.replace("http://testserver", ""))
        )
        result = CliRunner().invoke(cli, ["serve", "--status"])
    db_mod.close_cached_connections()
    assert result.exit_code == 0, result.output
    assert "Search idx" in result.output and "Writers" in result.output
