"""Unit tests for the author-management layer in core.article_db.

These tests use synthetic data and do not make API calls. The HTTP path of
``fetch_author_profile`` is exercised only with ``api_get`` mocked out.
"""

import pytest

from scopus_for_dobby.core import article_db as db_mod

# ── Fixtures ──────────────────────────────────────────────────────────────────

# Kim J. (12345678) + Lee S. (23456789)
ENTRY_KIM_LEE = {
    "dc:title": "Deep Learning for Image Segmentation: A Survey",
    "dc:creator": "Kim J.",
    "prism:publicationName": "IEEE Transactions on Pattern Analysis",
    "prism:coverDate": "2024-03-15",
    "prism:doi": "10.1109/TPAMI.2024.001234",
    "eid": "2-s2.0-85012345678",
    "dc:identifier": "SCOPUS_ID:85012345678",
    "citedby-count": "42",
    "prism:aggregationType": "Journal",
    "affiliation": [
        {
            "afid": "60001",
            "affilname": "Seoul National University",
            "affiliation-city": "Seoul",
            "affiliation-country": "South Korea",
        },
    ],
    "author": [
        {"authname": "Kim J.", "authid": "12345678", "afid": [{"$": "60001"}]},
        {"authname": "Lee S.", "authid": "23456789"},
    ],
}

# Kim J. (12345678) again + Park H. (34567890) — shares Kim with ENTRY_KIM_LEE
ENTRY_KIM_PARK = {
    "dc:title": "Self-Supervised Pretraining",
    "dc:creator": "Kim J.",
    "prism:publicationName": "Nature Machine Intelligence",
    "prism:coverDate": "2023-06-01",
    "prism:doi": "10.1038/s42256-023-00099",
    "eid": "2-s2.0-85098765432",
    "dc:identifier": "SCOPUS_ID:85098765432",
    "citedby-count": "10",
    "prism:aggregationType": "Journal",
    "author": [
        {"authname": "Kim J.", "authid": "12345678"},
        {"authname": "Park H.", "authid": "34567890"},
    ],
}

# No author block at all.
ENTRY_NO_AUTHORS = {
    "dc:title": "Anonymous Editorial",
    "prism:publicationName": "Some Journal",
    "prism:coverDate": "2022-01-01",
    "eid": "2-s2.0-85000000001",
    "dc:identifier": "SCOPUS_ID:85000000001",
    "prism:aggregationType": "Journal",
}


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Use a temporary DuckDB database for tests."""
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    return db_file


# ── list_authors ──────────────────────────────────────────────────────────────


class TestListAuthors:
    def test_lists_all_extracted_authors(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        result = db_mod.list_authors()
        # Kim, Lee, Park
        assert result["total"] == 3
        assert len(result["authors"]) == 3
        names = {a["name"] for a in result["authors"]}
        assert names == {"Kim J.", "Lee S.", "Park H."}

    def test_query_filters_by_name(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        result = db_mod.list_authors(query="park")
        assert result["total"] == 1
        assert result["authors"][0]["name"] == "Park H."

    def test_query_is_case_insensitive(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE])
        assert db_mod.list_authors(query="KIM")["total"] == 1

    def test_sort_by_papers(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        result = db_mod.list_authors(sort="papers")
        # Kim appears in two articles, so should be first.
        assert result["authors"][0]["name"] == "Kim J."
        assert result["authors"][0]["paper_count"] == 2

    def test_sort_by_name(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        names = [a["name"] for a in db_mod.list_authors(sort="name")["authors"]]
        assert names == sorted(names, key=str.lower)

    def test_limit_caps_results(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        result = db_mod.list_authors(limit=1)
        assert len(result["authors"]) == 1
        # total ignores the limit.
        assert result["total"] == 3

    def test_unknown_sort_falls_back_to_papers(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        result = db_mod.list_authors(sort="bogus")
        assert result["authors"][0]["name"] == "Kim J."


# ── get_author ────────────────────────────────────────────────────────────────


class TestGetAuthor:
    def test_found_with_articles(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        author = db_mod.get_author("12345678")
        assert author["auid"] == "12345678"
        assert author["name"] == "Kim J."
        assert author["paper_count"] == 2
        assert len(author["articles"]) == 2
        # Articles ordered by cover_date DESC: 2024 entry first.
        assert author["articles"][0]["eid"] == "2-s2.0-85012345678"

    def test_first_author_flag(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE])
        author = db_mod.get_author("12345678")
        assert author["articles"][0]["is_first_author"] is True
        assert author["articles"][0]["author_position"] == 1

    def test_coauthors_embedded(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        author = db_mod.get_author("12345678")
        co_names = {c["name"] for c in author["coauthors"]}
        assert co_names == {"Lee S.", "Park H."}

    def test_missing_author_raises(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE])
        with pytest.raises(ValueError, match="Author not found: 99999999"):
            db_mod.get_author("99999999")


# ── find_coauthors ────────────────────────────────────────────────────────────


class TestFindCoauthors:
    def test_dedup_across_shared_papers(self, tmp_db):
        # Kim co-authors with Lee on one paper and Park on another. Lee also
        # collaborates with Kim a second time below to confirm dedup + counting.
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        # A third paper with Kim + Lee again so they share two papers.
        third = dict(ENTRY_KIM_LEE)
        third["eid"] = "2-s2.0-85011111111"
        third["dc:identifier"] = "SCOPUS_ID:85011111111"
        third["prism:doi"] = "10.1109/TPAMI.2024.999999"
        db_mod.add_entries([third])

        result = db_mod.find_coauthors("12345678")
        assert result["author"] == {"auid": "12345678", "name": "Kim J."}
        # One row per distinct co-author despite multiple shared papers.
        by_auid = {c["auid"]: c for c in result["coauthors"]}
        assert set(by_auid) == {"23456789", "34567890"}
        assert result["total"] == 2
        # Lee shares two papers, Park one.
        assert by_auid["23456789"]["shared_papers"] == 2
        assert by_auid["34567890"]["shared_papers"] == 1

    def test_affiliations_parsed_from_json(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE, ENTRY_KIM_PARK])
        # Kim carries the resolved affiliation; query Lee's view of Kim.
        result = db_mod.find_coauthors("23456789")
        kim = next(c for c in result["coauthors"] if c["auid"] == "12345678")
        assert kim["affiliations"] == ["Seoul National University"]

    def test_author_with_no_coauthors(self, tmp_db):
        # Build an entry whose single author has a valid AUID.
        solo = dict(ENTRY_NO_AUTHORS)
        solo["author"] = [{"authname": "Solo X.", "authid": "55555555"}]
        db_mod.add_entries([solo])
        result = db_mod.find_coauthors("55555555")
        assert result["coauthors"] == []
        assert result["total"] == 0

    def test_missing_author_raises(self, tmp_db):
        with pytest.raises(ValueError, match="Author not found"):
            db_mod.find_coauthors("00000000")


# ── set_author_note ───────────────────────────────────────────────────────────


class TestAuthorNote:
    def test_set_and_read_back(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE])
        result = db_mod.set_author_note("12345678", "Met at NeurIPS")
        assert result == {"auid": "12345678", "note": "Met at NeurIPS"}
        assert db_mod.get_author("12345678")["notes"] == "Met at NeurIPS"

    def test_overwrite(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE])
        db_mod.set_author_note("12345678", "first")
        db_mod.set_author_note("12345678", "second")
        assert db_mod.get_author("12345678")["notes"] == "second"

    def test_clear_to_empty(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE])
        db_mod.set_author_note("12345678", "temporary")
        db_mod.set_author_note("12345678", "")
        assert db_mod.get_author("12345678")["notes"] == ""

    def test_missing_author_raises(self, tmp_db):
        with pytest.raises(ValueError, match="Author not found"):
            db_mod.set_author_note("00000000", "nope")


# ── Author auto-extraction edge cases (via add_entries) ───────────────────────


class TestAuthorExtraction:
    def test_entry_without_authors_yields_none(self, tmp_db):
        db_mod.add_entries([ENTRY_NO_AUTHORS])
        assert db_mod.list_authors()["total"] == 0

    def test_author_missing_auid_is_skipped(self, tmp_db):
        entry = dict(ENTRY_NO_AUTHORS)
        entry["author"] = [
            {"authname": "Has Id", "authid": "77777777"},
            {"authname": "No Id"},  # missing authid → skipped
        ]
        db_mod.add_entries([entry])
        result = db_mod.list_authors()
        assert result["total"] == 1
        assert result["authors"][0]["auid"] == "77777777"

    def test_duplicate_auid_in_one_entry_links_once(self, tmp_db):
        entry = dict(ENTRY_NO_AUTHORS)
        entry["author"] = [
            {"authname": "Kim J.", "authid": "12345678"},
            {"authname": "Kim Jihoon", "authid": "12345678"},  # same AUID
        ]
        db_mod.add_entries([entry])
        # A single author row, linked to the article exactly once.
        result = db_mod.list_authors()
        assert result["total"] == 1
        assert result["authors"][0]["paper_count"] == 1

    def test_reextraction_merges_affiliations(self, tmp_db):
        # Kim added without an affiliation first, then with one.
        first = dict(ENTRY_KIM_PARK)  # Kim has no afid here
        db_mod.add_entries([first])
        before = db_mod.get_author("12345678")["affiliations"]
        assert before == []

        db_mod.add_entries([ENTRY_KIM_LEE])  # Kim carries afid → SNU
        after = db_mod.get_author("12345678")["affiliations"]
        assert "Seoul National University" in after

    def test_orphan_authors_removed_with_article(self, tmp_db):
        db_mod.add_entries([ENTRY_KIM_LEE])
        assert db_mod.list_authors()["total"] == 2
        db_mod.remove_entries(["2-s2.0-85012345678"])
        # Both authors were unique to that article, so both are pruned.
        assert db_mod.list_authors()["total"] == 0


# ── fetch_author_profile (HTTP mocked) ────────────────────────────────────────


class TestFetchAuthorProfile:
    def test_inserts_profile_from_mocked_api(self, tmp_db, monkeypatch):
        fake_response = {
            "author-retrieval-response": [
                {
                    "coredata": {
                        "document-count": "120",
                        "cited-by-count": "5000",
                        "citation-count": "5200",
                        "orcid": "0000-0002-1825-0097",
                    },
                    "h-index": "31",
                    "coauthor-count": "88",
                    "author-profile": {
                        "preferred-name": {"indexed-name": "Kim J."},
                        "affiliation-current": {
                            "affiliation": {"ip-doc": {"afdispname": "Seoul National University"}}
                        },
                    },
                    "subject-areas": {
                        "subject-area": [
                            {"$": "Artificial Intelligence", "@code": "1702", "@abbrev": "COMP"},
                        ]
                    },
                }
            ]
        }

        from scopus_for_dobby.utils import api_client

        monkeypatch.setattr(api_client, "api_get", lambda *a, **k: fake_response)

        result = db_mod.fetch_author_profile("12345678")
        assert result["name"] == "Kim J."
        assert result["h_index"] == 31
        assert result["document_count"] == 120
        assert result["coauthor_count"] == 88
        assert result["orcid"] == "0000-0002-1825-0097"
        assert result["affiliations"] == ["Seoul National University"]
        assert result["subject_areas"][0]["name"] == "Artificial Intelligence"

        # Persisted to the DB.
        stored = db_mod.get_author("12345678")
        assert stored["h_index"] == 31
        assert stored["subject_areas"][0]["code"] == "1702"
