"""Tests for the events table + per-mutation event emission (Step 2)."""

import json

import pytest

from scopus_for_dobby.core import article_db as db_mod

SAMPLE = {
    "dc:title": "Sample paper for events",
    "dc:creator": "Tester A.",
    "prism:publicationName": "Journal of Tests",
    "prism:coverDate": "2025-01-01",
    "prism:doi": "10.0/sample",
    "eid": "2-s2.0-events-1",
    "dc:identifier": "SCOPUS_ID:events-1",
    "citedby-count": "0",
    "openaccess": "0",
    "prism:aggregationType": "Journal",
    "author": [{"authname": "Tester A.", "authid": "auid-1"}],
}

SAMPLE2 = {**SAMPLE, "eid": "2-s2.0-events-2",
           "dc:identifier": "SCOPUS_ID:events-2",
           "dc:title": "Second paper"}


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield db_file
    db_mod.close_cached_connections()


def _events(kind: str | None = None) -> list[dict]:
    conn = db_mod._get_conn()
    sql = "SELECT id, kind, entity_type, entity_id, payload FROM events"
    params: list = []
    if kind:
        sql += " WHERE kind = ?"
        params.append(kind)
    sql += " ORDER BY id"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for _id, k, et, ei, payload in rows:
        out.append({
            "id": _id, "kind": k, "entity_type": et, "entity_id": ei,
            "payload": json.loads(payload) if payload else {},
        })
    return out


class TestEventsEmission:
    def test_events_table_exists(self, tmp_db):
        conn = db_mod._get_conn()
        names = {row[0] for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()}
        assert "events" in names

    def test_add_entries_emits_article_added(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        evs = _events("article.added")
        assert len(evs) == 1
        assert evs[0]["entity_id"] == SAMPLE["eid"]

    def test_add_existing_emits_article_updated(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.add_entries([SAMPLE])
        assert len(_events("article.added")) == 1
        assert len(_events("article.updated")) == 1

    def test_add_with_collection_emits_collection_created(self, tmp_db):
        db_mod.add_entries([SAMPLE], collection="bin")
        assert len(_events("collection.created")) == 1
        assert len(_events("article.added_to_collection")) == 1

    def test_remove_emits_article_removed(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.remove_entries([SAMPLE["eid"]])
        evs = _events("article.removed")
        assert len(evs) == 1
        assert evs[0]["entity_id"] == SAMPLE["eid"]

    def test_tag_untag_emit_events(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.tag_articles([SAMPLE["eid"]], ["x"])
        db_mod.untag_articles([SAMPLE["eid"]], ["x"])
        assert len(_events("article.tagged")) == 1
        assert len(_events("article.untagged")) == 1

    def test_set_note_emits_event(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.set_note(SAMPLE["eid"], "hello")
        assert len(_events("article.note_set")) == 1

    def test_collection_lifecycle_events(self, tmp_db):
        db_mod.create_collection("c")
        db_mod.add_entries([SAMPLE])
        db_mod.add_to_collection("c", [SAMPLE["eid"]])
        db_mod.remove_from_collection("c", [SAMPLE["eid"]])
        db_mod.delete_collection("c")
        assert len(_events("collection.created")) == 1
        assert len(_events("article.added_to_collection")) == 1
        assert len(_events("article.removed_from_collection")) == 1
        assert len(_events("collection.deleted")) == 1

    def test_set_author_note_emits_event(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.set_author_note("auid-1", "interesting")
        assert len(_events("author.note_set")) == 1

    def test_event_ids_are_monotonic(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.add_entries([SAMPLE2])
        ids = [e["id"] for e in _events()]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)


class TestEventTransactionAtomicity:
    def test_rollback_leaves_no_orphan_event(self, tmp_db):
        """If a mutation raises mid-transaction, neither the row nor the event persists."""
        db_mod.add_entries([SAMPLE])
        baseline = len(_events())

        conn = db_mod._get_conn()

        class Boom(RuntimeError):
            pass

        with pytest.raises(Boom), db_mod._txn(conn):
            conn.execute(
                "UPDATE articles SET notes = ? WHERE eid = ?",
                ["should-rollback", SAMPLE["eid"]],
            )
            db_mod._emit_event(conn, "article.note_set", "article",
                               SAMPLE["eid"], {})
            raise Boom("simulated failure after emit")

        assert len(_events()) == baseline, "no orphaned event row"
        article = db_mod.get_article(SAMPLE["eid"])
        assert article["_notes"] != "should-rollback", "no orphaned mutation"


class TestMergeCollections:
    def test_merge_union_no_dup(self, tmp_db):
        db_mod.add_entries([SAMPLE, SAMPLE2])
        db_mod.create_collection("a")
        db_mod.create_collection("b")
        db_mod.add_to_collection("a", [SAMPLE["eid"], SAMPLE2["eid"]])
        db_mod.add_to_collection("b", [SAMPLE["eid"]])  # overlap

        result = db_mod.merge_collections("a", "b")
        assert result["merged_from"] == "a"
        assert result["merged_to"] == "b"
        # Only SAMPLE2 was new to b; SAMPLE was already in b.
        assert result["moved"] == 1

        colls = db_mod.list_collections()["collections"]
        assert "a" not in colls, "src collection deleted"
        assert colls["b"]["article_count"] == 2, "set union, no dup"
        assert len(_events("collection.merged")) == 1

    def test_merge_into_missing_dst_autocreates(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.create_collection("a")
        db_mod.add_to_collection("a", [SAMPLE["eid"]])
        db_mod.merge_collections("a", "new-target")

        colls = db_mod.list_collections()["collections"]
        assert "new-target" in colls
        assert colls["new-target"]["article_count"] == 1

    def test_merge_same_src_dst_is_noop(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.create_collection("a")
        db_mod.add_to_collection("a", [SAMPLE["eid"]])
        result = db_mod.merge_collections("a", "a")
        assert result.get("noop") is True
        assert "a" in db_mod.list_collections()["collections"]

    def test_merge_unknown_src_raises(self, tmp_db):
        with pytest.raises(ValueError, match="Source collection"):
            db_mod.merge_collections("missing", "anything")


class TestRenameCollection:
    def test_rename_preserves_created_at_and_articles(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.create_collection("orig")
        db_mod.add_to_collection("orig", [SAMPLE["eid"]])
        before = db_mod.list_collections()["collections"]["orig"]["created"]

        result = db_mod.rename_collection("orig", "renamed")
        assert result["renamed_from"] == "orig"
        assert result["renamed_to"] == "renamed"
        assert result["created_at"] == before

        colls = db_mod.list_collections()["collections"]
        assert "orig" not in colls
        assert colls["renamed"]["created"] == before
        assert colls["renamed"]["article_count"] == 1
        assert len(_events("collection.renamed")) == 1

    def test_rename_to_existing_raises(self, tmp_db):
        db_mod.create_collection("a")
        db_mod.create_collection("b")
        with pytest.raises(ValueError, match="already exists"):
            db_mod.rename_collection("a", "b")

    def test_rename_unknown_raises(self, tmp_db):
        with pytest.raises(ValueError, match="not found"):
            db_mod.rename_collection("ghost", "anywhere")
