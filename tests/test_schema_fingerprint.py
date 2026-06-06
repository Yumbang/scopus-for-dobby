"""Step 8: schema-fingerprint tripwire.

A canonical SHA-256 of the normalized ``CREATE TABLE`` strings emitted
by DuckDB for our schema is checked into ``tests/fixtures/schema_fingerprint.txt``.
Any DDL change in ``core.article_db._ensure_schema`` will flip the
fingerprint; the test fails with an actionable message instructing the
developer to update both the fingerprint AND the matching Swift structs
in ``gui-macos/Sources/Models/`` (forthcoming) before merging.

To refresh the fingerprint after an intentional schema change, run the
helper at the bottom of this file via:
    pytest tests/test_schema_fingerprint.py --update-fingerprint
"""

import hashlib
import re
from pathlib import Path

import pytest

from scopus_for_dobby.core import article_db as db_mod

FINGERPRINT_FILE = Path(__file__).parent / "fixtures" / "schema_fingerprint.txt"


def _compute_fingerprint(conn) -> str:
    rows = conn.execute(
        "SELECT table_name, sql FROM duckdb_tables() "
        "WHERE schema_name = 'main' ORDER BY table_name"
    ).fetchall()
    parts = []
    for name, sql in rows:
        norm = re.sub(r"\s+", " ", sql).strip()
        parts.append(f"{name}:{norm}")
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield db_file
    db_mod.close_cached_connections()


def test_schema_fingerprint_unchanged(tmp_db):
    expected = FINGERPRINT_FILE.read_text().strip()
    conn = db_mod._get_conn()
    actual = _compute_fingerprint(conn)
    assert actual == expected, (
        f"Schema fingerprint changed.\n"
        f"  Expected: {expected}\n"
        f"  Actual:   {actual}\n\n"
        f"If this change is intentional:\n"
        f"  1. Update the matching Swift structs in gui-macos/Sources/Models/\n"
        f"     (Article.swift, Collection.swift, Event.swift, etc.) IN THE\n"
        f"     SAME COMMIT as the DDL change.\n"
        f"  2. Refresh the fingerprint:\n"
        f"     echo {actual} > {FINGERPRINT_FILE}\n"
    )
