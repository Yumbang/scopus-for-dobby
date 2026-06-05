"""Local article database — collect, tag, and manage papers offline.

Stores articles in a DuckDB database at ~/.scopus-for-dobby/articles.duckdb.
Each article is keyed by EID for deduplication. Supports:
- Adding articles from search results or abstract retrieval
- Tagging and notes
- Filtering and listing
- Collections
- Export to XLSX and BibTeX
"""

import contextlib
import json
import logging
import threading
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import duckdb

from scopus_for_dobby.utils.api_client import CONFIG_DIR

DB_PATH = CONFIG_DIR / "articles.duckdb"

# Current on-disk schema version. Bump and add a migration gate in
# ``_ensure_schema`` whenever the DDL changes incompatibly.
SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Connection & schema ──────────────────────────────────────────────────────
#
# DuckDB allows only one read/write connection per file. We keep a
# process-local cache keyed by the resolved DB_PATH so tests that
# monkeypatch DB_PATH per test pick up a fresh connection cleanly.
# Schema initialization (DDL) runs at most once per (path, connection).

_conn_cache: dict[Path, duckdb.DuckDBPyConnection] = {}
_schema_initialized: set[Path] = set()
_fts_loaded: set[Path] = set()
_fts_available: dict[Path, bool] = {}

# DuckDB's Python bindings are NOT thread-safe even with the documented
# ``cursor()`` pattern: cursors share their parent connection's underlying
# state, so concurrent ``execute()``/``fetchone()`` calls from FastAPI's
# threadpool can still produce torn results — manifesting most often as
# ``fetchone() is None`` on a query that should always return one row.
#
# Pattern that actually works: one parent ``duckdb.connect()`` PER THREAD,
# stored in ``threading.local()``. DuckDB supports multiple parents over the
# same file from the same process, so each request thread gets its own
# isolated connection without a global lock around every query.
#
# ``_conn_cache`` is preserved for tests that monkeypatch ``DB_PATH`` and
# call ``close_cached_connections()`` to clean up; we now also track
# per-thread parents in ``_thread_local.conns`` and close them too.
_conn_lock = threading.RLock()
_thread_local = threading.local()

# Process-wide write serialization. Per-thread connections solved the cursor-
# race that caused ``fetchone() is None``, but they still hit DuckDB's MVCC
# write-write detection: two threads UPDATE-ing the same row in overlapping
# transactions both get ``TransactionException: Conflict on update!`` and one
# (or both) is rolled back. For a single-user GUI the realistic write rate is
# tiny — events polls are reads, the user mutates one row at a time — so
# serializing every ``_txn`` block costs nothing in practice and eliminates
# the conflict class entirely. Reads remain parallel (no lock).
_write_lock = threading.Lock()


def _open_conn(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open a fresh DuckDB connection with no DDL side-effects."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH), read_only=read_only)
    # The DB file holds the user's article corpus; mirror the 0600 lock-down
    # applied to config.json (api_client.save_config) so it isn't world-
    # readable under the default umask. The file may already exist from a
    # prior run; chmod is idempotent. Tolerate a missing file (e.g. an
    # in-memory or not-yet-flushed connection) rather than failing the open.
    with contextlib.suppress(FileNotFoundError):
        Path(DB_PATH).chmod(0o600)
    return conn


def _ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create tables if they don't exist. Idempotent; runs at most once per process per DB."""
    path = Path(DB_PATH)
    if path in _schema_initialized:
        return
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
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
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            name       VARCHAR PRIMARY KEY,
            created_at VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collection_articles (
            collection_name VARCHAR,
            eid             VARCHAR,
            PRIMARY KEY (collection_name, eid)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS authors (
            auid            VARCHAR PRIMARY KEY,
            name            VARCHAR,
            affiliations    JSON DEFAULT '[]',
            h_index         INTEGER,
            document_count  INTEGER,
            cited_by_count  INTEGER,
            citation_count  INTEGER,
            coauthor_count  INTEGER,
            orcid           VARCHAR DEFAULT '',
            subject_areas   JSON DEFAULT '[]',
            notes           VARCHAR DEFAULT '',
            added_at        VARCHAR,
            updated_at      VARCHAR,
            fetched_at      VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS article_authors (
            eid                VARCHAR,
            auid               VARCHAR,
            seq                INTEGER DEFAULT 0,
            is_first           BOOLEAN DEFAULT FALSE,
            is_corresponding   BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (eid, auid)
        )
    """)
    # ── Events table (cross-process IPC + audit log) ─────────────────────────
    conn.execute("CREATE SEQUENCE IF NOT EXISTS events_id_seq")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id          BIGINT PRIMARY KEY DEFAULT nextval('events_id_seq'),
            ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            kind        VARCHAR,
            entity_type VARCHAR,
            entity_id   VARCHAR,
            payload     JSON
        )
    """)
    # ── Schema versioning gate ───────────────────────────────────────────────
    # Single-row meta table recording the on-disk schema version. No migration
    # framework — just a gate future migrations can branch on. A fresh DB is
    # stamped with SCHEMA_VERSION; existing DBs keep whatever version they hold.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_meta (
            version INTEGER NOT NULL
        )
    """)
    if conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0] == 0:
        conn.execute("INSERT INTO schema_meta (version) VALUES (?)", [SCHEMA_VERSION])
    _schema_initialized.add(path)


def _emit_event(
    conn: duckdb.DuckDBPyConnection,
    kind: str,
    entity_type: str,
    entity_id: str,
    payload: dict | None = None,
) -> None:
    """Insert an event row. Must be called inside an active transaction
    so the event commits atomically with the mutation it describes."""
    conn.execute(
        "INSERT INTO events (kind, entity_type, entity_id, payload) VALUES (?, ?, ?, ?)",
        [kind, entity_type, entity_id, json.dumps(payload or {})],
    )


def _get_conn() -> duckdb.DuckDBPyConnection:
    """Return the calling thread's parent DuckDB connection for ``DB_PATH``.

    The connection is opened on first call per (thread, DB_PATH) and reused
    afterwards. DuckDB allows many parent connections to the same file from
    one process, so this gives full thread isolation without a global lock
    around every query.

    Schema initialization is global (runs at most once per process per
    DB_PATH), guarded by ``_conn_lock`` so concurrent first-callers don't
    race the DDL.
    """
    path = Path(DB_PATH)
    # Per-thread connection cache. ``getattr`` + ``hasattr`` separately so we
    # don't ``or {}`` an empty-but-existing dict (left behind after a test
    # cleanup), which would silently detach future stores from
    # ``_thread_local`` and re-open a fresh connection per call.
    if not hasattr(_thread_local, "conns"):
        _thread_local.conns = {}
    conns: dict[Path, duckdb.DuckDBPyConnection] = _thread_local.conns
    conn = conns.get(path)
    if conn is None:
        conn = _open_conn(read_only=False)
        conns[path] = conn
        # Track the first connection ever opened against this path so tests
        # / cleanup can close it; subsequent threads' connections are tracked
        # in ``_all_thread_conns`` for global teardown.
        with _conn_lock:
            _conn_cache.setdefault(path, conn)
            _all_thread_conns.append(conn)
    with _conn_lock:
        _ensure_schema(conn)
    return conn


# Tracks every per-thread connection ever opened so
# ``close_cached_connections()`` can fully shut down the process's DuckDB
# resources (used by tests to release file locks).
_all_thread_conns: list[duckdb.DuckDBPyConnection] = []


@contextmanager
def _txn(conn: duckdb.DuckDBPyConnection):
    """Wrap a block of mutations in BEGIN/COMMIT, rolling back on exception.

    Acquires ``_write_lock`` for the entire span so DuckDB's MVCC never sees
    two concurrent writers on the same row (which would raise
    ``TransactionException: Conflict on update!``). For a single-user app
    this serialization is free; reads continue to run in parallel because
    they don't go through ``_txn``.
    """
    with _write_lock:
        conn.execute("BEGIN TRANSACTION")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def close_cached_connections() -> None:
    """Close all cached connections. Intended for tests/teardown.

    Closes every per-thread parent connection tracked in
    ``_all_thread_conns`` plus any legacy entries still in ``_conn_cache``.
    Resets the calling thread's local cache so the next ``_get_conn()``
    opens a fresh connection (important for test isolation when DB_PATH is
    monkeypatched).
    """
    with _conn_lock:
        for c in list(_all_thread_conns):
            with contextlib.suppress(Exception):
                c.close()
        _all_thread_conns.clear()
        for c in _conn_cache.values():
            with contextlib.suppress(Exception):
                c.close()
        _conn_cache.clear()
        _schema_initialized.clear()
        _fts_loaded.clear()
        _fts_available.clear()
    if hasattr(_thread_local, "conns"):
        _thread_local.conns.clear()


def _ensure_fts(conn: duckdb.DuckDBPyConnection) -> bool:
    """Install + load DuckDB's fts extension once per process per DB.

    Returns True if FTS is available; False on any failure (e.g. offline,
    extension repository unreachable). Callers must fall back to LIKE search.
    """
    path = Path(DB_PATH)
    if path in _fts_loaded:
        return _fts_available.get(path, False)
    try:
        conn.execute("INSTALL fts")
        conn.execute("LOAD fts")
        _fts_available[path] = True
    except Exception as exc:
        _fts_available[path] = False
        logger.warning("DuckDB fts extension unavailable; search falls back to LIKE: %s", exc)
    _fts_loaded.add(path)
    return _fts_available[path]


def rebuild_fts() -> dict:
    """Rebuild the FTS index over the articles table.

    Idempotent. No-op if the FTS extension is unavailable or the
    articles table has zero rows (the PRAGMA fails on an empty corpus).
    """
    conn = _get_conn()
    if not _ensure_fts(conn):
        return {"rebuilt": False, "reason": "fts_unavailable"}
    # Hold the process-wide write lock for the whole count+rebuild so a
    # search-triggered rebuild can't race a concurrent add_entries and miss
    # rows it just committed (the PRAGMA snapshots the table as it runs).
    with _write_lock:
        n = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        if n == 0:
            return {"rebuilt": False, "reason": "empty_corpus"}
        conn.execute(
            "PRAGMA create_fts_index('articles', 'eid', 'title', 'abstract', "
            "'keywords', overwrite=1)"
        )
    return {"rebuilt": True, "rows": n}


def _row_to_dict(row: tuple, columns: list[str]) -> dict:
    """Convert a DuckDB row tuple to a dict, parsing JSON fields."""
    d = dict(zip(columns, row, strict=False))
    # Parse JSON fields
    for key in ("all_authors", "affiliations", "index_keywords", "subject_areas", "tags"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                d[key] = []
    # Rename for backward compat with export/display
    d["_tags"] = d.pop("tags", [])
    d["_notes"] = d.pop("notes", "")
    d["_added_at"] = d.pop("added_at", "")
    d["_updated_at"] = d.pop("updated_at", "")
    return d


_ARTICLE_COLUMNS = [
    "eid", "scopus_id", "doi", "title", "first_author", "all_authors",
    "journal", "volume", "issue", "pages", "cover_date", "cited_by",
    "open_access", "abstract", "keywords", "issn", "source_type",
    "affiliations", "index_keywords", "subject_areas",
    "tags", "notes", "added_at", "updated_at",
]


# ── Normalize ────────────────────────────────────────────────────────────────

def _normalize_entry(entry: dict) -> dict:
    """Normalize a Scopus search entry or abstract result into DB format."""
    if "dc:title" in entry:
        creator = entry.get("dc:creator", "")
        if isinstance(creator, dict):
            authors = creator.get("author", [])
            first_author = authors[0].get("preferred-name", {}).get(
                "ce:indexed-name", "") if authors else ""
        else:
            first_author = str(creator)

        all_authors = []
        for a in entry.get("author", []):
            all_authors.append({
                "name": a.get("authname", ""),
                "auid": a.get("authid", ""),
            })

        sid = entry.get("dc:identifier", "")
        scopus_id = str(sid).replace("SCOPUS_ID:", "") if sid else ""

        affs = []
        for a in (entry.get("affiliation", [])
                  if isinstance(entry.get("affiliation"), list) else []):
            affs.append(a.get("affilname", ""))

        cited = entry.get("citedby-count", "0")
        try:
            cited = int(cited)
        except (ValueError, TypeError):
            cited = 0

        return {
            "title": entry.get("dc:title", ""),
            "first_author": first_author,
            "all_authors": all_authors if all_authors else [{"name": first_author}],
            "journal": entry.get("prism:publicationName", ""),
            "volume": entry.get("prism:volume", ""),
            "issue": entry.get("prism:issueIdentifier", ""),
            "pages": entry.get("prism:pageRange", "") or entry.get("article-number", ""),
            "cover_date": entry.get("prism:coverDate", ""),
            "doi": entry.get("prism:doi", ""),
            "eid": entry.get("eid", ""),
            "scopus_id": scopus_id,
            "cited_by": cited,
            "open_access": str(entry.get("openaccess", "0")) == "1",
            "abstract": entry.get("dc:description", ""),
            "keywords": entry.get("authkeywords", ""),
            "issn": entry.get("prism:issn", ""),
            "source_type": entry.get("prism:aggregationType", ""),
            "affiliations": affs,
        }
    elif "title" in entry and "eid" in entry:
        # Already normalized — ensure cited_by is int
        e = dict(entry)
        try:
            e["cited_by"] = int(e.get("cited_by", 0))
        except (ValueError, TypeError):
            e["cited_by"] = 0
        return e
    else:
        raise ValueError("Unrecognized entry format.")


# ── Author extraction ─────────────────────────────────────────────────────────

def _upsert_authors_from_entry(
    conn: duckdb.DuckDBPyConnection, eid: str, raw_entry: dict, normalized: dict
):
    """Extract authors from a raw Scopus entry and upsert into authors + article_authors.

    Uses authid/auid from the raw API response. Only inserts authors with valid AUIDs.
    """
    authors_to_link: list[dict] = []

    # Source 1: raw search entry has author[] with authid + afid
    raw_authors = raw_entry.get("author", [])
    if raw_authors and isinstance(raw_authors, list):
        for seq, a in enumerate(raw_authors, 1):
            auid = a.get("authid", "") or a.get("@auid", "")
            name = a.get("authname", "")
            if auid and name:
                # Extract affiliation IDs for this author
                afids = a.get("afid", [])
                if isinstance(afids, dict):
                    afids = [afids]
                aff_ids = [af.get("$", "") for af in afids if isinstance(af, dict)]
                authors_to_link.append({
                    "auid": str(auid),
                    "name": name,
                    "seq": seq,
                    "aff_ids": aff_ids,
                })

    # Source 2: normalized entry has all_authors[] with auid (from abstract retrieval)
    if not authors_to_link:
        norm_authors = normalized.get("all_authors", [])
        if isinstance(norm_authors, list):
            for seq_idx, a in enumerate(norm_authors, 1):
                if isinstance(a, dict):
                    auid = a.get("auid", "")
                    name = a.get("name", "")
                    seq = int(a.get("seq", seq_idx) or seq_idx)
                    if auid and name:
                        authors_to_link.append({
                            "auid": str(auid),
                            "name": name,
                            "seq": seq,
                            "aff_ids": [],
                        })

    # Resolve affiliation names from the entry's affiliation block
    aff_map: dict[str, str] = {}
    raw_affs = raw_entry.get("affiliation", [])
    if isinstance(raw_affs, list):
        for af in raw_affs:
            afid = af.get("afid", "")
            afname = af.get("affilname", "")
            if afid and afname:
                aff_map[str(afid)] = afname

    # Detect corresponding author(s)
    corresponding_names: set[str] = set()

    def _strip_accents(s: str) -> str:
        """Normalize accented characters to ASCII for comparison."""
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

    # Source 1: from raw entry's item.bibrecord.head.correspondence
    item = raw_entry.get("item", {})
    if isinstance(item, dict):
        bib = item.get("bibrecord", {})
        head = bib.get("head", {}) if isinstance(bib, dict) else {}
        corr = head.get("correspondence", {}) if isinstance(head, dict) else {}
        if isinstance(corr, dict):
            corr = [corr]
        if isinstance(corr, list):
            for c in corr:
                person = c.get("person", {})
                if isinstance(person, dict):
                    cname = person.get("ce:indexed-name", "")
                    if cname:
                        corresponding_names.add(_strip_accents(cname).lower())

    # Source 2: from normalized entry's corresponding_authors (abstract retrieval)
    for cname in normalized.get("corresponding_authors", []):
        if cname:
            corresponding_names.add(_strip_accents(cname).lower())

    # Upsert each author
    for author in authors_to_link:
        auid = author["auid"]
        name = author["name"]
        is_first = author["seq"] == 1
        is_corresponding = _strip_accents(name).lower() in corresponding_names

        # Resolve affiliations for this author
        resolved_affs = [aff_map[aid] for aid in author["aff_ids"] if aid in aff_map]

        existing = conn.execute(
            "SELECT affiliations FROM authors WHERE auid = ?", [auid]
        ).fetchone()

        if existing:
            # Merge affiliations
            old_affs = json.loads(existing[0]) if existing[0] else []
            merged_affs = sorted(set(old_affs) | set(resolved_affs))
            conn.execute(
                "UPDATE authors SET name=?, affiliations=?, updated_at=? WHERE auid=?",
                [name, json.dumps(merged_affs), _now(), auid],
            )
        else:
            conn.execute(
                "INSERT INTO authors (auid, name, affiliations, notes, added_at) "
                "VALUES (?, ?, ?, '', ?)",
                [auid, name, json.dumps(resolved_affs), _now()],
            )

        # Link article <-> author (upsert to update is_corresponding on re-retrieval)
        existing_link = conn.execute(
            "SELECT is_corresponding FROM article_authors WHERE eid = ? AND auid = ?",
            [eid, auid],
        ).fetchone()
        if existing_link is None:
            conn.execute(
                "INSERT INTO article_authors (eid, auid, seq, is_first, is_corresponding) "
                "VALUES (?, ?, ?, ?, ?)",
                [eid, auid, author["seq"], is_first, is_corresponding],
            )
        elif is_corresponding and not existing_link[0]:
            conn.execute(
                "UPDATE article_authors SET is_corresponding = ? WHERE eid = ? AND auid = ?",
                [True, eid, auid],
            )


# ── Public API ────────────────────────────────────────────────────────────────

def add_entries(entries: list[dict], tags: list[str] | None = None,
                collection: str | None = None,
                defer_fts_rebuild: bool = False) -> dict:
    """Add one or more articles to the database.

    Deduplicates by EID. Updates existing entries with new data.

    The FTS index is rebuilt at the end of the call. Pass
    ``defer_fts_rebuild=True`` to skip the rebuild for this single call —
    the caller is then responsible for invoking :func:`rebuild_fts` once
    the bulk operation completes. The flag is single-call only and not a
    persistent sentinel.
    """
    conn = _get_conn()
    added = 0
    updated = 0

    with _txn(conn):
        for entry in entries:
            try:
                n = _normalize_entry(entry)
            except ValueError:
                continue

            eid = n.get("eid", "")
            if not eid:
                continue

            existing = conn.execute(
                "SELECT tags, notes, added_at FROM articles WHERE eid = ?", [eid]
            ).fetchone()

            all_authors_json = json.dumps(n.get("all_authors", []))
            affiliations_json = json.dumps(n.get("affiliations", []))
            idx_kw_json = json.dumps(n.get("index_keywords", []))
            subj_json = json.dumps(n.get("subject_areas", []))

            if existing:
                existing_tags = json.loads(existing[0]) if existing[0] else []
                merged_tags = sorted(set(existing_tags) | set(tags or []))
                conn.execute("""
                    UPDATE articles SET
                        scopus_id=?, doi=?, title=?, first_author=?, all_authors=?,
                        journal=?, volume=?, issue=?, pages=?, cover_date=?,
                        cited_by=?, open_access=?, abstract=?, keywords=?, issn=?,
                        source_type=?, affiliations=?, index_keywords=?,
                        subject_areas=?, tags=?, updated_at=?
                    WHERE eid = ?
                """, [
                    n.get("scopus_id", ""), n.get("doi", ""), n.get("title", ""),
                    n.get("first_author", ""), all_authors_json,
                    n.get("journal", ""), n.get("volume", ""), n.get("issue", ""),
                    n.get("pages", ""), n.get("cover_date", ""),
                    n.get("cited_by", 0), n.get("open_access", False),
                    n.get("abstract", ""), n.get("keywords", ""),
                    n.get("issn", ""), n.get("source_type", ""),
                    affiliations_json, idx_kw_json, subj_json,
                    json.dumps(merged_tags), _now(), eid,
                ])
                updated += 1
                _emit_event(conn, "article.updated", "article", eid,
                            {"title": n.get("title", "")})
            else:
                new_tags = sorted(set(tags or []))
                conn.execute("""
                    INSERT INTO articles (
                        eid, scopus_id, doi, title, first_author, all_authors,
                        journal, volume, issue, pages, cover_date, cited_by,
                        open_access, abstract, keywords, issn, source_type,
                        affiliations, index_keywords, subject_areas,
                        tags, notes, added_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, [
                    eid, n.get("scopus_id", ""), n.get("doi", ""),
                    n.get("title", ""), n.get("first_author", ""),
                    all_authors_json, n.get("journal", ""), n.get("volume", ""),
                    n.get("issue", ""), n.get("pages", ""),
                    n.get("cover_date", ""), n.get("cited_by", 0),
                    n.get("open_access", False), n.get("abstract", ""),
                    n.get("keywords", ""), n.get("issn", ""),
                    n.get("source_type", ""), affiliations_json,
                    idx_kw_json, subj_json,
                    json.dumps(new_tags), "", _now(), None,
                ])
                added += 1
                _emit_event(conn, "article.added", "article", eid,
                            {"title": n.get("title", "")})

            _upsert_authors_from_entry(conn, eid, entry, n)

        if collection:
            created = conn.execute(
                "SELECT name FROM collections WHERE name = ?", [collection]
            ).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO collections VALUES (?, ?)",
                [collection, _now()],
            )
            if not created:
                _emit_event(conn, "collection.created", "collection", collection, {})

            for entry in entries:
                eid = entry.get("eid", "")
                if not eid:
                    try:
                        eid = _normalize_entry(entry).get("eid", "")
                    except ValueError:
                        continue
                if not eid:
                    continue
                already = conn.execute(
                    "SELECT 1 FROM collection_articles WHERE collection_name = ? AND eid = ?",
                    [collection, eid],
                ).fetchone()
                conn.execute(
                    "INSERT OR IGNORE INTO collection_articles VALUES (?, ?)",
                    [collection, eid],
                )
                if not already:
                    _emit_event(conn, "article.added_to_collection",
                                "article", eid, {"collection": collection})

    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    if not defer_fts_rebuild and (added or updated):
        try:
            rebuild_fts()
        except Exception as exc:
            logger.warning("FTS index rebuild failed; search may be stale: %s", exc)
    return {"added": added, "updated": updated, "total": total}


def remove_entries(eids: list[str]) -> dict:
    """Remove articles by EID."""
    conn = _get_conn()
    removed = 0
    with _txn(conn):
        for eid in eids:
            existed = conn.execute(
                "SELECT 1 FROM articles WHERE eid = ?", [eid]
            ).fetchone()
            conn.execute("DELETE FROM articles WHERE eid = ?", [eid])
            conn.execute("DELETE FROM collection_articles WHERE eid = ?", [eid])
            conn.execute("DELETE FROM article_authors WHERE eid = ?", [eid])
            removed += 1
            if existed:
                _emit_event(conn, "article.removed", "article", eid, {})

        conn.execute("""
            DELETE FROM authors WHERE auid NOT IN (SELECT DISTINCT auid FROM article_authors)
        """)

    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    return {"removed": removed, "total": total}


def list_articles(
    tag: str | None = None,
    collection: str | None = None,
    query: str | None = None,
    sort: str = "added",
    limit: int = 50,
) -> dict:
    """List articles in the database with optional filters."""
    conn = _get_conn()

    where_clauses = []
    params = []

    if collection:
        where_clauses.append(
            "eid IN (SELECT eid FROM collection_articles WHERE collection_name = ?)"
        )
        params.append(collection)

    if tag:
        where_clauses.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    if query:
        where_clauses.append(
            "(LOWER(title) LIKE ? OR LOWER(first_author) LIKE ? "
            "OR LOWER(journal) LIKE ? OR LOWER(abstract) LIKE ?)"
        )
        q = f"%{query.lower()}%"
        params.extend([q, q, q, q])

    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sort_map = {
        "added": "added_at DESC",
        "cited": "cited_by DESC",
        "date": "cover_date DESC",
        "title": "LOWER(title) ASC",
    }
    order = sort_map.get(sort, "added_at DESC")

    # Get total matching
    count_row = conn.execute(
        f"SELECT COUNT(*) FROM articles{where}", params
    ).fetchone()
    total_matching = count_row[0]

    # Get total in DB
    total_in_db = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

    # Fetch rows
    rows = conn.execute(
        f"SELECT * FROM articles{where} ORDER BY {order} LIMIT ?",
        params + [limit],
    ).fetchall()

    columns = [desc[0] for desc in conn.description] if conn.description else _ARTICLE_COLUMNS
    articles = [_row_to_dict(row, columns) for row in rows]
    return {
        "articles": articles,
        "total_matching": total_matching,
        "total_in_db": total_in_db,
    }


def search_articles_fts(query: str, limit: int = 50) -> dict:
    """BM25-ranked full-text search over (title, abstract, keywords).

    Returns ``{"articles": [...], "total": n}`` where ``total`` is the
    number of matching rows (capped at ``limit``-equivalent semantics is
    not enforced; ``total`` reflects all hits with score > 0).

    Raises RuntimeError if the FTS extension is unavailable; callers
    that want a fallback should branch on :func:`fts_available` and call
    :func:`search_articles_like` instead.
    """
    conn = _get_conn()
    if not _ensure_fts(conn):
        raise RuntimeError("DuckDB fts extension unavailable")
    if conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0:
        return {"articles": [], "total": 0}
    # Ensure index exists; cheap rebuild on empty/missing.
    try:
        rebuild_fts()
    except Exception as exc:
        logger.warning("FTS index rebuild failed; search may be stale: %s", exc)

    sql = (
        "SELECT *, fts_main_articles.match_bm25(eid, ?) AS _score "
        "FROM articles "
        "WHERE fts_main_articles.match_bm25(eid, ?) IS NOT NULL "
        "ORDER BY _score DESC LIMIT ?"
    )
    rows = conn.execute(sql, [query, query, limit]).fetchall()
    columns = [desc[0] for desc in conn.description]
    articles = [_row_to_dict(row, columns) for row in rows]
    total = conn.execute(
        "SELECT COUNT(*) FROM articles "
        "WHERE fts_main_articles.match_bm25(eid, ?) IS NOT NULL",
        [query],
    ).fetchone()[0]
    return {"articles": articles, "total": total}


def search_articles_like(query: str, limit: int = 50) -> dict:
    """Trigram-style LIKE search over title/abstract/first_author/journal.

    Symmetric replacement for :func:`search_articles_fts` when the FTS
    extension isn't available. Exposed in core (not Swift) so the GUI
    holds no search logic of its own (Plan Principle 2).
    """
    conn = _get_conn()
    q = f"%{query.lower()}%"
    sql = (
        "SELECT * FROM articles WHERE "
        "LOWER(title) LIKE ? OR LOWER(abstract) LIKE ? "
        "OR LOWER(first_author) LIKE ? OR LOWER(journal) LIKE ? "
        "ORDER BY cited_by DESC LIMIT ?"
    )
    rows = conn.execute(sql, [q, q, q, q, limit]).fetchall()
    columns = [desc[0] for desc in conn.description]
    articles = [_row_to_dict(row, columns) for row in rows]
    total = conn.execute(
        "SELECT COUNT(*) FROM articles WHERE "
        "LOWER(title) LIKE ? OR LOWER(abstract) LIKE ? "
        "OR LOWER(first_author) LIKE ? OR LOWER(journal) LIKE ?",
        [q, q, q, q],
    ).fetchone()[0]
    return {"articles": articles, "total": total}


def fts_available() -> bool:
    """Probe whether the DuckDB fts extension is usable in this process."""
    return _ensure_fts(_get_conn())


def tag_articles(eids: list[str], tags: list[str]) -> dict:
    """Add tags to articles."""
    conn = _get_conn()
    tagged = 0
    with _txn(conn):
        for eid in eids:
            row = conn.execute("SELECT tags FROM articles WHERE eid = ?", [eid]).fetchone()
            if row:
                existing = json.loads(row[0]) if row[0] else []
                merged = sorted(set(existing) | set(tags))
                conn.execute("UPDATE articles SET tags = ? WHERE eid = ?",
                             [json.dumps(merged), eid])
                tagged += 1
                _emit_event(conn, "article.tagged", "article", eid, {"tags": list(tags)})
    return {"tagged": tagged, "tags": tags}


def untag_articles(eids: list[str], tags: list[str]) -> dict:
    """Remove tags from articles."""
    conn = _get_conn()
    untagged = 0
    with _txn(conn):
        for eid in eids:
            row = conn.execute("SELECT tags FROM articles WHERE eid = ?", [eid]).fetchone()
            if row:
                existing = set(json.loads(row[0]) if row[0] else [])
                existing -= set(tags)
                conn.execute("UPDATE articles SET tags = ? WHERE eid = ?",
                             [json.dumps(sorted(existing)), eid])
                untagged += 1
                _emit_event(conn, "article.untagged", "article", eid, {"tags": list(tags)})
    return {"untagged": untagged, "tags": tags}


def set_note(eid: str, note: str) -> dict:
    """Set a note on an article."""
    conn = _get_conn()
    row = conn.execute("SELECT eid FROM articles WHERE eid = ?", [eid]).fetchone()
    if not row:
        raise ValueError(f"Article not found: {eid}")
    with _txn(conn):
        conn.execute("UPDATE articles SET notes = ? WHERE eid = ?", [note, eid])
        _emit_event(conn, "article.note_set", "article", eid, {})
    return {"eid": eid, "note": note}


def get_article(eid: str) -> dict:
    """Get a single article by EID."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM articles WHERE eid = ?", [eid]).fetchone()
    if not row:
        raise ValueError(f"Article not found: {eid}")
    columns = [desc[0] for desc in conn.description]
    return _row_to_dict(row, columns)


# ── Collection management ────────────────────────────────────────────────────

def list_collections() -> dict:
    """List all collections with article counts."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.name, c.created_at, COUNT(ca.eid) as cnt
        FROM collections c
        LEFT JOIN collection_articles ca ON c.name = ca.collection_name
        GROUP BY c.name, c.created_at
    """).fetchall()
    result = {}
    for name, created, cnt in rows:
        result[name] = {"article_count": cnt, "created": created or ""}
    return {"collections": result}


def create_collection(name: str) -> dict:
    """Create a new empty collection."""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT name FROM collections WHERE name = ?", [name]
    ).fetchone()
    if existing:
        raise ValueError(f"Collection already exists: {name}")
    with _txn(conn):
        conn.execute("INSERT INTO collections VALUES (?, ?)", [name, _now()])
        _emit_event(conn, "collection.created", "collection", name, {})
    return {"created": name}


def delete_collection(name: str) -> dict:
    """Delete a collection (does not delete articles)."""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT name FROM collections WHERE name = ?", [name]
    ).fetchone()
    if not existing:
        raise ValueError(f"Collection not found: {name}")
    with _txn(conn):
        conn.execute("DELETE FROM collection_articles WHERE collection_name = ?", [name])
        conn.execute("DELETE FROM collections WHERE name = ?", [name])
        _emit_event(conn, "collection.deleted", "collection", name, {})
    return {"deleted": name}


def merge_collections(src: str, dst: str) -> dict:
    """Merge collection ``src`` into ``dst`` and delete ``src``.

    Set-union semantics: articles in both end up once in ``dst``. ``dst`` is
    auto-created if missing. ``src == dst`` is a no-op. Atomic — partial
    failure rolls back. Emits one ``collection.merged`` event.
    """
    conn = _get_conn()
    if src == dst:
        return {"merged_from": src, "merged_to": dst, "moved": 0, "noop": True}

    src_row = conn.execute(
        "SELECT name FROM collections WHERE name = ?", [src]
    ).fetchone()
    if not src_row:
        raise ValueError(f"Source collection not found: {src}")

    with _txn(conn):
        conn.execute(
            "INSERT OR IGNORE INTO collections VALUES (?, ?)", [dst, _now()]
        )
        before = conn.execute(
            "SELECT COUNT(*) FROM collection_articles WHERE collection_name = ?",
            [dst],
        ).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO collection_articles "
            "SELECT ?, eid FROM collection_articles WHERE collection_name = ?",
            [dst, src],
        )
        after = conn.execute(
            "SELECT COUNT(*) FROM collection_articles WHERE collection_name = ?",
            [dst],
        ).fetchone()[0]
        moved = after - before
        conn.execute(
            "DELETE FROM collection_articles WHERE collection_name = ?", [src]
        )
        conn.execute("DELETE FROM collections WHERE name = ?", [src])
        _emit_event(
            conn, "collection.merged", "collection", dst,
            {"merged_from": src, "moved": moved},
        )

    return {"merged_from": src, "merged_to": dst, "moved": moved}


def rename_collection(old: str, new: str) -> dict:
    """Rename a collection, preserving ``created_at`` and article membership."""
    conn = _get_conn()
    if old == new:
        return {"renamed_from": old, "renamed_to": new, "noop": True}
    src_row = conn.execute(
        "SELECT created_at FROM collections WHERE name = ?", [old]
    ).fetchone()
    if not src_row:
        raise ValueError(f"Collection not found: {old}")
    if conn.execute(
        "SELECT 1 FROM collections WHERE name = ?", [new]
    ).fetchone():
        raise ValueError(f"Collection already exists: {new}")

    created_at = src_row[0]
    with _txn(conn):
        conn.execute("INSERT INTO collections VALUES (?, ?)", [new, created_at])
        conn.execute(
            "UPDATE collection_articles SET collection_name = ? WHERE collection_name = ?",
            [new, old],
        )
        conn.execute("DELETE FROM collections WHERE name = ?", [old])
        _emit_event(
            conn, "collection.renamed", "collection", new,
            {"renamed_from": old, "created_at": created_at},
        )
    return {"renamed_from": old, "renamed_to": new, "created_at": created_at}


def add_to_collection(name: str, eids: list[str]) -> dict:
    """Add articles to a collection."""
    conn = _get_conn()
    added = 0
    with _txn(conn):
        created = conn.execute(
            "SELECT name FROM collections WHERE name = ?", [name]
        ).fetchone()
        conn.execute("INSERT OR IGNORE INTO collections VALUES (?, ?)", [name, _now()])
        if not created:
            _emit_event(conn, "collection.created", "collection", name, {})

        for eid in eids:
            exists = conn.execute(
                "SELECT eid FROM articles WHERE eid = ?", [eid]
            ).fetchone()
            if not exists:
                continue
            already = conn.execute(
                "SELECT 1 FROM collection_articles "
                "WHERE collection_name = ? AND eid = ?",
                [name, eid],
            ).fetchone()
            if already:
                continue
            try:
                conn.execute(
                    "INSERT INTO collection_articles VALUES (?, ?)", [name, eid]
                )
                added += 1
                _emit_event(conn, "article.added_to_collection",
                            "article", eid, {"collection": name})
            except duckdb.ConstraintException:
                pass
    total = conn.execute(
        "SELECT COUNT(*) FROM collection_articles WHERE collection_name = ?", [name]
    ).fetchone()[0]
    return {"collection": name, "added": added, "total": total}


def remove_from_collection(name: str, eids: list[str]) -> dict:
    """Remove articles from a collection."""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT name FROM collections WHERE name = ?", [name]
    ).fetchone()
    if not existing:
        raise ValueError(f"Collection not found: {name}")
    removed = 0
    with _txn(conn):
        for eid in eids:
            was_in = conn.execute(
                "SELECT 1 FROM collection_articles "
                "WHERE collection_name = ? AND eid = ?",
                [name, eid],
            ).fetchone()
            conn.execute(
                "DELETE FROM collection_articles WHERE collection_name = ? AND eid = ?",
                [name, eid],
            )
            removed += 1
            if was_in:
                _emit_event(conn, "article.removed_from_collection",
                            "article", eid, {"collection": name})
    total = conn.execute(
        "SELECT COUNT(*) FROM collection_articles WHERE collection_name = ?", [name]
    ).fetchone()[0]
    return {"collection": name, "removed": removed, "total": total}


# ── Stats ─────────────────────────────────────────────────────────────────────

def stats() -> dict:
    """Get database statistics."""
    conn = _get_conn()

    total_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    total_authors = conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    total_collections = conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]

    # Gather all tags
    tag_rows = conn.execute("SELECT tags FROM articles WHERE tags != '[]'").fetchall()
    tag_counts: dict[str, int] = {}
    for (tags_json,) in tag_rows:
        for t in json.loads(tags_json) if tags_json else []:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    # Year distribution
    year_rows = conn.execute("""
        SELECT SUBSTR(cover_date, 1, 4) as yr, COUNT(*) as cnt
        FROM articles
        WHERE cover_date IS NOT NULL AND cover_date != ''
        GROUP BY yr ORDER BY yr
    """).fetchall()
    year_counts = {yr: cnt for yr, cnt in year_rows}

    # DB file size
    db_size = round(DB_PATH.stat().st_size / 1024, 1) if DB_PATH.exists() else 0

    return {
        "total_articles": total_articles,
        "total_authors": total_authors,
        "total_collections": total_collections,
        "total_tags": len(tag_counts),
        "tags": tag_counts,
        "years": year_counts,
        "db_path": str(DB_PATH),
        "db_size_kb": db_size,
    }


# ── Author management ────────────────────────────────────────────────────────

def list_authors(
    query: str | None = None,
    sort: str = "papers",
    limit: int = 50,
) -> dict:
    """List authors in the database.

    Args:
        query: Text search in author name.
        sort: Sort by 'papers' (most articles), 'name', 'added'.
        limit: Max results.

    Returns:
        List of authors with article counts.
    """
    conn = _get_conn()

    where = ""
    params: list = []
    if query:
        where = " WHERE LOWER(a.name) LIKE ?"
        params.append(f"%{query.lower()}%")

    sort_map = {
        "papers": "paper_count DESC",
        "name": "LOWER(a.name) ASC",
        "added": "a.added_at DESC",
    }
    order = sort_map.get(sort, "paper_count DESC")

    rows = conn.execute(f"""
        SELECT a.auid, a.name, a.affiliations, a.h_index, a.document_count,
               a.cited_by_count, a.orcid, a.notes, a.added_at,
               COUNT(aa.eid) as paper_count
        FROM authors a
        LEFT JOIN article_authors aa ON a.auid = aa.auid
        {where}
        GROUP BY a.auid, a.name, a.affiliations, a.h_index, a.document_count,
                 a.cited_by_count, a.orcid, a.notes, a.added_at
        ORDER BY {order}
        LIMIT ?
    """, params + [limit]).fetchall()

    total = conn.execute(f"SELECT COUNT(*) FROM authors{'  WHERE LOWER(name) LIKE ?' if query else ''}", params).fetchone()[0]

    authors = []
    for row in rows:
        auid, name, affiliations, h_index, doc_count, cited_by, orcid, notes, added_at, paper_count = row
        affs = json.loads(affiliations) if affiliations else []
        authors.append({
            "auid": auid,
            "name": name,
            "affiliations": affs,
            "h_index": h_index,
            "document_count": doc_count,
            "cited_by_count": cited_by,
            "orcid": orcid or "",
            "notes": notes or "",
            "added_at": added_at or "",
            "paper_count": paper_count,
        })

    return {"authors": authors, "total": total}


def get_author(auid: str) -> dict:
    """Get a single author with their articles.

    Args:
        auid: Scopus Author ID.

    Returns:
        Author info with list of their articles in the DB.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT auid, name, affiliations, h_index, document_count, "
        "cited_by_count, citation_count, coauthor_count, orcid, "
        "subject_areas, notes, added_at, fetched_at "
        "FROM authors WHERE auid = ?",
        [auid],
    ).fetchone()
    if not row:
        raise ValueError(f"Author not found: {auid}")

    (auid, name, affiliations, h_index, doc_count, cited_by, citation_count,
     coauthor_count, orcid, subject_areas_json, notes, added_at, fetched_at) = row
    affs = json.loads(affiliations) if affiliations else []
    subj_areas = json.loads(subject_areas_json) if subject_areas_json else []

    # Get their articles
    article_rows = conn.execute("""
        SELECT a.eid, a.title, a.journal, a.cover_date, a.cited_by, a.doi,
               aa.seq, aa.is_first, aa.is_corresponding
        FROM articles a
        JOIN article_authors aa ON a.eid = aa.eid
        WHERE aa.auid = ?
        ORDER BY a.cover_date DESC
    """, [auid]).fetchall()

    articles = []
    for eid, title, journal, cover_date, cited_by, doi, seq, is_first, is_corr in article_rows:
        articles.append({
            "eid": eid,
            "title": title,
            "journal": journal,
            "cover_date": cover_date,
            "cited_by": cited_by,
            "doi": doi,
            "author_position": seq,
            "is_first_author": bool(is_first),
            "is_corresponding": bool(is_corr),
        })

    # Find co-authors (other authors who share articles)
    coauthor_rows = conn.execute("""
        SELECT au.auid, au.name, COUNT(*) as shared_papers
        FROM article_authors aa1
        JOIN article_authors aa2 ON aa1.eid = aa2.eid AND aa1.auid != aa2.auid
        JOIN authors au ON aa2.auid = au.auid
        WHERE aa1.auid = ?
        GROUP BY au.auid, au.name
        ORDER BY shared_papers DESC
        LIMIT 20
    """, [auid]).fetchall()

    coauthors = [
        {"auid": ca_auid, "name": ca_name, "shared_papers": cnt}
        for ca_auid, ca_name, cnt in coauthor_rows
    ]

    return {
        "auid": auid,
        "name": name,
        "affiliations": affs,
        "h_index": h_index,
        "document_count": doc_count,
        "cited_by_count": cited_by,
        "citation_count": citation_count,
        "coauthor_count": coauthor_count,
        "orcid": orcid or "",
        "subject_areas": subj_areas,
        "notes": notes or "",
        "added_at": added_at or "",
        "fetched_at": fetched_at or "",
        "paper_count": len(articles),
        "articles": articles,
        "coauthors": coauthors,
    }


def fetch_author_profile(auid: str) -> dict:
    """Fetch full author profile from Scopus API and save to DB.

    Retrieves h-index, document count, citation counts, co-author count,
    ORCID, and subject areas from the Author Retrieval API.

    Args:
        auid: Scopus Author ID.

    Returns:
        Updated author profile.
    """
    from scopus_for_dobby.utils.api_client import api_get

    # Fetch from API (ENHANCED view gives most data except metrics)
    resp = api_get(
        f"/content/author/author_id/{auid}",
        params={"view": "ENHANCED"},
    )
    ar = resp.get("author-retrieval-response", [{}])
    if isinstance(ar, list):
        ar = ar[0]

    core = ar.get("coredata", {})

    # Parse name
    profile = ar.get("author-profile", {})
    pref_name = profile.get("preferred-name", {})
    name = pref_name.get("indexed-name", "") or pref_name.get("surname", "")

    # Parse metrics
    h_index = ar.get("h-index")
    if h_index is not None:
        h_index = int(h_index)
    coauthor_count = ar.get("coauthor-count")
    if coauthor_count is not None:
        coauthor_count = int(coauthor_count)

    doc_count = core.get("document-count")
    if doc_count is not None:
        doc_count = int(doc_count)
    cited_by = core.get("cited-by-count")
    if cited_by is not None:
        cited_by = int(cited_by)
    citation_count = core.get("citation-count")
    if citation_count is not None:
        citation_count = int(citation_count)

    orcid = core.get("orcid", "")

    # Parse subject areas
    subj_block = ar.get("subject-areas", {})
    subject_areas = []
    if isinstance(subj_block, dict):
        for area in subj_block.get("subject-area", []):
            if isinstance(area, dict):
                subject_areas.append({
                    "name": area.get("$", ""),
                    "code": area.get("@code", ""),
                    "abbrev": area.get("@abbrev", ""),
                })

    # Parse current affiliation
    aff_current = profile.get("affiliation-current", {})
    if isinstance(aff_current, dict):
        aff_current = aff_current.get("affiliation", {})
    affiliations = []
    if isinstance(aff_current, dict):
        aff_name = (aff_current.get("ip-doc", {}).get("afdispname", "")
                    or aff_current.get("ip-doc", {}).get("preferred-name", {}).get("$", ""))
        if aff_name:
            affiliations.append(aff_name)
    elif isinstance(aff_current, list):
        for afc in aff_current:
            aff_name = (afc.get("ip-doc", {}).get("afdispname", "")
                        or afc.get("ip-doc", {}).get("preferred-name", {}).get("$", ""))
            if aff_name:
                affiliations.append(aff_name)

    # Upsert into DB
    conn = _get_conn()
    existing = conn.execute("SELECT auid FROM authors WHERE auid = ?", [auid]).fetchone()

    with _txn(conn):
        if existing:
            conn.execute("""
                UPDATE authors SET
                    name=?, affiliations=?, h_index=?, document_count=?,
                    cited_by_count=?, citation_count=?, coauthor_count=?,
                    orcid=?, subject_areas=?, updated_at=?, fetched_at=?
                WHERE auid=?
            """, [
                name, json.dumps(affiliations), h_index, doc_count,
                cited_by, citation_count, coauthor_count,
                orcid, json.dumps(subject_areas), _now(), _now(), auid,
            ])
        else:
            conn.execute("""
                INSERT INTO authors (
                    auid, name, affiliations, h_index, document_count,
                    cited_by_count, citation_count, coauthor_count,
                    orcid, subject_areas, notes, added_at, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                auid, name, json.dumps(affiliations), h_index, doc_count,
                cited_by, citation_count, coauthor_count,
                orcid, json.dumps(subject_areas), "", _now(), _now(),
            ])
        _emit_event(conn, "author.profile_fetched", "author", auid, {"name": name})

    return {
        "auid": auid,
        "name": name,
        "affiliations": affiliations,
        "h_index": h_index,
        "document_count": doc_count,
        "cited_by_count": cited_by,
        "citation_count": citation_count,
        "coauthor_count": coauthor_count,
        "orcid": orcid,
        "subject_areas": subject_areas,
    }


def set_author_note(auid: str, note: str) -> dict:
    """Set a note on an author."""
    conn = _get_conn()
    row = conn.execute("SELECT auid FROM authors WHERE auid = ?", [auid]).fetchone()
    if not row:
        raise ValueError(f"Author not found: {auid}")
    with _txn(conn):
        conn.execute("UPDATE authors SET notes = ? WHERE auid = ?", [note, auid])
        _emit_event(conn, "author.note_set", "author", auid, {})
    return {"auid": auid, "note": note}


def find_coauthors(auid: str) -> dict:
    """Find all co-authors of a given author from the local DB.

    Returns:
        List of co-authors with shared paper counts.
    """
    conn = _get_conn()
    row = conn.execute("SELECT name FROM authors WHERE auid = ?", [auid]).fetchone()
    if not row:
        raise ValueError(f"Author not found: {auid}")
    author_name = row[0]

    rows = conn.execute("""
        SELECT au.auid, au.name, au.affiliations, COUNT(*) as shared_papers
        FROM article_authors aa1
        JOIN article_authors aa2 ON aa1.eid = aa2.eid AND aa1.auid != aa2.auid
        JOIN authors au ON aa2.auid = au.auid
        WHERE aa1.auid = ?
        GROUP BY au.auid, au.name, au.affiliations
        ORDER BY shared_papers DESC
    """, [auid]).fetchall()

    coauthors = []
    for ca_auid, ca_name, ca_affs, cnt in rows:
        affs = json.loads(ca_affs) if ca_affs else []
        coauthors.append({
            "auid": ca_auid,
            "name": ca_name,
            "affiliations": affs,
            "shared_papers": cnt,
        })

    return {
        "author": {"auid": auid, "name": author_name},
        "coauthors": coauthors,
        "total": len(coauthors),
    }
