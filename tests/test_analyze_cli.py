"""`openalex analyze` at the CLI boundary.

Runs against a graph file so no network is involved. What matters here is that
the command surfaces its own limits — truncation, unsupported analyses, a
missing optional extra — rather than printing a confident-looking report that
quietly omits them.
"""

import json

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.core import openalex as oa


@pytest.fixture
def runner():
    state.json_output = False
    state.repl_mode = False
    yield CliRunner()
    state.json_output = False


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "articles.duckdb")
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield
    db_mod.close_cached_connections()


def _node(sid, role, **kw):
    base = {
        "id": sid,
        "label": kw.get("label", f"Work {sid}"),
        "year": 2020,
        "doi": kw.get("doi", f"10.1/{sid.lower()}"),
        "cited_by_count": kw.get("cited", 10),
        "is_seed": role == "seed",
        "role": role,
        "depth": kw.get("depth", 0),
        "reached_by": kw.get("reached", 0),
    }
    return base


@pytest.fixture
def graph_file(tmp_path):
    """Two coupled seeds over shared references."""
    graph = {
        "nodes": {
            n["id"]: n
            for n in [
                _node("S1", "seed"),
                _node("S2", "seed"),
                _node("A", "frontier", depth=1, reached=2, cited=900),
                _node("B", "frontier", depth=1, reached=2, cited=40),
            ]
        },
        "edges": [("S1", "A"), ("S1", "B"), ("S2", "A"), ("S2", "B")],
        "unmatched": [],
        "meta": {"depth": 1, "direction": "references", "truncated": False},
    }
    path = tmp_path / "g.json"
    oa.write_json(graph, path)
    return path


class TestAnalyzeFromFile:
    def test_reports_gaps(self, runner, graph_file):
        result = runner.invoke(root_cli, ["openalex", "analyze", "--from-file", str(graph_file)])
        assert result.exit_code == 0, result.output
        assert "does not contain" in result.output
        assert "Work A" in result.output

    def test_project_with_collection_rejected_even_from_file(self, runner, graph_file):
        result = runner.invoke(
            root_cli,
            ["openalex", "analyze", "--from-file", str(graph_file), "-p", "r1", "-c", "r1-a"],
        )
        assert result.exit_code != 0
        assert "not both" in result.output

    def test_json_structure(self, runner, graph_file):
        result = runner.invoke(
            root_cli, ["--json", "openalex", "analyze", "--from-file", str(graph_file)]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert set(data) >= {"topology", "stats", "gap_papers", "coupling", "co_citation"}
        assert data["stats"]["seeds"] == 2
        assert data["coupling"][0]["shared"] == 2

    def test_warns_that_centrality_is_unsupported(self, runner, graph_file):
        """A depth-1 star cannot support centrality — say so."""
        result = runner.invoke(root_cli, ["openalex", "analyze", "--from-file", str(graph_file)])
        assert "centrality" in result.output
        assert "star" in result.output

    def test_no_network_calls(self, runner, graph_file, monkeypatch):
        def _boom(*a, **k):  # pragma: no cover - must never run
            raise AssertionError("analyze --from-file must not hit the API")

        monkeypatch.setattr(oa, "oa_get", _boom)
        result = runner.invoke(root_cli, ["openalex", "analyze", "--from-file", str(graph_file)])
        assert result.exit_code == 0, result.output


class TestSurfacingLimits:
    def test_truncation_is_reported(self, runner, tmp_path):
        graph = {
            "nodes": {n["id"]: n for n in [_node("S1", "seed"), _node("A", "frontier", reached=1)]},
            "edges": [("S1", "A")],
            "unmatched": [],
            "meta": {"depth": 2, "direction": "references", "truncated": True},
        }
        path = tmp_path / "t.json"
        oa.write_json(graph, path)
        result = runner.invoke(root_cli, ["openalex", "analyze", "--from-file", str(path)])
        assert "truncated" in result.output.lower()

    def test_cited_by_graph_explains_missing_coupling(self, runner, tmp_path):
        graph = {
            "nodes": {n["id"]: n for n in [_node("S1", "seed"), _node("P", "frontier", reached=1)]},
            "edges": [("P", "S1")],
            "unmatched": [],
            "meta": {"depth": 1, "direction": "cited-by", "truncated": False},
        }
        path = tmp_path / "c.json"
        oa.write_json(graph, path)
        result = runner.invoke(root_cli, ["openalex", "analyze", "--from-file", str(path)])
        assert result.exit_code == 0, result.output
        assert "cited-by" in result.output

    def test_missing_analysis_extra_is_reported_not_fatal(
        self, runner, graph_file, monkeypatch
    ):
        """Without networkx the rest of the report must still be produced."""
        from scopus_for_dobby.core import graph_analysis as ga

        def _unsupported(*a, **k):
            raise ga.AnalysisUnsupported("needs the optional [analysis] extra")

        monkeypatch.setattr(ga, "communities", _unsupported)
        result = runner.invoke(
            root_cli,
            ["openalex", "analyze", "--from-file", str(graph_file), "--communities"],
        )
        assert result.exit_code == 0, result.output
        assert "[analysis]" in result.output
        assert "does not contain" in result.output  # report still rendered


class TestSeedResolution:
    def test_requires_a_seed_source(self, runner):
        result = runner.invoke(root_cli, ["openalex", "analyze"])
        assert result.exit_code != 0
        assert "collection" in result.output

    def test_graph_and_analyze_share_direction_default(self):
        """Same flags must give the same graph in both commands."""
        from scopus_for_dobby.cli.openalex import oa_analyze, oa_graph

        def _default(cmd, name):
            return next(p.default for p in cmd.params if p.name == name)

        for option in ("direction", "depth", "min_reached", "max_nodes", "deep_direction"):
            assert _default(oa_graph, option) == _default(oa_analyze, option), option
