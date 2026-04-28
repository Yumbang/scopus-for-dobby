"""HTTP-client facade mirroring :mod:`scopus_for_dobby.core.article_db`.

ADR-7 — every CLI subcommand routes through here. The function names and
return shapes match ``core.article_db`` so subcommand code can simply
swap its import (``from .._client import db_mod``) without changing
call sites. ``ensure_daemon()`` is invoked lazily on first call.

``_normalize_entry`` is re-exported from ``core.article_db`` directly:
it is a pure helper with no DB access and is used by ``cli/search.py``
to shape entries before POSTing.
"""

from __future__ import annotations

from typing import Any

import httpx

from scopus_for_dobby.core.article_db import _normalize_entry  # noqa: F401

from ._daemon import ensure_daemon

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

# Tests install a factory here to bypass the lazy-spawn daemon and route
# through ``fastapi.testclient.TestClient`` instead. Returns a
# context-manager whose ``__enter__`` yields something with
# ``.get/.post/.request`` (TestClient or httpx.Client both qualify).
_client_factory = None  # type: ignore[var-annotated]


def _client():
    if _client_factory is not None:
        return _client_factory()
    base_url = ensure_daemon()
    return httpx.Client(base_url=base_url, timeout=_TIMEOUT)


def _get(path: str, **params: Any) -> Any:
    params = {k: v for k, v in params.items() if v is not None}
    with _client() as c:
        r = c.get(path, params=params)
        r.raise_for_status()
        return r.json()


def _post(path: str, body: dict | None = None) -> Any:
    with _client() as c:
        r = c.post(path, json=body or {})
        r.raise_for_status()
        return r.json()


def _delete(path: str, body: dict | None = None) -> Any:
    with _client() as c:
        r = c.request("DELETE", path, json=body or {})
        r.raise_for_status()
        return r.json()


# ── Articles ──────────────────────────────────────────────────────────────────
def list_articles(*, tag=None, collection=None, query=None, sort="added", limit=50):
    return _get("/articles", tag=tag, collection=collection, query=query,
                sort=sort, limit=limit)


def get_article(eid: str):
    return _get(f"/articles/{eid}")


def add_entries(entries, *, tags=None, collection=None):
    return _post("/articles", {"entries": entries, "tags": tags,
                               "collection": collection})


def remove_entries(eids):
    return _delete("/articles", {"eids": list(eids)})


# ── Tags & notes ──────────────────────────────────────────────────────────────
def tag_articles(eids, tags):
    return _post("/articles/tag", {"eids": list(eids), "tags": list(tags)})


def untag_articles(eids, tags):
    return _post("/articles/untag", {"eids": list(eids), "tags": list(tags)})


def set_note(eid: str, note: str):
    return _post(f"/articles/{eid}/note", {"note": note})


# ── Collections ───────────────────────────────────────────────────────────────
def list_collections():
    return _get("/collections")


def create_collection(name: str):
    return _post("/collections", {"name": name})


def delete_collection(name: str):
    return _delete(f"/collections/{name}")


def add_to_collection(name: str, eids):
    return _post(f"/collections/{name}/articles", {"eids": list(eids)})


def remove_from_collection(name: str, eids):
    return _delete(f"/collections/{name}/articles", {"eids": list(eids)})


def merge_collections(src: str, dst: str):
    return _post("/collections/merge", {"src": src, "dst": dst})


def rename_collection(old: str, new: str):
    return _post("/collections/rename", {"old": old, "new": new})


# ── Authors ───────────────────────────────────────────────────────────────────
def list_authors(*, sort="citation", limit=50):
    return _get("/authors", sort=sort, limit=limit)


def get_author(auid: str):
    return _get(f"/authors/{auid}")


def set_author_note(auid: str, note: str):
    return _post(f"/authors/{auid}/note", {"note": note})


def find_coauthors(auid: str):
    return _get(f"/authors/{auid}/coauthors")


def fetch_author_profile(auid: str):
    return _post(f"/authors/{auid}/fetch")


# ── Search / stats ────────────────────────────────────────────────────────────
def search_articles_fts(query: str, *, limit: int = 50):
    return _get("/search/fts", query=query, limit=limit)


def search_articles_like(query: str, *, limit: int = 50):
    return _get("/search/like", query=query, limit=limit)


def stats():
    return _get("/stats")


def rebuild_fts():
    return _post("/fts/rebuild")
