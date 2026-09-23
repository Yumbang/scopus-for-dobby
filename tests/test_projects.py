"""Projects: one level above collections (schema v4)."""

import json

import pytest

from scopus_for_dobby.core import article_db as db_mod


def _entry(n: int) -> dict:
    return {
        "dc:title": f"Paper {n}",
        "dc:creator": "Tester A.",
        "prism:publicationName": "Journal of Tests",
        "prism:coverDate": "2025-01-01",
        "eid": f"2-s2.0-proj-{n}",
        "dc:identifier": f"SCOPUS_ID:proj-{n}",
        "citedby-count": "0",
        "openaccess": "0",
        "prism:aggregationType": "Journal",
    }


def _eid(n: int) -> str:
    return f"2-s2.0-proj-{n}"


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield db_file
    db_mod.close_cached_connections()


@pytest.fixture
def library(tmp_db):
    """Papers 1-4; r1-a holds 1,2; r1-b holds 2,3; other holds 4."""
    db_mod.add_entries([_entry(n) for n in range(1, 5)])
    db_mod.add_to_collection("r1-a", [_eid(1), _eid(2)])
    db_mod.add_to_collection("r1-b", [_eid(2), _eid(3)])
    db_mod.add_to_collection("other", [_eid(4)])
    return tmp_db


def _events(kind: str) -> list[dict]:
    rows = (
        db_mod._get_conn()
        .execute("SELECT entity_id, payload FROM events WHERE kind = ? ORDER BY id", [kind])
        .fetchall()
    )
    return [{"entity_id": e, "payload": json.loads(p) if p else {}} for e, p in rows]


def _project_of(name: str):
    return db_mod.list_collections()["collections"][name]["project"]


class TestCrud:
    def test_create_and_list(self, tmp_db):
        assert db_mod.create_project("r1") == {"created": "r1"}
        info = db_mod.list_projects()["projects"]["r1"]
        assert info["collections"] == []
        assert info["collection_count"] == 0
        assert info["article_count"] == 0
        assert info["created"]

    def test_create_existing_raises(self, tmp_db):
        db_mod.create_project("r1")
        with pytest.raises(ValueError, match="already exists"):
            db_mod.create_project("r1")

    def test_rename_keeps_created_and_members(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        created = db_mod.list_projects()["projects"]["r1"]["created"]
        result = db_mod.rename_project("r1", "review-1")
        assert result["created_at"] == created
        projects = db_mod.list_projects()["projects"]
        assert "r1" not in projects
        assert projects["review-1"]["collections"] == ["r1-a"]
        assert projects["review-1"]["created"] == created
        assert _project_of("r1-a") == "review-1"

    def test_rename_noop_and_errors(self, tmp_db):
        db_mod.create_project("a")
        db_mod.create_project("b")
        assert db_mod.rename_project("a", "a")["noop"] is True
        with pytest.raises(ValueError, match="already exists"):
            db_mod.rename_project("a", "b")
        with pytest.raises(ValueError, match="not found"):
            db_mod.rename_project("missing", "c")

    def test_delete_keeps_collections(self, library):
        db_mod.assign_collections("r1", ["r1-a", "r1-b"])
        result = db_mod.delete_project("r1")
        assert result == {"deleted": "r1", "released": ["r1-a", "r1-b"]}
        colls = db_mod.list_collections()["collections"]
        assert colls["r1-a"]["project"] is None
        assert colls["r1-a"]["article_count"] == 2
        assert db_mod.list_projects()["projects"] == {}

    def test_delete_missing_raises(self, tmp_db):
        with pytest.raises(ValueError, match="not found"):
            db_mod.delete_project("nope")


class TestAssign:
    def test_assign_creates_project(self, library):
        result = db_mod.assign_collections("r1", ["r1-a", "r1-b"])
        assert result == {
            "project": "r1",
            "assigned": ["r1-a", "r1-b"],
            "moved_from": {},
            "created": True,
        }
        assert db_mod.list_projects()["projects"]["r1"]["collections"] == ["r1-a", "r1-b"]

    def test_unknown_name_changes_nothing(self, library):
        with pytest.raises(ValueError, match="nope"):
            db_mod.assign_collections("r1", ["r1-a", "nope"])
        assert _project_of("r1-a") is None
        # Not even the project is created.
        assert db_mod.list_projects()["projects"] == {}

    def test_moves_between_projects(self, library):
        db_mod.assign_collections("r1", ["r1-a", "r1-b"])
        result = db_mod.assign_collections("r2", ["r1-b"])
        assert result["moved_from"] == {"r1-b": "r1"}
        projects = db_mod.list_projects()["projects"]
        assert projects["r1"]["collections"] == ["r1-a"]
        assert projects["r2"]["collections"] == ["r1-b"]

    def test_already_member_is_not_reassigned(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        result = db_mod.assign_collections("r1", ["r1-a", "r1-b"])
        assert result["assigned"] == ["r1-b"]
        assert result["created"] is False

    def test_empty_names_raises(self, library):
        with pytest.raises(ValueError):
            db_mod.assign_collections("r1", [])


class TestUnassign:
    def test_unassign(self, library):
        db_mod.assign_collections("r1", ["r1-a", "r1-b"])
        assert db_mod.unassign_collections("r1", ["r1-a"]) == {
            "project": "r1",
            "unassigned": ["r1-a"],
        }
        assert _project_of("r1-a") is None
        assert _project_of("r1-b") == "r1"

    def test_not_in_project_changes_nothing(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        with pytest.raises(ValueError, match="other"):
            db_mod.unassign_collections("r1", ["r1-a", "other"])
        assert _project_of("r1-a") == "r1"

    def test_unknown_project_raises(self, library):
        with pytest.raises(ValueError, match="not found"):
            db_mod.unassign_collections("nope", ["r1-a"])


class TestCollectionOpsKeepProject:
    def test_rename_collection_keeps_project(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        db_mod.rename_collection("r1-a", "r1-renamed")
        assert _project_of("r1-renamed") == "r1"
        assert db_mod.list_projects()["projects"]["r1"]["collections"] == ["r1-renamed"]

    def test_merge_into_existing_keeps_destination_project(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        db_mod.assign_collections("r2", ["r1-b"])
        db_mod.merge_collections("r1-a", "r1-b")
        assert _project_of("r1-b") == "r2"

    def test_merge_into_new_inherits_source_project(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        db_mod.merge_collections("r1-a", "fresh")
        assert _project_of("fresh") == "r1"

    def test_create_collection_into_project(self, tmp_db):
        result = db_mod.create_collection("c", project="p")
        assert result == {"created": "c", "project": "p", "project_created": True}
        assert _project_of("c") == "p"
        assert "p" in db_mod.list_projects()["projects"]


class TestSelector:
    def test_union_is_deduplicated(self, library):
        db_mod.assign_collections("r1", ["r1-a", "r1-b"])
        result = db_mod.list_articles(project="r1", limit=100)
        assert result["total_matching"] == 3
        assert sorted(a["eid"] for a in result["articles"]) == [_eid(1), _eid(2), _eid(3)]
        assert db_mod.list_projects()["projects"]["r1"]["article_count"] == 3

    def test_ands_with_query(self, library):
        db_mod.assign_collections("r1", ["r1-a", "r1-b"])
        result = db_mod.list_articles(project="r1", query="Paper 3")
        assert [a["eid"] for a in result["articles"]] == [_eid(3)]

    def test_project_and_collection_raises(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        with pytest.raises(ValueError, match="not both"):
            db_mod.list_articles(project="r1", collection="r1-a")

    def test_unknown_project_raises(self, library):
        with pytest.raises(ValueError, match="Project not found"):
            db_mod.list_articles(project="typo")

    def test_empty_project_selects_nothing(self, library):
        db_mod.create_project("empty")
        assert db_mod.list_articles(project="empty")["total_matching"] == 0

    def test_get_article_lists_projects(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        db_mod.assign_collections("r2", ["r1-b"])
        assert db_mod.get_article(_eid(2))["projects"] == ["r1", "r2"]
        assert db_mod.get_article(_eid(4))["projects"] == []

    def test_stats_counts_projects(self, library):
        db_mod.create_project("a")
        db_mod.create_project("b")
        assert db_mod.stats()["total_projects"] == 2


class TestEvents:
    def test_lifecycle_events(self, library):
        db_mod.assign_collections("r1", ["r1-a"])
        db_mod.assign_collections("r2", ["r1-a"])
        db_mod.unassign_collections("r2", ["r1-a"])
        db_mod.rename_project("r1", "r1x")
        db_mod.delete_project("r1x")

        assert [e["entity_id"] for e in _events("project.created")] == ["r1", "r2"]
        changed = _events("collection.project_changed")
        assert [e["payload"] for e in changed] == [
            {"project": "r1", "previous": None},
            {"project": "r2", "previous": "r1"},
            {"project": None, "previous": "r2"},
        ]
        assert all(e["entity_id"] == "r1-a" for e in changed)
        renamed = _events("project.renamed")
        assert renamed[0]["entity_id"] == "r1x"
        assert renamed[0]["payload"]["renamed_from"] == "r1"
        assert [e["entity_id"] for e in _events("project.deleted")] == ["r1x"]

    def test_failed_assign_emits_nothing(self, library):
        with pytest.raises(ValueError):
            db_mod.assign_collections("r1", ["nope"])
        assert _events("project.created") == []
        assert _events("collection.project_changed") == []


class TestNames:
    @pytest.mark.parametrize("bad", ["", "  ", "a/b", ".", ".."])
    def test_unaddressable_names_rejected(self, library, bad):
        with pytest.raises(ValueError):
            db_mod.create_project(bad)
        with pytest.raises(ValueError):
            db_mod.assign_collections(bad, ["r1-a"])
        assert _project_of("r1-a") is None

    def test_rename_to_bad_name_rejected(self, tmp_db):
        db_mod.create_project("ok")
        with pytest.raises(ValueError):
            db_mod.rename_project("ok", "")

    def test_empty_project_filter_is_not_no_filter(self, library):
        with pytest.raises(ValueError, match="Project not found"):
            db_mod.list_articles(project="")


class TestNewerSchemaRefused:
    def test_refuses_database_from_newer_install(self, tmp_db):
        db_mod._get_conn().execute(
            "UPDATE schema_meta SET version = ?", [db_mod.SCHEMA_VERSION + 1]
        )
        db_mod.close_cached_connections()
        with pytest.raises(RuntimeError, match="newer scopus-for-dobby"):
            db_mod._get_conn()


def test_bare_string_is_not_split_into_names(library):
    db_mod.create_collection("a")
    with pytest.raises(ValueError, match="list"):
        db_mod.assign_collections("r1", "ab")
    assert _project_of("a") is None
