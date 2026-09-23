"""Tests for the ``project`` CLI group (projects group collections)."""

import json

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.core import session as session_mod

SAMPLE = {
    "dc:title": "Project CLI sample",
    "dc:creator": "Tester",
    "prism:publicationName": "J",
    "prism:coverDate": "2025-01-01",
    "prism:doi": "10.0/proj",
    "eid": "2-s2.0-proj-1",
    "dc:identifier": "SCOPUS_ID:proj-1",
    "citedby-count": "3",
    "openaccess": "0",
    "prism:aggregationType": "Journal",
}


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(session_mod, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(session_mod, "_session", None)
    state.json_output = False
    state.repl_mode = False
    yield db_file
    db_mod.close_cached_connections()
    state.json_output = False


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def colls(tmp_db):
    """Three thesis collections and one unrelated, the first holding one paper."""
    db_mod.add_entries([SAMPLE])
    for name in ("thesis-ch1", "thesis-ch2", "thesis-ch3", "misc"):
        db_mod.create_collection(name)
    db_mod.add_to_collection("thesis-ch1", [SAMPLE["eid"]])
    return tmp_db


def _project_of(name):
    return db_mod.list_collections()["collections"][name]["project"]


def _projects():
    return db_mod.list_projects()["projects"]


class TestProjectAdd:
    def test_add_by_name(self, colls, runner):
        result = runner.invoke(
            root_cli, ["--json", "project", "add", "thesis", "thesis-ch1", "misc"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["assigned"] == ["thesis-ch1", "misc"]
        assert data["created"] is True
        assert _project_of("thesis-ch1") == "thesis"
        assert _project_of("misc") == "thesis"
        assert _project_of("thesis-ch2") is None

    def test_add_by_match(self, colls, runner):
        result = runner.invoke(
            root_cli, ["--json", "project", "add", "thesis", "--match", "thesis-*"]
        )
        assert result.exit_code == 0, result.output
        assert sorted(json.loads(result.output)["assigned"]) == [
            "thesis-ch1",
            "thesis-ch2",
            "thesis-ch3",
        ]
        assert _project_of("misc") is None

    def test_names_and_match_union_deduped(self, colls, runner):
        result = runner.invoke(
            root_cli,
            ["--json", "project", "add", "p", "misc", "thesis-ch1", "-m", "thesis-ch[12]"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["assigned"] == ["misc", "thesis-ch1", "thesis-ch2"]

    def test_match_nothing_errors(self, colls, runner):
        result = runner.invoke(root_cli, ["project", "add", "thesis", "--match", "nope-*"])
        assert result.exit_code != 0
        assert "nope-*" in result.output
        assert "thesis" not in _projects()

    def test_dry_run_changes_nothing(self, colls, runner):
        db_mod.assign_collections("other", ["thesis-ch2"])
        db_mod.assign_collections("thesis", ["thesis-ch3"])
        result = runner.invoke(
            root_cli,
            ["--json", "project", "add", "thesis", "-m", "thesis-*", "ghost", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["project"] == "thesis"
        assert data["would_assign"] == ["thesis-ch1", "thesis-ch2"]
        assert data["would_move_from"] == {"thesis-ch2": "other"}
        assert data["already_in"] == ["thesis-ch3"]
        assert data["unknown"] == ["ghost"]
        assert _project_of("thesis-ch1") is None
        assert _project_of("thesis-ch2") == "other"

    def test_dry_run_human(self, colls, runner):
        result = runner.invoke(
            root_cli, ["project", "add", "thesis", "--match", "thesis-*", "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert "Dry run" in result.output
        assert "would assign: thesis-ch1" in result.output
        assert "thesis" not in _projects()

    def test_unknown_collection_changes_nothing(self, colls, runner):
        result = runner.invoke(root_cli, ["project", "add", "thesis", "thesis-ch1", "ghost"])
        assert result.exit_code == 1
        assert "ghost" in result.output
        assert "thesis" not in _projects()
        assert _project_of("thesis-ch1") is None

    def test_no_collections_is_usage_error(self, colls, runner):
        result = runner.invoke(root_cli, ["project", "add", "thesis"])
        assert result.exit_code != 0
        assert "thesis" not in _projects()

    def test_move_between_projects_says_moved_from(self, colls, runner):
        db_mod.assign_collections("old", ["misc"])
        result = runner.invoke(root_cli, ["project", "add", "new", "misc"])
        assert result.exit_code == 0, result.output
        assert "moved from old" in result.output
        assert "Created project 'new'" in result.output
        assert _project_of("misc") == "new"


class TestProjectList:
    def test_list_json_shape(self, colls, runner):
        db_mod.assign_collections("thesis", ["thesis-ch1", "thesis-ch2"])
        result = runner.invoke(root_cli, ["--json", "project", "list"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        meta = data["projects"]["thesis"]
        assert meta["collections"] == ["thesis-ch1", "thesis-ch2"]
        assert meta["collection_count"] == 2
        assert meta["article_count"] == 1
        assert "created" in meta

    def test_list_human(self, colls, runner):
        db_mod.assign_collections("thesis", ["thesis-ch1", "thesis-ch2"])
        result = runner.invoke(root_cli, ["project", "list"])
        assert result.exit_code == 0, result.output
        assert "thesis" in result.output
        assert "thesis-ch1 — 1 article" in result.output
        assert "Ungrouped: 2 collections" in result.output

    def test_list_empty(self, colls, runner):
        result = runner.invoke(root_cli, ["project", "list"])
        assert result.exit_code == 0, result.output
        assert "No projects yet" in result.output
        assert "Ungrouped: 4 collections" in result.output


class TestProjectLifecycle:
    def test_create(self, colls, runner):
        result = runner.invoke(root_cli, ["--json", "project", "create", "p"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"created": "p"}
        assert _projects()["p"]["collection_count"] == 0

    def test_remove(self, colls, runner):
        db_mod.assign_collections("thesis", ["thesis-ch1", "thesis-ch2", "misc"])
        result = runner.invoke(
            root_cli, ["--json", "project", "remove", "thesis", "misc", "--match", "*ch2"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["unassigned"] == ["misc", "thesis-ch2"]
        assert _project_of("misc") is None
        assert _project_of("thesis-ch2") is None
        assert _project_of("thesis-ch1") == "thesis"
        assert "misc" in db_mod.list_collections()["collections"]

    def test_remove_nothing_is_usage_error(self, colls, runner):
        db_mod.assign_collections("thesis", ["thesis-ch1"])
        result = runner.invoke(root_cli, ["project", "remove", "thesis"])
        assert result.exit_code != 0
        assert _project_of("thesis-ch1") == "thesis"

    def test_rename(self, colls, runner):
        db_mod.assign_collections("old", ["misc"])
        result = runner.invoke(root_cli, ["project", "rename", "old", "new"])
        assert result.exit_code == 0, result.output
        assert "Renamed 'old' → 'new'" in result.output
        assert "old" not in _projects()
        assert _project_of("misc") == "new"

    def test_delete_keeps_collections(self, colls, runner):
        db_mod.assign_collections("thesis", ["thesis-ch1", "thesis-ch2"])
        result = runner.invoke(root_cli, ["project", "delete", "thesis", "--confirm"])
        assert result.exit_code == 0, result.output
        assert "thesis-ch1, thesis-ch2" in result.output
        assert "thesis" not in _projects()
        remaining = db_mod.list_collections()["collections"]
        assert remaining["thesis-ch1"]["project"] is None
        assert remaining["thesis-ch1"]["article_count"] == 1


@pytest.mark.in_process
def test_add_in_process_backend(colls, runner):
    result = runner.invoke(root_cli, ["--json", "project", "add", "thesis", "-m", "thesis-*"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.output)["assigned"]) == 3
    assert _project_of("thesis-ch3") == "thesis"


def test_match_that_misses_is_an_error_even_with_names(colls, runner):
    result = runner.invoke(root_cli, ["project", "add", "thesis", "misc", "-m", "zzz*"])
    assert result.exit_code != 0
    assert "zzz*" in result.output
    assert "thesis" not in _projects()


def test_collection_create_says_when_it_created_the_project(colls, runner):
    result = runner.invoke(root_cli, ["collection", "create", "newc", "-p", "brandnew"])
    assert result.exit_code == 0, result.output
    assert "Created project 'brandnew'" in result.output


def test_blank_project_is_rejected(colls, runner):
    assert runner.invoke(root_cli, ["project", "add", " ", "misc"]).exit_code != 0
    result = runner.invoke(root_cli, ["db", "list", "-p", ""])
    assert result.exit_code != 0
    assert "Project not found" in result.output
