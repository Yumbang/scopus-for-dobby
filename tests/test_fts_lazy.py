"""The full-text index goes stale on a write instead of being rebuilt on it.

Rebuilding after every add_entries (and before every index search) cost a full pass
over the corpus per `abstract` call or search-all page, queued behind the single
writer lock; with several agents writing, requests outlasted the CLI's 30 s timeout.
"""

from __future__ import annotations

import threading

import pytest

from scopus_for_dobby.core import article_db as db_mod


def _entry(n: int, title: str = "", abstract: str = "") -> dict:
    return {
        "dc:title": title or f"Paper {n}",
        "dc:creator": "Tester A.",
        "prism:publicationName": "Journal of Tests",
        "prism:coverDate": "2025-01-01",
        "eid": f"2-s2.0-fts-{n}",
        "dc:identifier": f"SCOPUS_ID:fts-{n}",
        "citedby-count": "0",
        "openaccess": "0",
        "prism:aggregationType": "Journal",
        "dc:description": abstract,
    }


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "articles.duckdb")
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield
    db_mod.set_fts_background(False)
    db_mod.close_cached_connections()


@pytest.fixture
def rebuilds(monkeypatch):
    """Count how often the real index build runs."""
    calls = []
    real = db_mod._rebuild_fts_locked

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(db_mod, "_rebuild_fts_locked", counting)
    return calls


def _need_fts():
    db_mod.add_entries([_entry(0)])
    if not db_mod.fts_available():
        pytest.skip("DuckDB fts extension unavailable here")


class TestWritesDoNotRebuild:
    def test_add_entries_leaves_the_index_stale(self, tmp_db, rebuilds):
        _need_fts()
        db_mod.add_entries([_entry(1)])
        db_mod.add_entries([_entry(2), _entry(3)])
        assert rebuilds == []
        assert db_mod.fts_status()["stale"] is True

    def test_defer_flag_is_still_accepted(self, tmp_db, rebuilds):
        db_mod.add_entries([_entry(1)], defer_fts_rebuild=True)
        db_mod.add_entries([_entry(2)], defer_fts_rebuild=False)
        assert rebuilds == []

    def test_empty_library_is_never_stale(self, tmp_db):
        assert db_mod.fts_status()["stale"] is False


class TestEnsureFresh:
    def test_builds_once_then_is_fresh(self, tmp_db, rebuilds):
        _need_fts()
        assert db_mod.ensure_fts_fresh()["rebuilt"] is True
        assert db_mod.fts_status()["stale"] is False
        assert db_mod.ensure_fts_fresh() == {"rebuilt": False, "reason": "fresh"}
        assert len(rebuilds) == 1

    def test_a_write_makes_it_stale_again(self, tmp_db, rebuilds):
        _need_fts()
        db_mod.ensure_fts_fresh()
        db_mod.add_entries([_entry(1)])
        status = db_mod.fts_status()
        assert status["stale"] is True and status["behind"] >= 1
        db_mod.ensure_fts_fresh()
        assert len(rebuilds) == 2

    def test_a_note_edit_counts_as_a_text_change(self, tmp_db):
        _need_fts()
        db_mod.ensure_fts_fresh()
        db_mod.set_note("2-s2.0-fts-0", "membrane")
        assert db_mod.fts_status()["stale"] is True

    def test_concurrent_callers_share_one_rebuild(self, tmp_db, rebuilds):
        _need_fts()
        threads = [threading.Thread(target=db_mod.ensure_fts_fresh) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(rebuilds) == 1

    def test_status_reports_the_last_rebuild(self, tmp_db):
        _need_fts()
        db_mod.ensure_fts_fresh()
        status = db_mod.fts_status()
        assert status["rows"] == 1 and status["last_rebuild_ms"] >= 0
        assert status["built_event_id"] == status["latest_event_id"]


class TestSearch:
    def test_without_a_worker_a_search_refreshes_first(self, tmp_db, rebuilds):
        _need_fts()
        db_mod.add_entries([_entry(1, "Nanofiltration membrane fouling")])
        result = db_mod.search_articles_fts("membrane")
        assert [a["eid"] for a in result["articles"]] == ["2-s2.0-fts-1"]
        assert len(rebuilds) == 1
        db_mod.search_articles_fts("membrane")
        assert len(rebuilds) == 1  # fresh: not rebuilt per search

    def test_with_a_worker_a_search_never_rebuilds_and_still_finds_new_papers(
        self, tmp_db, rebuilds
    ):
        _need_fts()
        db_mod.add_entries([_entry(1, "Reverse osmosis spacer design")])
        db_mod.ensure_fts_fresh()  # what the worker would have done
        rebuilds.clear()
        db_mod.set_fts_background(True)

        db_mod.add_entries([_entry(2, "Spacer geometry for osmosis modules")])  # not indexed yet
        result = db_mod.search_articles_fts("spacer")
        assert rebuilds == []  # the search did not wait for, or trigger, a rebuild
        assert {a["eid"] for a in result["articles"]} == {"2-s2.0-fts-1", "2-s2.0-fts-2"}
        assert result["total"] == 2

    def test_tail_ignores_accents_and_stopwords(self, tmp_db):
        _need_fts()
        db_mod.add_entries([_entry(1, "Hydrodynamics")])
        db_mod.ensure_fts_fresh()
        db_mod.set_fts_background(True)
        db_mod.add_entries([_entry(2, "The Rayleigh-Bénard problem")])
        found = db_mod.search_articles_fts("benard")["articles"]
        assert [a["eid"] for a in found] == ["2-s2.0-fts-2"]

    def test_an_updated_paper_is_found_by_its_new_text(self, tmp_db):
        _need_fts()
        db_mod.add_entries([_entry(1, "Old title about zeolites")])
        db_mod.ensure_fts_fresh()
        db_mod.set_fts_background(True)
        db_mod.add_entries([_entry(1, "New title about graphene")])  # same EID, new text
        found = db_mod.search_articles_fts("graphene")["articles"]
        assert [a["eid"] for a in found] == ["2-s2.0-fts-1"]

    def test_no_index_yet_falls_back_to_the_plain_match(self, tmp_db):
        _need_fts()
        db_mod.add_entries([_entry(1, "Photocatalysis on titanium dioxide")])
        db_mod.set_fts_background(True)  # worker owns rebuilds, none has run
        found = db_mod.search_articles_fts("titanium")["articles"]
        assert [a["eid"] for a in found] == ["2-s2.0-fts-1"]

    def test_results_stay_correct_while_a_rebuild_runs_beside_writers(self, tmp_db):
        _need_fts()
        db_mod.add_entries([_entry(n, f"Topic alpha {n}") for n in range(1, 40)])
        errors = []

        def rebuild_loop():
            try:
                for _ in range(4):
                    db_mod.rebuild_fts()
            except Exception as exc:  # pragma: no cover — failing is the point
                errors.append(exc)

        def write_loop():
            try:
                for n in range(100, 130):
                    db_mod.add_entries([_entry(n, f"Topic alpha {n}")])
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=rebuild_loop), threading.Thread(target=write_loop)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        db_mod.ensure_fts_fresh()
        assert db_mod.search_articles_fts("alpha", limit=500)["total"] == 69  # 39 + 30
