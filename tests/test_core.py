"""Unit tests for scopus-for-dobby core modules.

These tests use synthetic data and do not make API calls.
"""

import os

import pytest

from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.core import export as export_mod
from scopus_for_dobby.core import session as session_mod
from scopus_for_dobby.core.session import Session

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_SEARCH_ENTRY = {
    "dc:title": "Deep Learning for Image Segmentation: A Survey",
    "dc:creator": "Kim J.",
    "prism:publicationName": "IEEE Transactions on Pattern Analysis",
    "prism:coverDate": "2024-03-15",
    "prism:volume": "46",
    "prism:issueIdentifier": "3",
    "prism:pageRange": "1234-1256",
    "prism:doi": "10.1109/TPAMI.2024.001234",
    "eid": "2-s2.0-85012345678",
    "dc:identifier": "SCOPUS_ID:85012345678",
    "citedby-count": "42",
    "openaccess": "1",
    "prism:issn": "0162-8828",
    "prism:aggregationType": "Journal",
    "affiliation": [
        {"affilname": "Seoul National University", "affiliation-city": "Seoul",
         "affiliation-country": "South Korea"},
    ],
    "author": [
        {"authname": "Kim J.", "authid": "12345678"},
        {"authname": "Lee S.", "authid": "23456789"},
    ],
}

SAMPLE_SEARCH_ENTRY_2 = {
    "dc:title": "Transformer Models in NLP",
    "dc:creator": "Smith A.",
    "prism:publicationName": "Nature Machine Intelligence",
    "prism:coverDate": "2023-06-01",
    "prism:doi": "10.1038/s42256-023-00001",
    "eid": "2-s2.0-85098765432",
    "dc:identifier": "SCOPUS_ID:85098765432",
    "citedby-count": "128",
    "openaccess": "0",
    "prism:aggregationType": "Journal",
}


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Use a temporary DuckDB database for tests."""
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    return db_file


@pytest.fixture(autouse=True)
def tmp_session(monkeypatch, tmp_path):
    """Isolate session storage from real user data."""
    monkeypatch.setattr(session_mod, "SESSION_DIR", tmp_path / "session")


# ── Session Tests ─────────────────────────────────────────────────────────────

class TestSession:
    def test_last_search(self):
        sess = Session()
        assert sess.last_search is None

        data = {"entries": [SAMPLE_SEARCH_ENTRY, SAMPLE_SEARCH_ENTRY_2]}
        sess.last_search = data
        assert sess.last_search == data

    def test_get_entry_by_index(self):
        sess = Session()
        sess.last_search = {"entries": [SAMPLE_SEARCH_ENTRY, SAMPLE_SEARCH_ENTRY_2]}

        entry = sess.get_entry_by_index(1)
        assert entry["dc:title"] == "Deep Learning for Image Segmentation: A Survey"

        entry2 = sess.get_entry_by_index(2)
        assert entry2["dc:title"] == "Transformer Models in NLP"

        assert sess.get_entry_by_index(0) is None
        assert sess.get_entry_by_index(3) is None

    def test_get_entries_by_indices(self):
        sess = Session()
        sess.last_search = {"entries": [SAMPLE_SEARCH_ENTRY, SAMPLE_SEARCH_ENTRY_2]}

        entries = sess.get_entries_by_indices([1, 2])
        assert len(entries) == 2

        entries = sess.get_entries_by_indices([1, 99])
        assert len(entries) == 1

    def test_search_history(self):
        sess = Session()
        sess.add_to_history("deep learning")
        sess.add_to_history("transformer")
        assert sess.search_history == ["deep learning", "transformer"]


# ── Article DB Tests ──────────────────────────────────────────────────────────

class TestArticleDB:
    def test_add_entries(self, tmp_db):
        result = db_mod.add_entries([SAMPLE_SEARCH_ENTRY])
        assert result["added"] == 1
        assert result["updated"] == 0
        assert result["total"] == 1

    def test_add_duplicate(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY])
        result = db_mod.add_entries([SAMPLE_SEARCH_ENTRY])
        assert result["added"] == 0
        assert result["updated"] == 1
        assert result["total"] == 1

    def test_add_with_tags(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY], tags=["ml", "survey"])
        article = db_mod.get_article("2-s2.0-85012345678")
        assert "ml" in article["_tags"]
        assert "survey" in article["_tags"]

    def test_add_to_collection(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY], collection="thesis")
        colls = db_mod.list_collections()
        assert "thesis" in colls["collections"]
        assert colls["collections"]["thesis"]["article_count"] == 1

    def test_remove_entries(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY, SAMPLE_SEARCH_ENTRY_2])
        result = db_mod.remove_entries(["2-s2.0-85012345678"])
        assert result["removed"] == 1
        assert result["total"] == 1

    def test_list_articles(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY, SAMPLE_SEARCH_ENTRY_2])
        result = db_mod.list_articles()
        assert result["total_matching"] == 2
        assert len(result["articles"]) == 2

    def test_list_filter_by_tag(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY], tags=["ml"])
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY_2])
        result = db_mod.list_articles(tag="ml")
        assert result["total_matching"] == 1

    def test_list_filter_by_query(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY, SAMPLE_SEARCH_ENTRY_2])
        result = db_mod.list_articles(query="transformer")
        assert result["total_matching"] == 1
        assert result["articles"][0]["title"] == "Transformer Models in NLP"

    def test_tag_articles(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY])
        result = db_mod.tag_articles(["2-s2.0-85012345678"], ["important"])
        assert result["tagged"] == 1
        article = db_mod.get_article("2-s2.0-85012345678")
        assert "important" in article["_tags"]

    def test_untag_articles(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY], tags=["ml", "survey"])
        db_mod.untag_articles(["2-s2.0-85012345678"], ["ml"])
        article = db_mod.get_article("2-s2.0-85012345678")
        assert "ml" not in article["_tags"]
        assert "survey" in article["_tags"]

    def test_set_note(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY])
        db_mod.set_note("2-s2.0-85012345678", "Great methodology")
        article = db_mod.get_article("2-s2.0-85012345678")
        assert article["_notes"] == "Great methodology"

    def test_get_nonexistent(self, tmp_db):
        with pytest.raises(ValueError, match="not found"):
            db_mod.get_article("nonexistent")

    def test_stats(self, tmp_db):
        db_mod.add_entries([SAMPLE_SEARCH_ENTRY, SAMPLE_SEARCH_ENTRY_2],
                           tags=["ml"])
        result = db_mod.stats()
        assert result["total_articles"] == 2
        assert result["total_tags"] == 1
        assert "ml" in result["tags"]

    def test_collection_crud(self, tmp_db):
        db_mod.create_collection("refs")
        colls = db_mod.list_collections()
        assert "refs" in colls["collections"]

        db_mod.add_entries([SAMPLE_SEARCH_ENTRY])
        db_mod.add_to_collection("refs", ["2-s2.0-85012345678"])
        colls = db_mod.list_collections()
        assert colls["collections"]["refs"]["article_count"] == 1

        db_mod.remove_from_collection("refs", ["2-s2.0-85012345678"])
        colls = db_mod.list_collections()
        assert colls["collections"]["refs"]["article_count"] == 0

        db_mod.delete_collection("refs")
        colls = db_mod.list_collections()
        assert "refs" not in colls["collections"]


# ── Export Tests ──────────────────────────────────────────────────────────────

class TestExport:
    def _make_articles(self):
        """Create normalized articles for export."""
        articles = []
        for entry in [SAMPLE_SEARCH_ENTRY, SAMPLE_SEARCH_ENTRY_2]:
            articles.append(db_mod._normalize_entry(entry))
        return articles

    def test_export_bibtex(self, tmp_path):
        articles = self._make_articles()
        out = str(tmp_path / "test.bib")
        result = export_mod.export_bibtex(articles, out)
        assert result["exported"] == 2
        assert os.path.exists(out)

        with open(out) as f:
            content = f.read()
        assert "@article{" in content
        assert "Kim" in content
        assert "10.1109" in content

    def test_export_xlsx(self, tmp_path):
        pytest.importorskip("openpyxl")
        articles = self._make_articles()
        out = str(tmp_path / "test.xlsx")
        result = export_mod.export_xlsx(articles, out)
        assert result["exported"] == 2
        assert os.path.exists(out)
        assert os.path.getsize(out) > 1000


# ── Search Module Tests (query building only) ────────────────────────────────

class TestSearchQueryBuilding:
    def test_has_field_code(self):
        from scopus_for_dobby.core.search import _has_field_code
        assert _has_field_code("TITLE-ABS-KEY(test)")
        assert _has_field_code("AUTH(Kim)")
        assert _has_field_code("DOI(10.1234/test)")
        assert not _has_field_code("deep learning")
        assert not _has_field_code("machine learning survey")


# ── Auth Validation Tests ────────────────────────────────────────────────────

class TestAuthValidation:
    def test_valid_api_key(self):
        from scopus_for_dobby.core.auth import _validate_api_key
        key = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"  # 32 hex chars
        assert _validate_api_key(key) == key

    def test_valid_api_key_uppercase(self):
        from scopus_for_dobby.core.auth import _validate_api_key
        key = "A1B2C3D4E5F6A1B2C3D4E5F6A1B2C3D4"
        assert _validate_api_key(key) == key

    def test_api_key_with_whitespace(self):
        from scopus_for_dobby.core.auth import _validate_api_key
        key = "  a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4  "
        assert _validate_api_key(key) == key.strip()

    def test_empty_api_key(self):
        from scopus_for_dobby.core.auth import _validate_api_key
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_api_key("")

    def test_whitespace_only_api_key(self):
        from scopus_for_dobby.core.auth import _validate_api_key
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_api_key("   ")

    def test_too_short_api_key(self):
        from scopus_for_dobby.core.auth import _validate_api_key
        with pytest.raises(ValueError, match="32 hex characters"):
            _validate_api_key("abc123")

    def test_non_hex_api_key(self):
        from scopus_for_dobby.core.auth import _validate_api_key
        with pytest.raises(ValueError, match="32 hex characters"):
            _validate_api_key("g1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4")  # 'g' is not hex

    def test_api_key_with_dashes(self):
        from scopus_for_dobby.core.auth import _validate_api_key
        with pytest.raises(ValueError, match="32 hex characters"):
            _validate_api_key("a1b2c3d4-e5f6-a1b2-c3d4-e5f6a1b2c3d4")

    def test_empty_inst_token(self):
        from scopus_for_dobby.core.auth import _validate_inst_token
        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_inst_token("")

    def test_valid_inst_token(self):
        from scopus_for_dobby.core.auth import _validate_inst_token
        assert _validate_inst_token("  some-token-123  ") == "some-token-123"
