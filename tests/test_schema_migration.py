"""Schema migration gate — including databases that predate it.

`schema_meta` was introduced after the project already had users, so an
on-disk database can be in one of several states. The gate must tell them
apart; getting it wrong is silent, because reads use ``SELECT *`` and only
queries naming a missing column fail.

Regression: a database created *before* `schema_meta` existed has no version
row — the same as a brand-new one. The original gate stamped both with the
current version, so legacy databases were marked up to date and the v1→v2
migration never ran. They kept listing articles fine and then failed on
``openalex enrich``.
"""

import duckdb
import pytest

from scopus_for_dobby.core import article_db as db_mod

# The `articles` table as it stood at v1 — before the OpenAlex columns.
V1_ARTICLES_DDL = """
    CREATE TABLE articles (
        eid             VARCHAR PRIMARY KEY,
        scopus_id       VARCHAR,
        doi             VARCHAR,
        title           VARCHAR,
        first_author    VARCHAR,
        all_authors     JSON,
        journal         VARCHAR,
        volume          VARCHAR,
        issue           VARCHAR,
        pages           VARCHAR,
        cover_date      VARCHAR,
        cited_by        INTEGER DEFAULT 0,
        open_access     BOOLEAN DEFAULT FALSE,
        abstract        VARCHAR,
        keywords        VARCHAR,
        issn            VARCHAR,
        source_type     VARCHAR,
        affiliations    JSON,
        index_keywords  JSON DEFAULT '[]',
        subject_areas   JSON DEFAULT '[]',
        tags            JSON DEFAULT '[]',
        notes           VARCHAR DEFAULT '',
        added_at        VARCHAR,
        updated_at      VARCHAR
    )
"""

V2_COLUMNS = [name for name, _ in db_mod._V2_ARTICLE_COLUMNS]

SAMPLE = {
    "dc:title": "Legacy row",
    "dc:creator": "Tester",
    "prism:publicationName": "J",
    "prism:coverDate": "2025-01-01",
    "prism:doi": "10.0/legacy",
    "eid": "2-s2.0-legacy-1",
    "dc:identifier": "SCOPUS_ID:legacy-1",
    "citedby-count": "4",
    "openaccess": "0",
    "prism:aggregationType": "Journal",
}


@pytest.fixture
def db_path(monkeypatch, tmp_path):
    path = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", path)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield path
    db_mod.close_cached_connections()


def _seed(path, *, stamp_version=None, with_v2_columns=False):
    """Write a database by hand, bypassing _ensure_schema."""
    conn = duckdb.connect(str(path))
    conn.execute(V1_ARTICLES_DDL)
    if with_v2_columns:
        for _, col_ddl in db_mod._V2_ARTICLE_COLUMNS:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {col_ddl}")
    if stamp_version is not None:
        conn.execute("CREATE TABLE schema_meta (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_meta (version) VALUES (?)", [stamp_version])
    conn.execute(
        "INSERT INTO articles (eid, title, added_at, updated_at) VALUES (?, ?, ?, ?)",
        ["2-s2.0-preexisting", "Row written before the migration", "", ""],
    )
    conn.close()


def _columns(conn) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = 'articles'"
        ).fetchall()
    }


def _version(conn) -> int:
    return conn.execute("SELECT version FROM schema_meta").fetchone()[0]


class TestLegacyDatabaseWithoutStamp:
    """The regression: v1 tables, no `schema_meta` at all."""

    def test_migration_runs(self, db_path):
        _seed(db_path)
        conn = db_mod._get_conn()
        assert V2_COLUMNS and set(V2_COLUMNS) <= _columns(conn)

    def test_stamped_current_afterwards(self, db_path):
        _seed(db_path)
        conn = db_mod._get_conn()
        assert _version(conn) == db_mod.SCHEMA_VERSION

    def test_existing_rows_survive(self, db_path):
        _seed(db_path)
        conn = db_mod._get_conn()
        row = conn.execute(
            "SELECT title FROM articles WHERE eid = '2-s2.0-preexisting'"
        ).fetchone()
        assert row[0] == "Row written before the migration"

    def test_enrich_works(self, db_path):
        """The user-visible symptom: `openalex enrich` writes these columns."""
        _seed(db_path)
        db_mod.add_entries([SAMPLE])
        # Field names are the ones core.openalex.normalize_enrichment emits.
        result = db_mod.enrich_articles(
            [{
                "eid": SAMPLE["eid"],
                "openalex_id": "W123",
                "oa_status": "gold",
                "oa_url": "https://example.org/paper.pdf",
                "cited_by_count": 12,
                "topics": ["hydrology"],
            }]
        )
        assert result["enriched"] == 1
        article = db_mod.get_article(SAMPLE["eid"])
        assert article["openalex_id"] == "W123"
        assert article["oa_url"] == "https://example.org/paper.pdf"
        assert article["openalex_cited_by"] == 12
        assert article["openalex_topics"] == ["hydrology"]


class TestMisStampedDatabase:
    """Already damaged by the old gate: stamped v2, columns never added."""

    def test_columns_are_repaired(self, db_path):
        _seed(db_path, stamp_version=2)
        conn = db_mod._get_conn()
        assert set(V2_COLUMNS) <= _columns(conn)

    def test_repair_is_logged(self, db_path, caplog):
        _seed(db_path, stamp_version=2)
        with caplog.at_level("WARNING"):
            db_mod._get_conn()
        assert "Repaired schema drift" in caplog.text

    def test_enrich_works_after_repair(self, db_path):
        _seed(db_path, stamp_version=2)
        db_mod.add_entries([SAMPLE])
        result = db_mod.enrich_articles(
            [{"eid": SAMPLE["eid"], "openalex_id": "W999", "oa_status": "green"}]
        )
        assert result["enriched"] == 1
        assert db_mod.get_article(SAMPLE["eid"])["openalex_id"] == "W999"


class TestHealthyDatabases:
    """Databases that need nothing done must be left alone and stay quiet."""

    def test_fresh_database_stamped_current(self, db_path):
        conn = db_mod._get_conn()
        assert _version(conn) == db_mod.SCHEMA_VERSION
        assert set(V2_COLUMNS) <= _columns(conn)

    def test_fresh_database_logs_no_repair(self, db_path, caplog):
        with caplog.at_level("WARNING"):
            db_mod._get_conn()
        assert "Repaired schema drift" not in caplog.text

    def test_current_database_untouched(self, db_path, caplog):
        _seed(db_path, stamp_version=2, with_v2_columns=True)
        with caplog.at_level("WARNING"):
            conn = db_mod._get_conn()
        assert _version(conn) == db_mod.SCHEMA_VERSION
        assert "Repaired schema drift" not in caplog.text

    def test_v1_stamped_database_migrates_quietly(self, db_path, caplog):
        """An honest v1 stamp is a migration, not drift — no warning."""
        _seed(db_path, stamp_version=1)
        with caplog.at_level("WARNING"):
            conn = db_mod._get_conn()
        assert set(V2_COLUMNS) <= _columns(conn)
        assert _version(conn) == db_mod.SCHEMA_VERSION
        assert "Repaired schema drift" not in caplog.text


class TestMigrationHelper:
    def test_is_idempotent(self, db_path):
        _seed(db_path)
        conn = db_mod._get_conn()
        assert db_mod._migrate_v1_to_v2(conn) == []

    def test_reports_only_what_it_added(self, db_path):
        _seed(db_path, stamp_version=2)
        raw = duckdb.connect(str(db_path))
        raw.execute("ALTER TABLE articles ADD COLUMN oa_status VARCHAR DEFAULT ''")
        raw.close()

        conn = db_mod._get_conn()
        # oa_status was already there; the other five were not.
        assert set(V2_COLUMNS) <= _columns(conn)
        assert db_mod._migrate_v1_to_v2(conn) == []
