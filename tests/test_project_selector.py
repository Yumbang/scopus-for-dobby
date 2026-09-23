"""`-p/--project` on the commands that fetch from the network.

`fulltext`, `openalex enrich`, `openalex graph` and `openalex analyze` all take
a batch of saved papers; `-p` makes that batch the deduplicated union of a
project's collections. The network boundary is replaced with a spy, so what is
asserted is exactly the batch each command would have spent quota on.
"""

import json

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.core import fulltext as ft
from scopus_for_dobby.core import openalex as oa


def _entry(n: int) -> dict:
    return {
        "dc:title": f"Paper {n}",
        "prism:doi": f"10.1/p{n}",
        "eid": f"2-s2.0-{n}",
        "prism:coverDate": "2024-01-01",
    }


@pytest.fixture(autouse=True)
def library(monkeypatch, tmp_path):
    """col1 = {1, 2}, col2 = {2, 3} in project `thesis`; col3 = {4} outside it."""
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "articles.duckdb")
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ft, "CONFIG_DIR", tmp_path)
    state.json_output = False
    state.repl_mode = False

    db_mod.add_entries([_entry(n) for n in (1, 2, 3, 4)])
    for name, ns in {"col1": (1, 2), "col2": (2, 3), "col3": (4,)}.items():
        db_mod.create_collection(name)
        db_mod.add_to_collection(name, [f"2-s2.0-{n}" for n in ns])
    db_mod.assign_collections("thesis", ["col1", "col2"])
    yield
    state.json_output = False
    db_mod.close_cached_connections()


PROJECT_EIDS = ["2-s2.0-1", "2-s2.0-2", "2-s2.0-3"]


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fetched(monkeypatch):
    """Record what `fulltext` would have fetched."""
    calls: list[list[dict]] = []

    def _fake(items, *, force=False, request=None):
        calls.append(items)
        return {"total": len(items), "counts": {}, "items": []}

    monkeypatch.setattr(ft, "fetch_batch", _fake)
    return calls


@pytest.fixture
def seeded(monkeypatch):
    """Record the seeds `openalex graph` / `analyze` would have built from."""
    calls: list[list[dict]] = []

    def _fake(seeds, **_kw):
        calls.append(seeds)
        return {
            "nodes": {},
            "edges": [],
            "unmatched": [],
            "meta": {
                "roles": {},
                "depth": 1,
                "truncated": False,
                "max_nodes": None,
                "requests": 0,
            },
        }

    monkeypatch.setattr(oa, "build_citation_graph", _fake)
    monkeypatch.setattr(oa, "plan_expansion", lambda *a, **kw: {})
    return calls


class TestFulltext:
    def test_project_is_deduplicated_union(self, runner, fetched):
        result = runner.invoke(root_cli, ["--json", "fulltext", "-p", "thesis"])
        assert result.exit_code == 0, result.output
        assert sorted(i["eid"] for i in fetched[0]) == PROJECT_EIDS

    def test_project_ands_with_query(self, runner, fetched):
        result = runner.invoke(root_cli, ["--json", "fulltext", "-p", "thesis", "-q", "Paper 3"])
        assert result.exit_code == 0, result.output
        assert [i["eid"] for i in fetched[0]] == ["2-s2.0-3"]

    def test_project_with_collection_fetches_nothing(self, runner, fetched):
        result = runner.invoke(root_cli, ["fulltext", "-p", "thesis", "-c", "col1"])
        assert result.exit_code != 0
        assert "not both" in result.output
        assert fetched == []

    def test_unknown_project(self, runner, fetched):
        result = runner.invoke(root_cli, ["fulltext", "-p", "nope"])
        assert result.exit_code != 0
        assert "Project not found" in result.output
        assert fetched == []


class TestSeeds:
    @pytest.mark.parametrize("cmd", [["graph"], ["analyze", "--dry-run"]])
    def test_seeds_from_project(self, runner, seeded, tmp_path, cmd):
        args = ["--json", "openalex", *cmd, "-p", "thesis"]
        if cmd == ["graph"]:
            args += ["-o", str(tmp_path / "g.json")]
        result = runner.invoke(root_cli, args)
        assert result.exit_code == 0, result.output
        assert sorted(s["eid"] for s in seeded[0]) == PROJECT_EIDS

    def test_analyze_project_ands_with_tag(self, runner, seeded):
        db_mod.tag_articles(["2-s2.0-2", "2-s2.0-4"], ["core"])
        result = runner.invoke(
            root_cli, ["--json", "openalex", "analyze", "--dry-run", "-p", "thesis", "-t", "core"]
        )
        assert result.exit_code == 0, result.output
        assert [s["eid"] for s in seeded[0]] == ["2-s2.0-2"]

    @pytest.mark.parametrize("cmd", ["graph", "analyze"])
    def test_project_with_collection_builds_nothing(self, runner, seeded, cmd):
        result = runner.invoke(root_cli, ["openalex", cmd, "-p", "thesis", "-c", "col1"])
        assert result.exit_code != 0
        assert "not both" in result.output
        assert seeded == []

    def test_unknown_project(self, runner, seeded):
        result = runner.invoke(root_cli, ["openalex", "analyze", "-p", "nope"])
        assert result.exit_code != 0
        assert "Project not found" in result.output
        assert seeded == []


class TestEnrich:
    @pytest.fixture
    def queried(self, monkeypatch):
        calls: list[list[str]] = []

        def _fake(dois, **_kw):
            calls.append(list(dois))
            return {}

        monkeypatch.setattr(oa, "fetch_works_by_dois", _fake)
        return calls

    def test_enrich_project(self, runner, queried):
        result = runner.invoke(root_cli, ["--json", "openalex", "enrich", "-p", "thesis"])
        assert result.exit_code == 0, result.output
        assert sorted(queried[0]) == ["10.1/p1", "10.1/p2", "10.1/p3"]
        assert json.loads(result.output)["enriched"] == 0

    def test_project_with_collection_queries_nothing(self, runner, queried):
        result = runner.invoke(root_cli, ["openalex", "enrich", "-p", "thesis", "-c", "col1"])
        assert result.exit_code != 0
        assert "not both" in result.output
        assert queried == []
