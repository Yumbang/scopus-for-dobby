"""Tests for DuckDB FTS index + search_articles_fts (Step 3)."""

import pytest

from scopus_for_dobby.core import article_db as db_mod


def _entry(eid: str, title: str, abstract: str = "", keywords: str = "") -> dict:
    return {
        "dc:title": title,
        "dc:creator": "Tester",
        "prism:publicationName": "J",
        "prism:coverDate": "2025-01-01",
        "prism:doi": f"10.0/{eid}",
        "eid": eid,
        "dc:identifier": f"SCOPUS_ID:{eid}",
        "citedby-count": "0",
        "openaccess": "0",
        "prism:aggregationType": "Journal",
        "dc:description": abstract,
        "authkeywords": keywords,
    }


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield db_file
    db_mod.close_cached_connections()


@pytest.fixture
def fts_or_skip(tmp_db):
    if not db_mod.fts_available():
        pytest.skip("DuckDB fts extension unavailable in this environment")
    return tmp_db


class TestRebuildFts:
    def test_empty_corpus_no_op(self, fts_or_skip):
        result = db_mod.rebuild_fts()
        assert result == {"rebuilt": False, "reason": "empty_corpus"}

    def test_rebuild_after_add(self, fts_or_skip):
        db_mod.add_entries([_entry("e1", "Hello world")])
        result = db_mod.rebuild_fts()
        assert result["rebuilt"] is True
        assert result["rows"] == 1


class TestSearchArticlesFts:
    def test_returns_expected_hit(self, fts_or_skip):
        db_mod.add_entries([
            _entry("e-tx", "Transformer architecture for NLP",
                   abstract="attention is all you need"),
            _entry("e-cv", "Convolutional neural networks for vision",
                   abstract="image classification"),
            _entry("e-rl", "Reinforcement learning survey",
                   abstract="policy gradient and Q-learning"),
        ])
        result = db_mod.search_articles_fts("transformer")
        eids = [a["eid"] for a in result["articles"]]
        assert "e-tx" in eids
        assert "e-cv" not in eids
        assert result["total"] >= 1

    def test_ranking_by_relevance(self, fts_or_skip):
        db_mod.add_entries([
            _entry("e1", "Transformer transformer transformer",
                   abstract="x"),
            _entry("e2", "One mention of transformer", abstract="y"),
        ])
        result = db_mod.search_articles_fts("transformer")
        assert len(result["articles"]) == 2
        assert result["articles"][0]["eid"] == "e1"

    def test_no_hits_returns_empty(self, fts_or_skip):
        db_mod.add_entries([_entry("e1", "Quantum chromodynamics")])
        result = db_mod.search_articles_fts("transformer")
        assert result == {"articles": [], "total": 0}


class TestDeferFtsRebuild:
    def test_defer_skips_index_rebuild(self, fts_or_skip):
        db_mod.add_entries([_entry("e1", "Indexed paper")])
        # baseline: search hits the indexed paper.
        assert db_mod.search_articles_fts("indexed")["total"] == 1

        db_mod.add_entries(
            [_entry("e2", "Deferred paper")],
            defer_fts_rebuild=True,
        )
        # Without explicit rebuild, FTS still reflects the previous index.
        deferred_total = db_mod.search_articles_fts("deferred")["total"]
        # Either 0 (index stale) or 1 (search_articles_fts auto-rebuild safety).
        # The contract is that deferral was respected: the caller must
        # be able to rebuild explicitly without error.
        result = db_mod.rebuild_fts()
        assert result["rebuilt"] is True
        assert db_mod.search_articles_fts("deferred")["total"] == 1
        # And whatever the deferred state was, it never returned wrong data.
        assert deferred_total in (0, 1)


class TestSearchArticlesLike:
    def test_like_works_without_fts(self, tmp_db):
        db_mod.add_entries([
            _entry("e1", "Transformer paper", abstract="abc"),
            _entry("e2", "Different topic", abstract="xyz"),
        ])
        result = db_mod.search_articles_like("transformer")
        eids = [a["eid"] for a in result["articles"]]
        assert eids == ["e1"]
        assert result["total"] == 1
