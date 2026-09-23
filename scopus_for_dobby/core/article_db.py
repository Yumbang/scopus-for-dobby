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
import re
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
SCHEMA_VERSION = 4

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


# v1 → v2: OpenAlex enrichment columns, as (name, DDL) so the migration can
# report which ones it actually had to add.
_V2_ARTICLE_COLUMNS = (
    ("openalex_id", "openalex_id VARCHAR DEFAULT ''"),
    ("oa_status", "oa_status VARCHAR DEFAULT ''"),
    ("oa_url", "oa_url VARCHAR DEFAULT ''"),
    ("openalex_cited_by", "openalex_cited_by INTEGER DEFAULT 0"),
    ("openalex_topics", "openalex_topics JSON DEFAULT '[]'"),
    ("openalex_enriched_at", "openalex_enriched_at VARCHAR DEFAULT ''"),
)

# v2 → v3: stamp that Elsevier full-text XML has been cached on disk.
# The body itself is never a column — see core/fulltext.py.
_V3_ARTICLE_COLUMNS = (("fulltext_fetched_at", "fulltext_fetched_at VARCHAR DEFAULT ''"),)

# v3 → v4: a collection may belong to one project. NULL means ungrouped.
# Deliberately no index on ``collections``: DuckDB refuses ALTER TABLE on a
# table with a dependent index, which would block every later migration here.
_V4_COLLECTION_COLUMNS = (("project", "project VARCHAR"),)


def _add_missing_columns(
    conn: duckdb.DuckDBPyConnection, table: str, spec: tuple[tuple[str, str], ...]
) -> list[str]:
    """Add any missing columns from ``spec`` to ``table``. Idempotent. Returns names added."""
    present = {
        r[0]
        for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ?",
            [table],
        ).fetchall()
    }
    added = []
    for name, col_ddl in spec:
        if name not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_ddl}")  # noqa: S608
            added.append(name)
    return added


def _add_missing_article_columns(
    conn: duckdb.DuckDBPyConnection, spec: tuple[tuple[str, str], ...]
) -> list[str]:
    """Add any missing ``articles`` columns from ``spec``. Idempotent. Returns names added."""
    return _add_missing_columns(conn, "articles", spec)


def _migrate_v1_to_v2(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Add any missing v2 columns to ``articles``. Returns the names added.

    Idempotent, and driven by the columns actually present rather than by the
    version stamp — so it doubles as the repair path for databases whose stamp
    does not match what is on disk. A half-applied migration self-heals on the
    next open.
    """
    return _add_missing_article_columns(conn, _V2_ARTICLE_COLUMNS)


def _ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create tables if they don't exist. Idempotent; runs at most once per process per DB."""
    path = Path(DB_PATH)
    if path in _schema_initialized:
        return
    # Whether `articles` already exists must be sampled BEFORE any DDL runs:
    # it is the only way to tell a brand-new database (safe to stamp with the
    # current version) from one that predates `schema_meta` and still needs
    # every migration. See the version gate at the end of this function.
    pre_existing_db = bool(
        conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = 'articles'"
        ).fetchone()
    )
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
            updated_at      VARCHAR,
            openalex_id          VARCHAR DEFAULT '',
            oa_status            VARCHAR DEFAULT '',
            oa_url               VARCHAR DEFAULT '',
            openalex_cited_by    INTEGER DEFAULT 0,
            openalex_topics      JSON DEFAULT '[]',
            openalex_enriched_at VARCHAR DEFAULT '',
            fulltext_fetched_at  VARCHAR DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS collections (
            name       VARCHAR PRIMARY KEY,
            created_at VARCHAR,
            project    VARCHAR
        )
    """)
    # One level above collections. Membership lives on ``collections.project``
    # (a collection is in at most one project); integrity is kept in code.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
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
    # The primary key leads with collection_name, which answers "what is in
    # this collection". The reverse — "which collections hold this article" —
    # cannot use that as a prefix and would scan the whole membership table.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_collection_articles_eid ON collection_articles(eid)"
    )
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
    # framework — just a gate migrations branch on. A fresh DB is stamped with
    # SCHEMA_VERSION; older DBs are migrated forward in place below.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_meta (
            version INTEGER NOT NULL
        )
    """)
    row = conn.execute("SELECT version FROM schema_meta").fetchone()
    if row is None:
        # No version stamp. Two very different databases land here:
        #   * a brand-new one — nothing to migrate, stamp the current version;
        #   * one created before `schema_meta` existed — it holds v1 tables and
        #     must be migrated forward, so stamp it v1 and let the gate below
        #     do the work.
        # Stamping both with SCHEMA_VERSION (the original behaviour) silently
        # marked legacy databases as up to date and skipped every migration —
        # they kept working for reads, then failed on any query naming a column
        # the migration was supposed to add.
        version = SCHEMA_VERSION if not pre_existing_db else 1
        conn.execute("INSERT INTO schema_meta (version) VALUES (?)", [version])
    else:
        version = row[0]

    if version > SCHEMA_VERSION:
        # A newer install has migrated this file. Writing to it with this
        # code's DDL assumptions fails in obscure ways (v3 code, for one,
        # cannot insert into v4's three-column ``collections``), so refuse
        # up front with something the user can act on.
        raise RuntimeError(
            f"{path} was written by a newer scopus-for-dobby (schema v{version}; "
            f"this install understands up to v{SCHEMA_VERSION}). Upgrade this "
            'install — e.g. `uv tool install --reinstall --editable ".[gui]"`.'
        )

    # Reconcile the columns that actually exist against what the current schema
    # expects. This runs regardless of the stamp: databases mis-stamped by the
    # bug described above already exist in the wild, and a version number is
    # only evidence about migrations that ran — not about the shape on disk.
    migrating = version < SCHEMA_VERSION
    added = _migrate_v1_to_v2(conn)
    added += _add_missing_article_columns(conn, _V3_ARTICLE_COLUMNS)
    added += _add_missing_columns(conn, "collections", _V4_COLLECTION_COLUMNS)

    if migrating:
        conn.execute("UPDATE schema_meta SET version = ?", [SCHEMA_VERSION])
    elif added:
        logger.warning(
            "Repaired schema drift in %s: added missing column(s) %s. The "
            "database was stamped v%s but those columns were absent.",
            path,
            ", ".join(added),
            version,
        )

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
            "'keywords', 'notes', overwrite=1)"
        )
    return {"rebuilt": True, "rows": n}


def _strip_accents(s: str) -> str:
    """Normalize accented characters to ASCII for author-name comparison."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


# "j." / "k.h." / "k.h" — an initials token, never a spelled-out name part.
_INITIALS = re.compile(r"^[a-z](?:\.[a-z])*\.?$")


def _name_keys(s: str) -> set[str]:
    """Comparable keys for a personal name.

    Two incompatible spellings reach this function for the same person:
    Scopus indexes surname-first with initials (``Cho K.H.``), while Elsevier
    full text spells the given name out first (``Kyung Hwa Cho``). Both are
    reduced to ``surname + given initial`` so they compare equal — matching on
    the raw string, or assuming a fixed token order, misses every time.
    """
    raw = _strip_accents(s or "").lower().replace(",", " ")
    raw = " ".join(raw.split())
    if not raw:
        return set()
    keys = {raw}
    tokens = [t for t in raw.split() if t]
    if len(tokens) < 2:
        return keys
    if any(_INITIALS.match(t) for t in tokens[1:]):
        surname, given = tokens[0], tokens[1]  # "Cho K.H."
    else:
        surname, given = tokens[-1], tokens[0]  # "Kyung Hwa Cho"
    surname = surname.replace(".", "")
    if surname and given:
        keys.add(f"{surname} {given[0]}")
    return keys


def _names_hit(name: str, candidates: set[str]) -> bool:
    keys = _name_keys(name)
    return any(keys & _name_keys(c) for c in candidates)


def _row_to_dict(row: tuple, columns: list[str]) -> dict:
    """Convert a DuckDB row tuple to a dict, parsing JSON fields."""
    d = dict(zip(columns, row, strict=False))
    # Parse JSON fields
    for key in (
        "all_authors",
        "affiliations",
        "index_keywords",
        "subject_areas",
        "tags",
        "openalex_topics",
    ):
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
    "eid",
    "scopus_id",
    "doi",
    "title",
    "first_author",
    "all_authors",
    "journal",
    "volume",
    "issue",
    "pages",
    "cover_date",
    "cited_by",
    "open_access",
    "abstract",
    "keywords",
    "issn",
    "source_type",
    "affiliations",
    "index_keywords",
    "subject_areas",
    "tags",
    "notes",
    "added_at",
    "updated_at",
    "openalex_id",
    "oa_status",
    "oa_url",
    "openalex_cited_by",
    "openalex_topics",
    "openalex_enriched_at",
    "fulltext_fetched_at",
]


# Every LIKE-based search matches these. The first four are what the FTS
# index covers, so a query means the same thing whether or not the extension
# loaded; first_author and journal are additions the fallback can afford
# because it is scanning anyway. Previously the fallback silently dropped
# `keywords`, so the two paths returned different result sets.
_LIKE_SEARCH_COLUMNS = ("title", "abstract", "keywords", "notes", "first_author", "journal")

_LIKE_SEARCH_PREDICATE = " OR ".join(f"LOWER({c}) LIKE ?" for c in _LIKE_SEARCH_COLUMNS)


# ── Normalize ────────────────────────────────────────────────────────────────


def _normalize_entry(entry: dict) -> dict:
    """Normalize a Scopus search entry or abstract result into DB format."""
    if "dc:title" in entry:
        creator = entry.get("dc:creator", "")
        if isinstance(creator, dict):
            authors = creator.get("author", [])
            first_author = (
                authors[0].get("preferred-name", {}).get("ce:indexed-name", "") if authors else ""
            )
        else:
            first_author = str(creator)

        all_authors = []
        for a in entry.get("author", []):
            all_authors.append(
                {
                    "name": a.get("authname", ""),
                    "auid": a.get("authid", ""),
                }
            )

        sid = entry.get("dc:identifier", "")
        scopus_id = str(sid).replace("SCOPUS_ID:", "") if sid else ""

        affs = []
        for a in entry.get("affiliation", []) if isinstance(entry.get("affiliation"), list) else []:
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
                authors_to_link.append(
                    {
                        "auid": str(auid),
                        "name": name,
                        "seq": seq,
                        "aff_ids": aff_ids,
                    }
                )

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
                        authors_to_link.append(
                            {
                                "auid": str(auid),
                                "name": name,
                                "seq": seq,
                                "aff_ids": [],
                            }
                        )

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


def add_entries(
    entries: list[dict],
    tags: list[str] | None = None,
    collection: str | None = None,
    defer_fts_rebuild: bool = False,
) -> dict:
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
                conn.execute(
                    """
                    UPDATE articles SET
                        scopus_id=?, doi=?, title=?, first_author=?, all_authors=?,
                        journal=?, volume=?, issue=?, pages=?, cover_date=?,
                        cited_by=?, open_access=?, abstract=?, keywords=?, issn=?,
                        source_type=?, affiliations=?, index_keywords=?,
                        subject_areas=?, tags=?, updated_at=?
                    WHERE eid = ?
                """,
                    [
                        n.get("scopus_id", ""),
                        n.get("doi", ""),
                        n.get("title", ""),
                        n.get("first_author", ""),
                        all_authors_json,
                        n.get("journal", ""),
                        n.get("volume", ""),
                        n.get("issue", ""),
                        n.get("pages", ""),
                        n.get("cover_date", ""),
                        n.get("cited_by", 0),
                        n.get("open_access", False),
                        n.get("abstract", ""),
                        n.get("keywords", ""),
                        n.get("issn", ""),
                        n.get("source_type", ""),
                        affiliations_json,
                        idx_kw_json,
                        subj_json,
                        json.dumps(merged_tags),
                        _now(),
                        eid,
                    ],
                )
                updated += 1
                _emit_event(conn, "article.updated", "article", eid, {"title": n.get("title", "")})
            else:
                new_tags = sorted(set(tags or []))
                conn.execute(
                    """
                    INSERT INTO articles (
                        eid, scopus_id, doi, title, first_author, all_authors,
                        journal, volume, issue, pages, cover_date, cited_by,
                        open_access, abstract, keywords, issn, source_type,
                        affiliations, index_keywords, subject_areas,
                        tags, notes, added_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    [
                        eid,
                        n.get("scopus_id", ""),
                        n.get("doi", ""),
                        n.get("title", ""),
                        n.get("first_author", ""),
                        all_authors_json,
                        n.get("journal", ""),
                        n.get("volume", ""),
                        n.get("issue", ""),
                        n.get("pages", ""),
                        n.get("cover_date", ""),
                        n.get("cited_by", 0),
                        n.get("open_access", False),
                        n.get("abstract", ""),
                        n.get("keywords", ""),
                        n.get("issn", ""),
                        n.get("source_type", ""),
                        affiliations_json,
                        idx_kw_json,
                        subj_json,
                        json.dumps(new_tags),
                        "",
                        _now(),
                        None,
                    ],
                )
                added += 1
                _emit_event(conn, "article.added", "article", eid, {"title": n.get("title", "")})

            _upsert_authors_from_entry(conn, eid, entry, n)

        if collection:
            created = conn.execute(
                "SELECT name FROM collections WHERE name = ?", [collection]
            ).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO collections (name, created_at) VALUES (?, ?)",
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
                    _emit_event(
                        conn,
                        "article.added_to_collection",
                        "article",
                        eid,
                        {"collection": collection},
                    )

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
            existed = conn.execute("SELECT 1 FROM articles WHERE eid = ?", [eid]).fetchone()
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
    project: str | None = None,
) -> dict:
    """List articles in the database with optional filters.

    ``project`` selects the deduplicated union of its member collections. It
    is exclusive with ``collection`` and, unlike an unknown collection, an
    unknown project raises — a typo should be loud, not an empty result.
    """
    conn = _get_conn()

    if project is not None and collection:
        raise ValueError("Pass either a project or a collection, not both")

    where_clauses = []
    params = []

    if project is not None:
        if not conn.execute("SELECT 1 FROM projects WHERE name = ?", [project]).fetchone():
            raise ValueError(f"Project not found: {project}")
        where_clauses.append(
            "eid IN (SELECT ca.eid FROM collection_articles ca "
            "JOIN collections c ON c.name = ca.collection_name WHERE c.project = ?)"
        )
        params.append(project)

    if collection:
        where_clauses.append(
            "eid IN (SELECT eid FROM collection_articles WHERE collection_name = ?)"
        )
        params.append(collection)

    if tag:
        where_clauses.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    if query:
        where_clauses.append(f"({_LIKE_SEARCH_PREDICATE})")
        params.extend([f"%{query.lower()}%"] * len(_LIKE_SEARCH_COLUMNS))

    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sort_map = {
        "added": "added_at DESC",
        "cited": "cited_by DESC",
        "date": "cover_date DESC",
        "title": "LOWER(title) ASC",
    }
    order = sort_map.get(sort, "added_at DESC")

    # Get total matching
    count_row = conn.execute(f"SELECT COUNT(*) FROM articles{where}", params).fetchone()
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
    """BM25-ranked full-text search over (title, abstract, keywords, notes).

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
        "SELECT COUNT(*) FROM articles WHERE fts_main_articles.match_bm25(eid, ?) IS NOT NULL",
        [query],
    ).fetchone()[0]
    return {"articles": articles, "total": total}


def search_articles_like(query: str, limit: int = 50) -> dict:
    """LIKE search over title/abstract/keywords/notes/first_author/journal.

    Replacement for :func:`search_articles_fts` when the FTS extension isn't
    available. It covers every column FTS indexes, so switching paths cannot
    change which articles match — only their order, since FTS ranks by BM25
    and this ranks by citations. Exposed in core (not Swift) so the GUI holds
    no search logic of its own (Plan Principle 2).
    """
    conn = _get_conn()
    q = f"%{query.lower()}%"
    params = [q] * len(_LIKE_SEARCH_COLUMNS)
    rows = conn.execute(
        f"SELECT * FROM articles WHERE {_LIKE_SEARCH_PREDICATE} "  # noqa: S608
        "ORDER BY cited_by DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    columns = [desc[0] for desc in conn.description]
    articles = [_row_to_dict(row, columns) for row in rows]
    total = conn.execute(
        f"SELECT COUNT(*) FROM articles WHERE {_LIKE_SEARCH_PREDICATE}",  # noqa: S608
        params,
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
                conn.execute(
                    "UPDATE articles SET tags = ? WHERE eid = ?", [json.dumps(merged), eid]
                )
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
                conn.execute(
                    "UPDATE articles SET tags = ? WHERE eid = ?",
                    [json.dumps(sorted(existing)), eid],
                )
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


def enrich_articles(enrichments: list[dict]) -> dict:
    """Apply OpenAlex enrichment fields to existing articles (matched by eid).

    Each enrichment dict carries ``eid`` plus the fields produced by
    ``core.openalex.normalize_enrichment``. Unknown EIDs are skipped.
    """
    conn = _get_conn()
    enriched = 0
    skipped = 0
    with _txn(conn):
        for e in enrichments:
            eid = e.get("eid")
            if (
                not eid
                or not conn.execute("SELECT eid FROM articles WHERE eid = ?", [eid]).fetchone()
            ):
                skipped += 1
                continue
            conn.execute(
                "UPDATE articles SET openalex_id = ?, oa_status = ?, oa_url = ?, "
                "openalex_cited_by = ?, openalex_topics = ?, openalex_enriched_at = ? "
                "WHERE eid = ?",
                [
                    e.get("openalex_id", ""),
                    e.get("oa_status", ""),
                    e.get("oa_url", ""),
                    int(e.get("cited_by_count") or 0),
                    json.dumps(e.get("topics") or []),
                    _now(),
                    eid,
                ],
            )
            enriched += 1
            _emit_event(
                conn,
                "article.enriched",
                "article",
                eid,
                {"openalex_id": e.get("openalex_id", "")},
            )
    return {"enriched": enriched, "skipped": skipped}


def collections_for_eids(eids: list[str]) -> dict[str, list[str]]:
    """Which collections hold each of these articles.

    One grouped query, not one per article: a list view asking per row would
    be N scans. Articles in no collection are absent from the result rather
    than present with an empty list — callers use ``.get(eid, [])``.
    """
    eids = [e for e in eids if e]
    if not eids:
        return {}
    placeholders = ",".join("?" * len(eids))
    rows = (
        _get_conn()
        .execute(
            "SELECT eid, collection_name FROM collection_articles "  # noqa: S608
            f"WHERE eid IN ({placeholders}) ORDER BY collection_name",
            eids,
        )
        .fetchall()
    )
    out: dict[str, list[str]] = {}
    for eid, name in rows:
        out.setdefault(eid, []).append(name)
    return out


def get_article(eid: str) -> dict:
    """Get a single article by EID, with its collection membership.

    ``collections`` is carried here and not on list rows: the detail pane is
    the only place that needs it, and adding a join to every listed row would
    cost far more than it buys.
    """
    conn = _get_conn()
    row = conn.execute("SELECT * FROM articles WHERE eid = ?", [eid]).fetchone()
    if not row:
        raise ValueError(f"Article not found: {eid}")
    columns = [desc[0] for desc in conn.description]
    article = _row_to_dict(row, columns)
    article["collections"] = collections_for_eids([eid]).get(eid, [])
    article["projects"] = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT p.name FROM collection_articles ca "
            "JOIN collections c ON c.name = ca.collection_name "
            "JOIN projects p ON p.name = c.project "
            "WHERE ca.eid = ? ORDER BY p.name",
            [eid],
        ).fetchall()
    ]
    return article


def lookup_article(identifier: str) -> dict | None:
    """Resolve a DOI, Scopus EID, or Scopus ID to a stored article, or None."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    conn = _get_conn()
    if ident.startswith("2-s2.0-"):
        row = conn.execute("SELECT * FROM articles WHERE eid = ?", [ident]).fetchone()
    elif "/" in ident:
        doi = ident.lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.startswith(prefix):
                doi = doi[len(prefix) :]
        row = conn.execute("SELECT * FROM articles WHERE lower(doi) = ?", [doi]).fetchone()
    else:
        sid = ident[len("SCOPUS_ID:") :] if ident.startswith("SCOPUS_ID:") else ident
        row = conn.execute(
            "SELECT * FROM articles WHERE scopus_id = ? OR eid = ?",
            [sid, ident],
        ).fetchone()
    if not row:
        return None
    columns = [desc[0] for desc in conn.description]
    return _row_to_dict(row, columns)


def record_fulltext_fetch(eid: str, roles: dict | None = None) -> dict:
    """Stamp ``fulltext_fetched_at`` and optionally update author-role flags.

    Unknown EIDs are skipped — the XML may still live on disk for a paper
    that is not in the library. ``roles`` is the dict from
    ``core.fulltext.parse_roles``; empty first/corr lists leave existing
    flags alone.
    """
    conn = _get_conn()
    row = conn.execute("SELECT eid FROM articles WHERE eid = ?", [eid]).fetchone()
    if not row:
        return {"eid": eid, "stamped": False, "roles_updated": 0}

    now = _now()
    roles = roles or {}
    first_auids = {str(a) for a in (roles.get("first_auids") or []) if a and str(a).isdigit()}
    first_names = {n for n in (roles.get("first_names") or []) if n}
    corr_auids = {str(a) for a in (roles.get("corr_auids") or []) if a and str(a).isdigit()}
    corr_names = {n for n in (roles.get("corr_names") or []) if n}
    have_first = bool(first_auids or first_names)
    have_corr = bool(corr_auids or corr_names)

    links = conn.execute(
        "SELECT aa.auid, au.name, aa.is_first, aa.is_corresponding "
        "FROM article_authors aa JOIN authors au ON aa.auid = au.auid "
        "WHERE aa.eid = ?",
        [eid],
    ).fetchall()

    roles_updated = 0
    with _txn(conn):
        conn.execute(
            "UPDATE articles SET fulltext_fetched_at = ?, updated_at = ? WHERE eid = ?",
            [now, now, eid],
        )
        _emit_event(
            conn,
            "article.fulltext_fetched",
            "article",
            eid,
            {"roles": bool(have_first or have_corr)},
        )
        for auid, name, was_first, was_corr in links:
            is_first = was_first
            is_corr = was_corr
            # Both flags are only ever raised, never cleared. ``is_first`` is
            # written at import time as ``seq == 1``; full text adds the *co*-first
            # authors named in a footnote. Reassigning it would erase the
            # first-listed author whenever the footnote parse matched nobody.
            if have_first and (auid in first_auids or _names_hit(name or "", first_names)):
                is_first = True
            if have_corr and (auid in corr_auids or _names_hit(name or "", corr_names)):
                is_corr = True
            if is_first == was_first and is_corr == was_corr:
                continue
            conn.execute(
                "UPDATE article_authors SET is_first = ?, is_corresponding = ? "
                "WHERE eid = ? AND auid = ?",
                [is_first, is_corr, eid, auid],
            )
            roles_updated += 1

    return {"eid": eid, "stamped": True, "roles_updated": roles_updated, "fetched_at": now}


# ── Collection management ────────────────────────────────────────────────────


def list_collections() -> dict:
    """List all collections with article counts and the project each is in."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.name, c.created_at, c.project, COUNT(ca.eid) as cnt
        FROM collections c
        LEFT JOIN collection_articles ca ON c.name = ca.collection_name
        GROUP BY c.name, c.created_at, c.project
    """).fetchall()
    result = {}
    for name, created, project, cnt in rows:
        result[name] = {"article_count": cnt, "created": created or "", "project": project}
    return {"collections": result}


def create_collection(name: str, project: str | None = None) -> dict:
    """Create a new empty collection, optionally filed straight into ``project``.

    A missing ``project`` is created, as ``assign_collections`` would.
    """
    if project is not None:
        _check_project_name(project)
    conn = _get_conn()
    existing = conn.execute("SELECT name FROM collections WHERE name = ?", [name]).fetchone()
    if existing:
        raise ValueError(f"Collection already exists: {name}")
    project_created = False
    with _txn(conn):
        if project:
            project_created = _ensure_project(conn, project)
        conn.execute(
            "INSERT INTO collections (name, created_at, project) VALUES (?, ?, ?)",
            [name, _now(), project or None],
        )
        _emit_event(conn, "collection.created", "collection", name, {"project": project or None})
    result = {"created": name}
    if project:
        result["project"] = project
        result["project_created"] = project_created
    return result


def delete_collection(name: str) -> dict:
    """Delete a collection (does not delete articles)."""
    conn = _get_conn()
    existing = conn.execute("SELECT name FROM collections WHERE name = ?", [name]).fetchone()
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
    auto-created if missing, and then inherits ``src``'s project; an existing
    ``dst`` keeps its own. ``src == dst`` is a no-op. Atomic — partial
    failure rolls back. Emits one ``collection.merged`` event.
    """
    conn = _get_conn()
    if src == dst:
        return {"merged_from": src, "merged_to": dst, "moved": 0, "noop": True}

    src_row = conn.execute("SELECT project FROM collections WHERE name = ?", [src]).fetchone()
    if not src_row:
        raise ValueError(f"Source collection not found: {src}")

    with _txn(conn):
        conn.execute(
            "INSERT OR IGNORE INTO collections (name, created_at, project) VALUES (?, ?, ?)",
            [dst, _now(), src_row[0]],
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
        conn.execute("DELETE FROM collection_articles WHERE collection_name = ?", [src])
        conn.execute("DELETE FROM collections WHERE name = ?", [src])
        _emit_event(
            conn,
            "collection.merged",
            "collection",
            dst,
            {"merged_from": src, "moved": moved},
        )

    return {"merged_from": src, "merged_to": dst, "moved": moved}


def rename_collection(old: str, new: str) -> dict:
    """Rename a collection, preserving ``created_at``, project and article membership."""
    conn = _get_conn()
    if old == new:
        return {"renamed_from": old, "renamed_to": new, "noop": True}
    src_row = conn.execute(
        "SELECT created_at, project FROM collections WHERE name = ?", [old]
    ).fetchone()
    if not src_row:
        raise ValueError(f"Collection not found: {old}")
    if conn.execute("SELECT 1 FROM collections WHERE name = ?", [new]).fetchone():
        raise ValueError(f"Collection already exists: {new}")

    created_at, project = src_row
    with _txn(conn):
        conn.execute(
            "INSERT INTO collections (name, created_at, project) VALUES (?, ?, ?)",
            [new, created_at, project],
        )
        conn.execute(
            "UPDATE collection_articles SET collection_name = ? WHERE collection_name = ?",
            [new, old],
        )
        conn.execute("DELETE FROM collections WHERE name = ?", [old])
        _emit_event(
            conn,
            "collection.renamed",
            "collection",
            new,
            {"renamed_from": old, "created_at": created_at},
        )
    return {"renamed_from": old, "renamed_to": new, "created_at": created_at}


def add_to_collection(name: str, eids: list[str]) -> dict:
    """Add articles to a collection."""
    conn = _get_conn()
    added = 0
    with _txn(conn):
        created = conn.execute("SELECT name FROM collections WHERE name = ?", [name]).fetchone()
        conn.execute(
            "INSERT OR IGNORE INTO collections (name, created_at) VALUES (?, ?)", [name, _now()]
        )
        if not created:
            _emit_event(conn, "collection.created", "collection", name, {})

        for eid in eids:
            exists = conn.execute("SELECT eid FROM articles WHERE eid = ?", [eid]).fetchone()
            if not exists:
                continue
            already = conn.execute(
                "SELECT 1 FROM collection_articles WHERE collection_name = ? AND eid = ?",
                [name, eid],
            ).fetchone()
            if already:
                continue
            try:
                conn.execute("INSERT INTO collection_articles VALUES (?, ?)", [name, eid])
                added += 1
                _emit_event(
                    conn, "article.added_to_collection", "article", eid, {"collection": name}
                )
            except duckdb.ConstraintException:
                pass
    total = conn.execute(
        "SELECT COUNT(*) FROM collection_articles WHERE collection_name = ?", [name]
    ).fetchone()[0]
    return {"collection": name, "added": added, "total": total}


def remove_from_collection(name: str, eids: list[str]) -> dict:
    """Remove articles from a collection."""
    conn = _get_conn()
    existing = conn.execute("SELECT name FROM collections WHERE name = ?", [name]).fetchone()
    if not existing:
        raise ValueError(f"Collection not found: {name}")
    removed = 0
    with _txn(conn):
        for eid in eids:
            was_in = conn.execute(
                "SELECT 1 FROM collection_articles WHERE collection_name = ? AND eid = ?",
                [name, eid],
            ).fetchone()
            conn.execute(
                "DELETE FROM collection_articles WHERE collection_name = ? AND eid = ?",
                [name, eid],
            )
            removed += 1
            if was_in:
                _emit_event(
                    conn, "article.removed_from_collection", "article", eid, {"collection": name}
                )
    total = conn.execute(
        "SELECT COUNT(*) FROM collection_articles WHERE collection_name = ?", [name]
    ).fetchone()[0]
    return {"collection": name, "removed": removed, "total": total}


# ── Project management ───────────────────────────────────────────────────────
#
# A project groups collections, one level deep. Membership is the
# ``collections.project`` column, so a collection is in at most one project,
# and a project never holds articles directly — its papers are the union of
# its collections'.


def _check_project_name(name) -> str:
    """Reject names that cannot round-trip: empty, or unaddressable in a URL path."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Project name must not be empty")
    if "/" in name or name in (".", ".."):
        raise ValueError(f"Project name may not contain '/' or be '.' or '..': {name!r}")
    return name


def _ensure_project(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    """Create ``name`` if missing, inside the caller's transaction. Returns whether it did."""
    if conn.execute("SELECT 1 FROM projects WHERE name = ?", [name]).fetchone():
        return False
    conn.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)", [name, _now()])
    _emit_event(conn, "project.created", "project", name, {})
    return True


def _collection_name_list(names) -> list[str]:
    """Deduplicated, order-preserving list of names. A bare string is refused
    rather than iterated — ``"ab"`` would otherwise mean collections a and b."""
    if isinstance(names, str) or not isinstance(names, (list, tuple)):
        raise ValueError("collections must be a list of names")
    names = list(dict.fromkeys(n for n in names if n))
    if not names:
        raise ValueError("No collections given")
    return names


def _validate_collection_names(conn: duckdb.DuckDBPyConnection, names: list[str]) -> None:
    unknown = [
        n
        for n in names
        if not conn.execute("SELECT 1 FROM collections WHERE name = ?", [n]).fetchone()
    ]
    if unknown:
        raise ValueError(f"Collection(s) not found: {', '.join(unknown)}")


def list_projects() -> dict:
    """List projects with their member collections and distinct article counts."""
    conn = _get_conn()
    projects = {
        name: {"created": created or "", "collections": []}
        for name, created in conn.execute("SELECT name, created_at FROM projects").fetchall()
    }
    for coll, project in conn.execute(
        "SELECT name, project FROM collections WHERE project IS NOT NULL ORDER BY name"
    ).fetchall():
        if project in projects:
            projects[project]["collections"].append(coll)
    counts = dict(
        conn.execute("""
            SELECT c.project, COUNT(DISTINCT ca.eid)
            FROM collections c
            JOIN collection_articles ca ON c.name = ca.collection_name
            WHERE c.project IS NOT NULL
            GROUP BY c.project
        """).fetchall()
    )
    for name, info in projects.items():
        info["collection_count"] = len(info["collections"])
        info["article_count"] = counts.get(name, 0)
    return {"projects": projects}


def create_project(name: str) -> dict:
    """Create a new empty project."""
    _check_project_name(name)
    conn = _get_conn()
    if conn.execute("SELECT 1 FROM projects WHERE name = ?", [name]).fetchone():
        raise ValueError(f"Project already exists: {name}")
    with _txn(conn):
        _ensure_project(conn, name)
    return {"created": name}


def delete_project(name: str) -> dict:
    """Delete a project. Its collections are kept, ungrouped."""
    conn = _get_conn()
    if not conn.execute("SELECT 1 FROM projects WHERE name = ?", [name]).fetchone():
        raise ValueError(f"Project not found: {name}")
    with _txn(conn):
        released = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM collections WHERE project = ? ORDER BY name", [name]
            ).fetchall()
        ]
        conn.execute("UPDATE collections SET project = NULL WHERE project = ?", [name])
        conn.execute("DELETE FROM projects WHERE name = ?", [name])
        _emit_event(conn, "project.deleted", "project", name, {"released": released})
    return {"deleted": name, "released": released}


def rename_project(old: str, new: str) -> dict:
    """Rename a project, preserving ``created_at`` and its collections."""
    _check_project_name(new)
    conn = _get_conn()
    if old == new:
        return {"renamed_from": old, "renamed_to": new, "noop": True}
    src_row = conn.execute("SELECT created_at FROM projects WHERE name = ?", [old]).fetchone()
    if not src_row:
        raise ValueError(f"Project not found: {old}")
    if conn.execute("SELECT 1 FROM projects WHERE name = ?", [new]).fetchone():
        raise ValueError(f"Project already exists: {new}")
    created_at = src_row[0]
    with _txn(conn):
        conn.execute("INSERT INTO projects (name, created_at) VALUES (?, ?)", [new, created_at])
        conn.execute("UPDATE collections SET project = ? WHERE project = ?", [new, old])
        conn.execute("DELETE FROM projects WHERE name = ?", [old])
        _emit_event(
            conn,
            "project.renamed",
            "project",
            new,
            {"renamed_from": old, "created_at": created_at},
        )
    return {"renamed_from": old, "renamed_to": new, "created_at": created_at}


def assign_collections(project: str, names: list[str]) -> dict:
    """Put collections into ``project``, moving them out of any other project.

    All-or-nothing: every name is validated before anything changes. The
    project is created if missing, as ``add_to_collection`` does for
    collections. Collections already in ``project`` are left alone.
    """
    _check_project_name(project)
    names = _collection_name_list(names)
    conn = _get_conn()
    assigned: list[str] = []
    moved_from: dict[str, str] = {}
    # Validation inside the transaction: raising rolls back, and holding the
    # write lock means a concurrent delete cannot land between check and use.
    with _txn(conn):
        _validate_collection_names(conn, names)
        created = _ensure_project(conn, project)
        for name in names:
            previous = conn.execute(
                "SELECT project FROM collections WHERE name = ?", [name]
            ).fetchone()[0]
            if previous == project:
                continue
            conn.execute("UPDATE collections SET project = ? WHERE name = ?", [project, name])
            assigned.append(name)
            if previous is not None:
                moved_from[name] = previous
            _emit_event(
                conn,
                "collection.project_changed",
                "collection",
                name,
                {"project": project, "previous": previous},
            )
    return {"project": project, "assigned": assigned, "moved_from": moved_from, "created": created}


def unassign_collections(project: str, names: list[str]) -> dict:
    """Take collections out of ``project``. They are kept, ungrouped.

    All-or-nothing: raises before changing anything if any name is not in
    ``project``.
    """
    names = _collection_name_list(names)
    conn = _get_conn()
    with _txn(conn):
        if not conn.execute("SELECT 1 FROM projects WHERE name = ?", [project]).fetchone():
            raise ValueError(f"Project not found: {project}")
        _validate_collection_names(conn, names)
        outside = [
            n
            for n in names
            if conn.execute("SELECT project FROM collections WHERE name = ?", [n]).fetchone()[0]
            != project
        ]
        if outside:
            raise ValueError(f"Not in project {project}: {', '.join(outside)}")
        for name in names:
            conn.execute("UPDATE collections SET project = NULL WHERE name = ?", [name])
            _emit_event(
                conn,
                "collection.project_changed",
                "collection",
                name,
                {"project": None, "previous": project},
            )
    return {"project": project, "unassigned": names}


# ── Stats ─────────────────────────────────────────────────────────────────────


def stats() -> dict:
    """Get database statistics."""
    conn = _get_conn()

    total_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    total_authors = conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    total_collections = conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
    total_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

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
        "total_projects": total_projects,
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

    rows = conn.execute(
        f"""
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
    """,
        params + [limit],
    ).fetchall()

    total = conn.execute(
        f"SELECT COUNT(*) FROM authors{'  WHERE LOWER(name) LIKE ?' if query else ''}", params
    ).fetchone()[0]

    authors = []
    for row in rows:
        (
            auid,
            name,
            affiliations,
            h_index,
            doc_count,
            cited_by,
            orcid,
            notes,
            added_at,
            paper_count,
        ) = row
        affs = json.loads(affiliations) if affiliations else []
        authors.append(
            {
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
            }
        )

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

    (
        auid,
        name,
        affiliations,
        h_index,
        doc_count,
        cited_by,
        citation_count,
        coauthor_count,
        orcid,
        subject_areas_json,
        notes,
        added_at,
        fetched_at,
    ) = row
    affs = json.loads(affiliations) if affiliations else []
    subj_areas = json.loads(subject_areas_json) if subject_areas_json else []

    # Get their articles
    article_rows = conn.execute(
        """
        SELECT a.eid, a.title, a.journal, a.cover_date, a.cited_by, a.doi,
               aa.seq, aa.is_first, aa.is_corresponding
        FROM articles a
        JOIN article_authors aa ON a.eid = aa.eid
        WHERE aa.auid = ?
        ORDER BY a.cover_date DESC
    """,
        [auid],
    ).fetchall()

    articles = []
    for eid, title, journal, cover_date, cited_by, doi, seq, is_first, is_corr in article_rows:
        articles.append(
            {
                "eid": eid,
                "title": title,
                "journal": journal,
                "cover_date": cover_date,
                "cited_by": cited_by,
                "doi": doi,
                "author_position": seq,
                "is_first_author": bool(is_first),
                "is_corresponding": bool(is_corr),
            }
        )

    # Find co-authors (other authors who share articles)
    coauthor_rows = conn.execute(
        """
        SELECT au.auid, au.name, COUNT(*) as shared_papers
        FROM article_authors aa1
        JOIN article_authors aa2 ON aa1.eid = aa2.eid AND aa1.auid != aa2.auid
        JOIN authors au ON aa2.auid = au.auid
        WHERE aa1.auid = ?
        GROUP BY au.auid, au.name
        ORDER BY shared_papers DESC
        LIMIT 20
    """,
        [auid],
    ).fetchall()

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
                subject_areas.append(
                    {
                        "name": area.get("$", ""),
                        "code": area.get("@code", ""),
                        "abbrev": area.get("@abbrev", ""),
                    }
                )

    # Parse current affiliation
    aff_current = profile.get("affiliation-current", {})
    if isinstance(aff_current, dict):
        aff_current = aff_current.get("affiliation", {})
    affiliations = []
    if isinstance(aff_current, dict):
        aff_name = aff_current.get("ip-doc", {}).get("afdispname", "") or aff_current.get(
            "ip-doc", {}
        ).get("preferred-name", {}).get("$", "")
        if aff_name:
            affiliations.append(aff_name)
    elif isinstance(aff_current, list):
        for afc in aff_current:
            aff_name = afc.get("ip-doc", {}).get("afdispname", "") or afc.get("ip-doc", {}).get(
                "preferred-name", {}
            ).get("$", "")
            if aff_name:
                affiliations.append(aff_name)

    # Upsert into DB
    conn = _get_conn()
    existing = conn.execute("SELECT auid FROM authors WHERE auid = ?", [auid]).fetchone()

    with _txn(conn):
        if existing:
            conn.execute(
                """
                UPDATE authors SET
                    name=?, affiliations=?, h_index=?, document_count=?,
                    cited_by_count=?, citation_count=?, coauthor_count=?,
                    orcid=?, subject_areas=?, updated_at=?, fetched_at=?
                WHERE auid=?
            """,
                [
                    name,
                    json.dumps(affiliations),
                    h_index,
                    doc_count,
                    cited_by,
                    citation_count,
                    coauthor_count,
                    orcid,
                    json.dumps(subject_areas),
                    _now(),
                    _now(),
                    auid,
                ],
            )
        else:
            conn.execute(
                """
                INSERT INTO authors (
                    auid, name, affiliations, h_index, document_count,
                    cited_by_count, citation_count, coauthor_count,
                    orcid, subject_areas, notes, added_at, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
                [
                    auid,
                    name,
                    json.dumps(affiliations),
                    h_index,
                    doc_count,
                    cited_by,
                    citation_count,
                    coauthor_count,
                    orcid,
                    json.dumps(subject_areas),
                    "",
                    _now(),
                    _now(),
                ],
            )
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

    rows = conn.execute(
        """
        SELECT au.auid, au.name, au.affiliations, COUNT(*) as shared_papers
        FROM article_authors aa1
        JOIN article_authors aa2 ON aa1.eid = aa2.eid AND aa1.auid != aa2.auid
        JOIN authors au ON aa2.auid = au.auid
        WHERE aa1.auid = ?
        GROUP BY au.auid, au.name, au.affiliations
        ORDER BY shared_papers DESC
    """,
        [auid],
    ).fetchall()

    coauthors = []
    for ca_auid, ca_name, ca_affs, cnt in rows:
        affs = json.loads(ca_affs) if ca_affs else []
        coauthors.append(
            {
                "auid": ca_auid,
                "name": ca_name,
                "affiliations": affs,
                "shared_papers": cnt,
            }
        )

    return {
        "author": {"auid": auid, "name": author_name},
        "coauthors": coauthors,
        "total": len(coauthors),
    }
