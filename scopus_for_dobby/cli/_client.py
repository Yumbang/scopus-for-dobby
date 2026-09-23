"""Backend router for DB access from CLI subcommands.

Subcommands do ``from . import _client as db_mod`` and then call
``db_mod.list_articles(...)`` without caring how the call is fulfilled.
This module picks one of two backends, once per process:

* **in-process** (:mod:`scopus_for_dobby.core.article_db`) — the default.
  Opens DuckDB directly. No subprocess, no HTTP hop, no daemon left
  running afterwards.
* **daemon** (:mod:`scopus_for_dobby.cli._http`) — selected only when a
  daemon is *already* listening, i.e. ``serve`` was run explicitly or the
  macOS GUI launched one. DuckDB allows a single read/write process per
  file, so when the daemon holds the file we must go through it.

Amends ADR-7: the CLI no longer lazy-spawns a daemon on every invocation.
The daemon *server* is a GUI/concurrency feature, shipped in the optional
``[gui]`` extra along with ``fastapi``/``uvicorn``. A CLI-only install cannot
start one — but it can still detect and attach to a daemon someone else
started, because the HTTP client (``httpx``) is a core dependency. That case
is not hypothetical: starting the macOS GUI puts every CLI invocation on that
machine onto the HTTP path. The spawn machinery in ``_daemon.py`` is retained for tests
and for anything that wants to start a daemon programmatically; nothing on
the default CLI path calls it.

Both backends take the same arguments and return the same shapes, so the
router hands the chosen module's attribute straight to the caller.
"""

from __future__ import annotations

from scopus_for_dobby.core.article_db import _normalize_entry  # noqa: F401

from .serve import daemon_endpoint

# The CLI↔core contract. Any name a subcommand reaches for through
# ``db_mod`` must appear here and be implemented by *both* backends —
# otherwise a call would silently work in-process and fail against the
# daemon (or vice versa).
_API = frozenset(
    {
        "list_articles",
        "get_article",
        "lookup_article",
        "add_entries",
        "remove_entries",
        "enrich_articles",
        "record_fulltext_fetch",
        "tag_articles",
        "untag_articles",
        "set_note",
        "list_collections",
        "create_collection",
        "delete_collection",
        "add_to_collection",
        "remove_from_collection",
        "merge_collections",
        "rename_collection",
        "list_projects",
        "create_project",
        "delete_project",
        "rename_project",
        "assign_collections",
        "unassign_collections",
        "list_authors",
        "get_author",
        "set_author_note",
        "find_coauthors",
        "fetch_author_profile",
        "search_articles_fts",
        "search_articles_like",
        "stats",
        "rebuild_fts",
    }
)

# Resolved once per process: ``daemon_endpoint()`` reads two files and may
# probe a TCP port, which is far too expensive to repeat on every call.
_backend = None


def _resolve():
    from . import _http

    # A test factory stands in for a live daemon.
    if _http._client_factory is not None:
        return _http
    if daemon_endpoint():
        return _http
    from scopus_for_dobby.core import article_db

    return article_db


def backend():
    """Return the module fulfilling DB calls for this process."""
    global _backend
    if _backend is None:
        _backend = _resolve()
    return _backend


def backend_name() -> str:
    """``"daemon"`` or ``"in-process"`` — for diagnostics and error messages."""
    return "daemon" if backend().__name__.endswith("._http") else "in-process"


def reset_backend() -> None:
    """Drop the cached choice so the next call re-resolves.

    Used by tests, and by anything that starts or stops a daemon mid-process.
    """
    global _backend
    _backend = None


def __getattr__(name: str):
    if name not in _API:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r} "
            f"(not part of the CLI↔core API surface in _API)"
        )
    return getattr(backend(), name)


def __dir__():
    return sorted(set(globals()) | _API)
