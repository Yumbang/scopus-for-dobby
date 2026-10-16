"""The daemon as a scheduler: pacing, queueing, visibility, and the index worker.

Five agents sharing one library produced timeouts: each write rebuilt the whole
full-text index behind a single writer lock, and each process paced the external APIs
with its own timer. These cover the pieces that replaced that: shared rate slots, a
bounded wait for the writer (answered "busy, retry"), request statistics, and the
background rebuild.
"""

from __future__ import annotations

import logging
import threading
import time

import pytest

from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.server import scheduler

pytest.importorskip("fastapi")


def _entry(n: int, title: str = "") -> dict:
    return {
        "dc:title": title or f"Paper {n}",
        "dc:creator": "Tester A.",
        "prism:publicationName": "Journal of Tests",
        "prism:coverDate": "2025-01-01",
        "eid": f"2-s2.0-sch-{n}",
        "dc:identifier": f"SCOPUS_ID:sch-{n}",
        "citedby-count": "0",
        "openaccess": "0",
        "prism:aggregationType": "Journal",
    }


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "articles.duckdb")
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield
    db_mod.set_fts_background(False)
    db_mod.close_cached_connections()


def _client(**kwargs):
    from fastapi.testclient import TestClient

    from scopus_for_dobby.server import build_app

    return TestClient(build_app(**kwargs))


def _wait_for(predicate, timeout=8.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class TestSlotLimiter:
    def test_consecutive_callers_get_consecutive_slots(self):
        limiter = scheduler.SlotLimiter({"/content/article": 0.1})
        waits = [limiter.reserve("/content/article/doi/10.1/x") for _ in range(4)]
        assert waits[0] == pytest.approx(0, abs=0.02)
        # Asked back to back: each is a slot later than the last, not the same answer.
        assert [round(w, 1) for w in waits] == [0.0, 0.1, 0.2, 0.3]

    def test_an_idle_endpoint_has_no_queue(self):
        limiter = scheduler.SlotLimiter({"/content/article": 0.05})
        limiter.reserve("/content/article/x")
        time.sleep(0.12)
        assert limiter.reserve("/content/article/x") == pytest.approx(0, abs=0.02)

    def test_endpoints_are_paced_independently(self):
        limiter = scheduler.SlotLimiter({"/content/article": 0.5, "/content/abstract": 0.5})
        limiter.reserve("/content/article/x")
        assert limiter.reserve("/content/abstract/x") == pytest.approx(0, abs=0.02)

    def test_unlimited_endpoint_never_waits(self):
        assert scheduler.SlotLimiter({"/a": 1.0}).reserve("/somewhere/else") == 0.0

    def test_threads_never_share_a_slot(self):
        limiter = scheduler.SlotLimiter({"/x": 0.01})
        waits, lock = [], threading.Lock()

        def ask():
            w = limiter.reserve("/x")
            with lock:
                waits.append(w)

        threads = [threading.Thread(target=ask) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len({round(w, 4) for w in waits}) == 20


class TestRequestStats:
    def test_counts_and_slow_list(self):
        stats = scheduler.RequestStats(slow_after=1.0, keep=2)
        for seconds in (0.1, 1.5, 2.0, 3.0):
            stats.begin()
            stats.end("GET", f"/p{seconds}", 200, seconds)
        stats.begin()
        stats.end("POST", "/boom", 503, 0.2)
        snap = stats.snapshot()
        assert snap["total"] == 5 and snap["in_flight"] == 0
        assert snap["by_status"] == {"2xx": 4, "5xx": 1}
        assert [s["path"] for s in snap["slow_recent"]] == ["/p2.0", "/p3.0"]  # newest 2


class TestStatusEndpoint:
    def test_shape(self, tmp_db):
        with _client() as c:
            c.post("/articles", json={"entries": [_entry(1)]})
            body = c.get("/admin/status").json()
        assert body["requests"]["total"] >= 1
        assert body["writer"]["wait_limit_s"] == db_mod.WRITE_WAIT
        assert body["fts"]["stale"] is True
        assert body["db"]["path"].endswith("articles.duckdb")
        assert isinstance(body["rate"], dict)

    def test_slow_requests_are_logged_without_their_query_string(self, tmp_db, caplog):
        with caplog.at_level(logging.WARNING), _client(slow_request=0.0) as c:
            c.get("/articles", params={"query": "something private"})
        slow = [r.getMessage() for r in caplog.records if "slow request" in r.getMessage()]
        assert any("GET /articles" in m for m in slow)
        assert not any("private" in m for m in slow)

    def test_slot_endpoint_reserves_and_validates(self, tmp_db):
        with _client() as c:
            first = c.post("/scheduler/slot", json={"endpoint": "/content/article/doi/1"}).json()
            second = c.post("/scheduler/slot", json={"endpoint": "/content/article/doi/2"}).json()
            assert second["wait"] > first["wait"]
            assert c.post("/scheduler/slot", json={}).status_code == 400
            granted = c.get("/admin/status").json()["rate"]["/content/article"]["granted"]
            assert granted == 2


class TestBusyWriter:
    def test_a_writer_that_cannot_get_the_slot_is_told_503_with_a_retry_hint(
        self, tmp_db, monkeypatch
    ):
        monkeypatch.setattr(db_mod, "WRITE_WAIT", 0.2)
        release = threading.Event()
        held = threading.Event()

        def hog():
            with db_mod._write_lock:
                held.set()
                release.wait(10)

        t = threading.Thread(target=hog)
        t.start()
        try:
            assert held.wait(5)
            with _client() as c:
                r = c.post("/articles", json={"entries": [_entry(1)]})
                assert r.status_code == 503
                assert r.headers["Retry-After"] == "2"
                assert r.json()["type"] == "WriteBusy"
                assert db_mod.writer_stats()["busy_rejections"] >= 1
        finally:
            release.set()
            t.join()

    def test_writes_resume_once_the_slot_frees(self, tmp_db):
        with _client() as c:
            assert c.post("/articles", json={"entries": [_entry(1)]}).status_code == 200

    def test_reads_are_not_blocked_by_a_busy_writer(self, tmp_db, monkeypatch):
        monkeypatch.setattr(db_mod, "WRITE_WAIT", 5)
        db_mod.add_entries([_entry(1)])
        release, held = threading.Event(), threading.Event()

        def hog():
            with db_mod._write_lock:
                held.set()
                release.wait(10)

        t = threading.Thread(target=hog)
        t.start()
        try:
            assert held.wait(5)
            with _client() as c:
                started = time.monotonic()
                assert c.get("/articles").status_code == 200
                assert time.monotonic() - started < 2
        finally:
            release.set()
            t.join()


class TestBackgroundIndexWorker:
    def test_a_burst_of_writes_costs_one_rebuild_after_it_goes_quiet(self, tmp_db, monkeypatch):
        db_mod.add_entries([_entry(0)])
        if not db_mod.fts_available():
            pytest.skip("DuckDB fts extension unavailable here")
        rebuilds = []
        real = db_mod._rebuild_fts_locked

        def counting():
            rebuilds.append(1)
            return real()

        monkeypatch.setattr(db_mod, "_rebuild_fts_locked", counting)
        with _client(fts_worker=True, fts_debounce=0.4, fts_poll=0.05) as c:
            for n in range(1, 13):  # a burst, faster than the debounce
                c.post("/articles", json={"entries": [_entry(n, f"Burst topic {n}")]})
                time.sleep(0.05)
            # Right after the burst the index lags, yet the paper is already searchable.
            hit = c.get("/search/fts", params={"query": "burst"}).json()
            assert hit["total"] == 12
            assert _wait_for(lambda: not db_mod.fts_status()["stale"])
            assert len(rebuilds) == 1
            assert c.get("/search/fts", params={"query": "burst"}).json()["total"] == 12
            assert c.get("/admin/status").json()["fts"]["background_worker"] is True
        assert db_mod._fts_background is False  # the worker's claim ends with the app

    def test_a_long_burst_is_not_starved_forever(self, tmp_db):
        db_mod.add_entries([_entry(0)])
        if not db_mod.fts_available():
            pytest.skip("DuckDB fts extension unavailable here")
        with _client(fts_worker=True, fts_debounce=30, fts_max_wait=0.5, fts_poll=0.05) as c:
            stop = threading.Event()

            def keep_writing():
                n = 1
                while not stop.is_set():
                    c.post("/articles", json={"entries": [_entry(n)]})
                    n += 1
                    time.sleep(0.02)

            t = threading.Thread(target=keep_writing)
            t.start()
            try:
                # Writes never go quiet for 30 s, so only max_wait can trigger the rebuild.
                assert _wait_for(lambda: db_mod.fts_status()["built_at"] is not None, timeout=10)
            finally:
                stop.set()
                t.join()
