"""HTTP backend — talks to a running daemon over 127.0.0.1.

One of the two backends behind :mod:`scopus_for_dobby.cli._client`. This
one is only selected when a daemon is *already* running (started by
``scopus-for-dobby serve`` or by the macOS GUI); the CLI never spawns one
on its own. See ``_client`` for the selection rule.

Function names and return shapes mirror :mod:`scopus_for_dobby.core.article_db`
exactly, so the router can hand either module to subcommand code.

``httpx`` is a core dependency: the daemon *server* is optional, but any
install may have to talk to a daemon someone else started, so the client
half cannot be. The import stays at call time only to keep it off the
startup path of commands that never reach this backend.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .serve import daemon_endpoint

# Tests install a factory here to bypass a real daemon and route through
# ``fastapi.testclient.TestClient`` instead. Returns a context-manager
# whose ``__enter__`` yields something with ``.get/.post/.request``
# (TestClient and httpx.Client both qualify). When set, it also forces
# the router in ``_client`` to pick this backend.
_client_factory = None  # type: ignore[var-annotated]


class DaemonUnavailableError(RuntimeError):
    """Raised when the daemon backend is selected but cannot be reached."""


def _client():
    if _client_factory is not None:
        return _client_factory()

    import httpx

    base_url = daemon_endpoint()
    if not base_url:  # pragma: no cover — router checks this first
        raise DaemonUnavailableError("No daemon is running.")
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    return httpx.Client(base_url=base_url, timeout=timeout)


def _seg(name: str) -> str:
    """Percent-encode one path segment, so ``?``, ``#`` and ``%`` in a name
    address that name rather than truncating the URL."""
    return quote(name, safe="")


def _check(r) -> None:
    """Raise like the in-process backend would.

    The server turns a core ``ValueError`` into a 400 carrying its message;
    re-raise it as one so the CLI prints "Collection(s) not found: x" rather
    than httpx's "Client error '400 Bad Request' for url ...".
    """
    if r.status_code == 400:
        try:
            msg = r.json().get("error")
        except ValueError:
            msg = None
        if msg:
            raise ValueError(msg)
    r.raise_for_status()


def _get(path: str, **params: Any) -> Any:
    params = {k: v for k, v in params.items() if v is not None}
    with _client() as c:
        r = c.get(path, params=params)
        _check(r)
        return r.json()


def _post(path: str, body: dict | None = None) -> Any:
    with _client() as c:
        r = c.post(path, json=body or {})
        _check(r)
        return r.json()


def _delete(path: str, body: dict | None = None) -> Any:
    with _client() as c:
        r = c.request("DELETE", path, json=body or {})
        _check(r)
        return r.json()


# ── Articles ──────────────────────────────────────────────────────────────────
def list_articles(*, tag=None, collection=None, query=None, sort="added", limit=50, project=None):
    return _get(
        "/articles",
        tag=tag,
        collection=collection,
        query=query,
        sort=sort,
        limit=limit,
        project=project,
    )


def get_article(eid: str):
    return _get(f"/articles/{eid}")


def lookup_article(identifier: str):
    with _client() as c:
        r = c.get("/articles/lookup", params={"identifier": identifier})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


def record_fulltext_fetch(eid: str, roles=None):
    return _post("/articles/fulltext", {"eid": eid, "roles": roles or {}})


def add_entries(entries, *, tags=None, collection=None):
    return _post("/articles", {"entries": entries, "tags": tags, "collection": collection})


def remove_entries(eids):
    return _delete("/articles", {"eids": list(eids)})


def enrich_articles(enrichments):
    return _post("/articles/enrich", {"enrichments": list(enrichments)})


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


def create_collection(name: str, project: str | None = None):
    return _post("/collections", {"name": name, "project": project})


def delete_collection(name: str):
    return _delete(f"/collections/{_seg(name)}")


def add_to_collection(name: str, eids):
    return _post(f"/collections/{_seg(name)}/articles", {"eids": list(eids)})


def remove_from_collection(name: str, eids):
    return _delete(f"/collections/{_seg(name)}/articles", {"eids": list(eids)})


def merge_collections(src: str, dst: str):
    return _post("/collections/merge", {"src": src, "dst": dst})


def rename_collection(old: str, new: str):
    return _post("/collections/rename", {"old": old, "new": new})


# ── Projects ──────────────────────────────────────────────────────────────────
def list_projects():
    return _get("/projects")


def create_project(name: str):
    return _post("/projects", {"name": name})


def delete_project(name: str):
    return _delete(f"/projects/{_seg(name)}")


def rename_project(old: str, new: str):
    return _post("/projects/rename", {"old": old, "new": new})


def assign_collections(project: str, names):
    return _post(f"/projects/{_seg(project)}/collections", {"collections": list(names)})


def unassign_collections(project: str, names):
    return _delete(f"/projects/{_seg(project)}/collections", {"collections": list(names)})


# ── Authors ───────────────────────────────────────────────────────────────────
def list_authors(*, query=None, sort="papers", limit=50):
    return _get("/authors", query=query, sort=sort, limit=limit)


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
