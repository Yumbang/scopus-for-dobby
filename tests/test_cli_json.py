"""Tests for CLI --json output mode + collection merge/rename subcommands (Step 4)."""

import json

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import article_db as db_mod

SAMPLE = {
    "dc:title": "JSON CLI sample",
    "dc:creator": "Tester",
    "prism:publicationName": "J",
    "prism:coverDate": "2025-01-01",
    "prism:doi": "10.0/cli",
    "eid": "2-s2.0-cli-1",
    "dc:identifier": "SCOPUS_ID:cli-1",
    "citedby-count": "3",
    "openaccess": "0",
    "prism:aggregationType": "Journal",
}


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    # Reset shared mutable state between tests.
    state.json_output = False
    state.repl_mode = False
    yield db_file
    db_mod.close_cached_connections()
    state.json_output = False


@pytest.fixture
def runner():
    return CliRunner()


class TestJsonMode:
    def test_db_list_json(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        result = runner.invoke(root_cli, ["--json", "db", "list"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "articles" in data
        assert any(a["eid"] == SAMPLE["eid"] for a in data["articles"])

    def test_db_info_json(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        result = runner.invoke(root_cli, ["--json", "db", "info", SAMPLE["eid"]])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["eid"] == SAMPLE["eid"]

    def test_db_stats_json(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        result = runner.invoke(root_cli, ["--json", "db", "stats"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["total_articles"] == 1

    def test_collection_list_json(self, tmp_db, runner):
        db_mod.create_collection("c1")
        result = runner.invoke(root_cli, ["--json", "collection", "list"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "c1" in data["collections"]

    def test_human_default_unchanged(self, tmp_db, runner):
        db_mod.create_collection("c1")
        result = runner.invoke(root_cli, ["collection", "list"])
        assert result.exit_code == 0, result.output
        # Not JSON-parseable, contains human-readable label.
        assert "c1" in result.output
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)


class TestCollectionMergeRenameCli:
    def test_merge_cli(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        db_mod.create_collection("a")
        db_mod.add_to_collection("a", [SAMPLE["eid"]])
        result = runner.invoke(root_cli, ["--json", "collection", "merge", "a", "b"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["merged_from"] == "a"
        assert data["merged_to"] == "b"
        colls = db_mod.list_collections()["collections"]
        assert "a" not in colls
        assert colls["b"]["article_count"] == 1

    def test_rename_cli(self, tmp_db, runner):
        db_mod.create_collection("orig")
        result = runner.invoke(root_cli, ["--json", "collection", "rename", "orig", "renamed"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["renamed_from"] == "orig"
        assert data["renamed_to"] == "renamed"
        colls = db_mod.list_collections()["collections"]
        assert "orig" not in colls
        assert "renamed" in colls


class TestEidsFromStdin:
    def test_collection_add_via_stdin(self, tmp_db, runner):
        db_mod.add_entries([SAMPLE])
        result = runner.invoke(
            root_cli,
            ["--json", "collection", "add", "c", "--eids-from-stdin"],
            input=f"{SAMPLE['eid']}\n",
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["added"] == 1

    def test_db_tag_via_file(self, tmp_db, runner, tmp_path):
        db_mod.add_entries([SAMPLE])
        eid_file = tmp_path / "eids.txt"
        eid_file.write_text(SAMPLE["eid"] + "\n")
        result = runner.invoke(
            root_cli,
            ["--json", "db", "tag", "--eids-from-file", str(eid_file), "topic"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["tagged"] == 1
