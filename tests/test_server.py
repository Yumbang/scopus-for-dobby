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
    client.post("/articles", json={
        "entries": [
            _entry("E1", title="Attention is all you need", abstract="self-attention"),
            _entry("E2", title="ResNet", abstract="residual learning"),
        ]
    })
    r = client.get("/search/fts?query=attention&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    eids = [a["eid"] for a in body["articles"]]
    assert "E1" in eids
