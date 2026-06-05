"""Tests for Step 1.5: connection lifecycle refactor in core.article_db.

Covers:
- _open_conn returns a fresh connection with no DDL side effects.
- _ensure_schema is idempotent and runs at most once per (process, DB_PATH).
- _get_conn returns a cached connection that survives repeated calls.
- _txn commits on success and rolls back on exception, leaving no
  orphaned mutation rows.
- A connect-storm of repeated _get_conn() calls does not raise
  "database is locked" or any other contention error.
"""

import pytest

from scopus_for_dobby.core import article_db as db_mod


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    """Per-test temporary DB file with cached connections cleaned up after."""
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield db_file
    db_mod.close_cached_connections()


class TestConnectionLifecycle:
    def test_open_conn_no_ddl(self, tmp_db):
        conn = db_mod._open_conn()
        try:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
            assert tables == [], "_open_conn must not create any tables"
        finally:
            conn.close()

    def test_ensure_schema_creates_tables(self, tmp_db):
        conn = db_mod._get_conn()
        names = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        for required in {"articles", "collections", "collection_articles",
                         "authors", "article_authors"}:
            assert required in names, f"Missing table {required}"

    def test_ensure_schema_idempotent(self, tmp_db):
        from pathlib import Path

        conn = db_mod._get_conn()
        # First call already initialized.
        assert Path(db_mod.DB_PATH) in db_mod._schema_initialized
        # Subsequent calls should be cheap no-ops; test that calling
        # _ensure_schema again does not raise and the guard set stays the same.
        before = set(db_mod._schema_initialized)
        db_mod._ensure_schema(conn)
        db_mod._ensure_schema(conn)
        assert db_mod._schema_initialized == before

    def test_get_conn_returns_thread_local_parent(self, tmp_db):
        # Post thread-safety fix v2: ``_get_conn()`` returns the calling
        # thread's parent connection (not a cursor). Cursor-isolation alone
        # was insufficient — DuckDB's underlying connection state still raced
        # under FastAPI threadpool dispatch. Same-thread calls return the
        # same object now; concurrent threads each get their own parent
        # (verified by ``test_concurrent_threads_dont_corrupt_cursors``).
        c1 = db_mod._get_conn()
        c2 = db_mod._get_conn()
        assert c1 is c2, "same-thread _get_conn() must return the same connection"
        # The first parent ever opened against this path is recorded in
        # ``_conn_cache`` for legacy/test cleanup hooks.
        assert db_mod.DB_PATH in db_mod._conn_cache

    def test_connect_storm(self, tmp_db):
        """50 rapid _get_conn() calls must not trigger lock errors."""
        for _ in range(50):
            conn = db_mod._get_conn()
            conn.execute("SELECT 1").fetchone()

    def test_concurrent_threads_dont_corrupt_cursors(self, tmp_db):
        """Regression: two threads issuing list_articles() simultaneously
        must not see ``fetchone() is None`` from interleaved cursors. This
        was the 500 hit by the GUI's concurrent reloadAll/poll loop —
        ``conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]``
        crashed because the underlying result cursor had been consumed by
        another thread. Fix: ``_get_conn()`` returns a fresh ``cursor()``
        per call.
        """
        import threading as _t

        # Seed a row so the table exists with deterministic content.
        db_mod.add_entries([{"eid": "EID-CONCURRENT-1", "title": "x"}])

        errors: list[Exception] = []

        def hammer() -> None:
            try:
                for _ in range(40):
                    db_mod.list_articles(limit=10)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [_t.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"concurrent list_articles raised: {errors[:3]}"

    def test_txn_commits_on_success(self, tmp_db):
        conn = db_mod._get_conn()
        with db_mod._txn(conn):
            conn.execute(
                "INSERT INTO articles (eid, title, added_at) VALUES (?, ?, ?)",
                ["eid-commit", "Committed", db_mod._now()],
            )
        rows = conn.execute(
            "SELECT eid FROM articles WHERE eid = ?", ["eid-commit"]
        ).fetchall()
        assert rows == [("eid-commit",)]

    def test_txn_rolls_back_on_exception(self, tmp_db):
        conn = db_mod._get_conn()

        class Boom(RuntimeError):
            pass

        with pytest.raises(Boom), db_mod._txn(conn):
            conn.execute(
                "INSERT INTO articles (eid, title, added_at) VALUES (?, ?, ?)",
                ["eid-rollback", "Should not persist", db_mod._now()],
            )
            raise Boom("simulated mid-transaction failure")

        rows = conn.execute(
            "SELECT eid FROM articles WHERE eid = ?", ["eid-rollback"]
        ).fetchall()
        assert rows == [], "rollback must leave no orphaned mutation row"
