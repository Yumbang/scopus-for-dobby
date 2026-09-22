"""Tests for CLI --json output mode + collection merge/rename subcommands (Step 4)."""

import json

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.core import session as session_mod

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

SAMPLE_2 = {
    **SAMPLE,
    "dc:title": "JSON CLI sample 2",
    "prism:doi": "10.0/cli-2",
    "eid": "2-s2.0-cli-2",
    "dc:identifier": "SCOPUS_ID:cli-2",
}


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    # Export reads the working collection from the session. Keep that off the
    # real ~/.scopus-for-dobby/session, and drop any Session cached earlier.
    monkeypatch.setattr(session_mod, "SESSION_DIR", tmp_path / "session")
    monkeypatch.setattr(session_mod, "_session", None)
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


class TestExportJson:
    def test_json_success_and_counts(self, tmp_db, runner, tmp_path):
        db_mod.add_entries([SAMPLE])
        out = tmp_path / "refs.bib"
        result = runner.invoke(root_cli, ["--json", "export", "--format", "bibtex", "-o", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["exported"] == 1
        assert data["format"] == "bibtex"
        assert data["output"] == str(out)
        assert data["total_matching"] == 1
        assert data["total_in_db"] == 1
        assert "tier" not in data
        assert "truncated" not in data
        assert out.read_text(encoding="utf-8").count("@") == 1

    def test_json_xlsx_includes_tier(self, tmp_db, runner, tmp_path):
        db_mod.add_entries([SAMPLE])
        out = tmp_path / "papers.xlsx"
        result = runner.invoke(root_cli, ["--json", "export", "--format", "xlsx", "-o", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["format"] == "xlsx"
        assert data["tier"] in {"free-tier", "institutional"}
        assert out.exists()

    def test_json_empty_library(self, tmp_db, runner, tmp_path):
        out = tmp_path / "empty.ris"
        result = runner.invoke(root_cli, ["--json", "export", "--format", "ris", "-o", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {
            "exported": 0,
            "format": "ris",
            "output": None,
            "reason": "no articles",
        }
        assert not out.exists()

    def test_json_no_search_results(self, tmp_db, runner, tmp_path):
        result = runner.invoke(
            root_cli,
            ["--json", "export", "--from-last-search", "--format", "bibtex", "-o", "x.bib"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["exported"] == 0
        assert data["reason"] == "no search results"

    def test_json_hides_working_collection_note(self, tmp_db, runner, tmp_path):
        db_mod.add_entries([SAMPLE])
        db_mod.create_collection("thesis")
        db_mod.add_to_collection("thesis", [SAMPLE["eid"]])
        session_mod.get_session().working_collection = "thesis"
        out = tmp_path / "refs.bib"
        result = runner.invoke(root_cli, ["--json", "export", "--format", "bibtex", "-o", str(out)])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["exported"] == 1
        assert "Using working collection" not in result.output

    def test_human_success_stays_human(self, tmp_db, runner, tmp_path):
        db_mod.add_entries([SAMPLE])
        out = tmp_path / "refs.bib"
        result = runner.invoke(root_cli, ["export", "--format", "bibtex", "-o", str(out)])
        assert result.exit_code == 0, result.output
        assert f"Exported 1 articles to {out}" in result.output
        assert "of 2 matching" not in result.output
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)

    def test_truncation_is_disclosed(self, tmp_db, runner, tmp_path, monkeypatch):
        monkeypatch.setattr("scopus_for_dobby.cli.export._ALL", 1)
        db_mod.add_entries([SAMPLE, SAMPLE_2])
        out = tmp_path / "refs.bib"
        human = runner.invoke(root_cli, ["export", "--format", "bibtex", "-o", str(out)])
        assert human.exit_code == 0, human.output
        assert "Exported 1 of 2 matching (2 total in DB)" in human.output
        assert out.read_text(encoding="utf-8").count("@") == 1

        out_json = tmp_path / "refs-json.bib"
        result = runner.invoke(
            root_cli, ["--json", "export", "--format", "bibtex", "-o", str(out_json)]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["exported"] == 1
        assert data["total_matching"] == 2
        assert data["total_in_db"] == 2
        assert data["truncated"] is True
