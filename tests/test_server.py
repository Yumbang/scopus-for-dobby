"""HTTP daemon tests using FastAPI's TestClient (no real network)."""

from __future__ import annotations

import pytest

from scopus_for_dobby.core import article_db as adb


@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    db = tmp_path / "articles.duckdb"
    monkeypatch.setattr(adb, "DB_PATH", db)
    adb.close_cached_connections()

    from scopus_for_dobby.server import build_app

    with TestClient(build_app()) as c:
        yield c
    adb.close_cached_connections()


def _entry(eid: str, title: str = "Sample paper", abstract: str = "About transformers.") -> dict:
    return {
        "eid": eid,
        "title": title,
        "first_author": "Doe, J.",
        "all_authors": [{"auid": "A1", "name": "Doe, J."}],
        "abstract": abstract,
        "keywords": "transformer",
    }


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "fts_available" in body


def test_articles_crud_roundtrip(client):
    r = client.post("/articles", json={"entries": [_entry("E1"), _entry("E2")]})
    assert r.status_code == 200
    assert r.json()["added"] == 2

    r = client.get("/articles")
    assert r.status_code == 200
    assert r.json()["total_in_db"] == 2

    r = client.get("/articles/E1")
    assert r.status_code == 200
    assert r.json()["eid"] == "E1"

    r = client.get("/articles/MISSING")
    assert r.status_code == 404

    r = client.request("DELETE", "/articles", json={"eids": ["E1"]})
    assert r.status_code == 200
    assert r.json()["removed"] == 1


def test_collections(client):
    client.post("/articles", json={"entries": [_entry("E1"), _entry("E2")]})
    client.post("/collections", json={"name": "alpha"})
    client.post("/collections/alpha/articles", json={"eids": ["E1", "E2"]})
    client.post("/collections", json={"name": "beta"})
    client.post("/collections/beta/articles", json={"eids": ["E2"]})

    r = client.post("/collections/merge", json={"src": "alpha", "dst": "beta"})
    assert r.status_code == 200
    body = r.json()
    assert body["merged_from"] == "alpha"
    assert body["merged_to"] == "beta"

    r = client.get("/collections")
    names = list(r.json()["collections"].keys())
    assert "alpha" not in names
    assert "beta" in names


def test_projects(client):
    client.post("/articles", json={"entries": [_entry("E1"), _entry("E2")]})
    client.post("/collections/alpha/articles", json={"eids": ["E1", "E2"]})
    client.post("/collections/beta/articles", json={"eids": ["E2"]})

    r = client.post("/projects", json={"name": "p1"})
    assert r.json() == {"created": "p1"}
    assert client.post("/projects", json={"name": "p1"}).status_code == 400

    r = client.post("/projects/p1/collections", json={"collections": ["alpha", "beta"]})
    assert r.status_code == 200
    assert r.json()["assigned"] == ["alpha", "beta"]
    r = client.post("/projects/p1/collections", json={"collections": ["missing"]})
    assert r.status_code == 400
    assert "missing" in r.json()["error"]

    p1 = client.get("/projects").json()["projects"]["p1"]
    assert p1["collections"] == ["alpha", "beta"]
    assert p1["article_count"] == 2
    assert client.get("/collections").json()["collections"]["alpha"]["project"] == "p1"

    r = client.get("/articles", params={"project": "p1"})
    assert r.json()["total_matching"] == 2
    assert client.get("/articles", params={"project": "nope"}).status_code == 400
    r = client.get("/articles", params={"project": "p1", "collection": "alpha"})
    assert r.status_code == 400

    r = client.request("DELETE", "/projects/p1/collections", json={"collections": ["beta"]})
    assert r.json() == {"project": "p1", "unassigned": ["beta"]}

    r = client.post("/projects/rename", json={"old": "p1", "new": "p2"})
    assert r.json()["renamed_to"] == "p2"

    r = client.delete("/projects/p2")
    assert r.json() == {"deleted": "p2", "released": ["alpha"]}
    assert client.get("/projects").json() == {"projects": {}}
    assert client.post("/collections", json={"name": "c", "project": "p3"}).status_code == 200
    assert client.get("/projects").json()["projects"]["p3"]["collections"] == ["c"]


def test_project_names_with_url_metacharacters(client, monkeypatch):
    """Over the daemon, a name is one path segment — ``?``/``#``/``%`` must not
    truncate it and address a different project."""
    from scopus_for_dobby.cli import _http

    monkeypatch.setattr(_http, "_client_factory", lambda: client)
    # TestClient's context manager is already open; hand it back as-is.
    monkeypatch.setattr(type(client), "__exit__", lambda *a: None, raising=False)
    client.post("/collections", json={"name": "c"})
    for name in ("q", "q?x", "h#1", "50%"):
        client.post("/projects", json={"name": name})
    assert _http.assign_collections("q?x", ["c"])["project"] == "q?x"
    assert _http.delete_project("h#1")["deleted"] == "h#1"
    assert _http.delete_project("50%")["deleted"] == "50%"
    assert set(client.get("/projects").json()["projects"]) == {"q", "q?x"}


def test_tag_and_note(client):
    client.post("/articles", json={"entries": [_entry("E1")]})
    r = client.post("/articles/tag", json={"eids": ["E1"], "tags": ["ml"]})
    assert r.json()["tagged"] == 1

    r = client.post("/articles/E1/note", json={"note": "interesting"})
    assert r.json()["note"] == "interesting"

    r = client.get("/articles/E1")
    assert "ml" in r.json()["_tags"]
    assert r.json()["_notes"] == "interesting"


def test_events_endpoint(client):
    client.post("/articles", json={"entries": [_entry("E1")]})
    client.post("/articles/tag", json={"eids": ["E1"], "tags": ["ml"]})
    r = client.get("/events?since=0")
    assert r.status_code == 200
    body = r.json()
    kinds = [e["kind"] for e in body["events"]]
    assert "article.added" in kinds
    assert "article.tagged" in kinds
    assert body["max_id"] >= 2

    # Cursor advance
    r2 = client.get(f"/events?since={body['max_id']}")
    assert r2.json()["events"] == []


def test_search_fts_falls_back_to_like(client):
    client.post(
        "/articles",
        json={
            "entries": [
                _entry("E1", title="Attention is all you need", abstract="self-attention"),
                _entry("E2", title="ResNet", abstract="residual learning"),
            ]
        },
    )
    r = client.get("/search/fts?query=attention&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    eids = [a["eid"] for a in body["articles"]]
    assert "E1" in eids


def test_lookup_and_fulltext_stamp(client):
    client.post("/articles", json={"entries": [_entry("2-s2.0-lookup-1")]})
    r = client.get("/articles/lookup", params={"identifier": "2-s2.0-lookup-1"})
    assert r.status_code == 200
    assert r.json()["eid"] == "2-s2.0-lookup-1"

    r = client.get("/articles/lookup", params={"identifier": "missing"})
    assert r.status_code == 404

    r = client.post(
        "/articles/fulltext",
        json={"eid": "2-s2.0-lookup-1", "roles": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stamped"] is True
    article = client.get("/articles/2-s2.0-lookup-1").json()
    assert article["fulltext_fetched_at"]


def test_article_detail_carries_collection_membership(client):
    """The detail route is where the GUI reads an article's collections.

    Adding the key to ``get_article`` rather than to a new route means both
    backends carry it by construction — there is no second implementation to
    drift.
    """
    client.post("/articles", json={"entries": [_entry("2-s2.0-mem-1")]})
    client.post("/collections", json={"name": "thesis"})
    client.post("/collections/thesis/articles", json={"eids": ["2-s2.0-mem-1"]})

    article = client.get("/articles/2-s2.0-mem-1").json()
    assert article["collections"] == ["thesis"]


def test_article_not_in_a_collection_reports_empty_membership(client):
    client.post("/articles", json={"entries": [_entry("2-s2.0-mem-2")]})
    assert client.get("/articles/2-s2.0-mem-2").json()["collections"] == []


def test_health_reports_the_daemon_version(client):
    """The GUI and the CLI are installed separately and drift apart silently.

    A version on /health is what lets the app notice it is older than the
    daemon it is driving.
    """
    from scopus_for_dobby import __version__

    body = client.get("/health").json()
    assert body["version"] == __version__
    assert body["status"] == "ok"
