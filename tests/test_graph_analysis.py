"""Citation-graph analysis: correctness, and refusing to lie.

Graphs here are built by hand so every expected count can be checked against
the fixture. The subtler half of these tests is about what the module must
*not* do: include frontier nodes (whose edges are truncated by where expansion
stopped) in structural measures, or report coupling on a graph that has no
reference edges at all.
"""

import pytest

from scopus_for_dobby.core import graph_analysis as ga
from scopus_for_dobby.core.openalex import ROLE_EXPANDED, ROLE_FRONTIER, ROLE_SEED


def node(sid, role, *, depth=0, reached=0, cited=0, doi="", year=2020, label=None):
    return {
        "id": sid,
        "label": label or f"Work {sid}",
        "year": year,
        "doi": doi,
        "cited_by_count": cited,
        "is_seed": role == ROLE_SEED,
        "role": role,
        "depth": depth,
        "reached_by": reached,
    }


def graph(nodes, edges, **meta):
    meta.setdefault("depth", 1)
    meta.setdefault("direction", "references")
    return {"nodes": {n["id"]: n for n in nodes}, "edges": sorted(edges), "unmatched": [], "meta": meta}


# S1 and S2 share references A and B; S2 additionally cites C.
COUPLED = graph(
    [
        node("S1", ROLE_SEED),
        node("S2", ROLE_SEED),
        node("S3", ROLE_SEED),
        node("A", ROLE_FRONTIER, depth=1, reached=2, cited=500, doi="10.1/a"),
        node("B", ROLE_FRONTIER, depth=1, reached=2, cited=50, doi="10.1/b"),
        node("C", ROLE_FRONTIER, depth=1, reached=1, cited=900, doi="10.1/c"),
        node("Z", ROLE_FRONTIER, depth=1, reached=1, cited=10, doi="10.1/z"),
    ],
    [("S1", "A"), ("S1", "B"), ("S2", "A"), ("S2", "B"), ("S2", "C"), ("S3", "Z")],
)


class TestBibliographicCoupling:
    def test_counts_shared_references(self):
        pairs = ga.bibliographic_coupling(COUPLED)
        top = pairs[0]
        assert {top["source"], top["target"]} == {"S1", "S2"}
        assert top["shared"] == 2
        assert top["shared_ids"] == ["A", "B"]

    def test_uncoupled_seeds_are_absent(self):
        pairs = ga.bibliographic_coupling(COUPLED)
        assert not [p for p in pairs if "S3" in (p["source"], p["target"])]

    def test_min_shared_filters(self):
        assert ga.bibliographic_coupling(COUPLED, min_shared=3) == []

    def test_frontier_nodes_are_excluded(self):
        """Frontier edges are truncated; including them understates every pair.

        A and B are frontier here — if they leaked in, they would appear as
        papers with (empty) reference sets.
        """
        pairs = ga.bibliographic_coupling(COUPLED)
        involved = {p["source"] for p in pairs} | {p["target"] for p in pairs}
        assert involved <= {"S1", "S2", "S3"}

    def test_expanded_nodes_are_included(self):
        g = graph(
            [
                node("S1", ROLE_SEED),
                node("E1", ROLE_EXPANDED, depth=1, reached=2),
                node("R", ROLE_FRONTIER, depth=2, reached=2),
                node("Q", ROLE_FRONTIER, depth=2, reached=2),
            ],
            [("S1", "R"), ("S1", "Q"), ("E1", "R"), ("E1", "Q")],
            depth=2,
        )
        pairs = ga.bibliographic_coupling(g)
        assert pairs and pairs[0]["shared"] == 2
        assert {pairs[0]["source"], pairs[0]["target"]} == {"E1", "S1"}


class TestCoCitation:
    def test_counts_shared_citers(self):
        pairs = ga.co_citation(COUPLED, min_shared=2)
        assert len(pairs) == 1
        assert {pairs[0]["source"], pairs[0]["target"]} == {"A", "B"}
        assert pairs[0]["shared"] == 2

    def test_min_shared_is_respected(self):
        assert ga.co_citation(COUPLED, min_shared=3) == []

    def test_single_citer_pairs_excluded_by_default(self):
        """A and C share only S2 — one citer is not co-citation."""
        pairs = ga.co_citation(COUPLED, min_shared=2)
        assert not [p for p in pairs if "C" in (p["source"], p["target"])]


class TestGapPapers:
    def test_ranks_by_corroboration_then_citations(self):
        """C is far more cited, but A is reached by more of the corpus."""
        gaps = ga.gap_papers(COUPLED)
        assert gaps[0]["id"] == "A"
        assert [g["id"] for g in gaps[:3]] == ["A", "B", "C"]

    def test_excludes_papers_already_held(self):
        gaps = ga.gap_papers(COUPLED, known_dois=["10.1/A"])  # case-insensitive
        assert "A" not in [g["id"] for g in gaps]

    def test_excludes_seeds(self):
        assert not [g for g in ga.gap_papers(COUPLED) if g["id"].startswith("S")]

    def test_limit_applies(self):
        assert len(ga.gap_papers(COUPLED, limit=2)) == 2

    def test_works_on_frontier_nodes(self):
        """Attribute ranking is valid for frontier nodes — the whole point."""
        assert all(g["role"] == ROLE_FRONTIER for g in ga.gap_papers(COUPLED))


class TestOutlierSeeds:
    def test_finds_uncoupled_seed(self):
        outliers = ga.outlier_seeds(COUPLED)
        assert [o["id"] for o in outliers] == ["S3"]

    def test_coupled_seeds_are_not_outliers(self):
        assert "S1" not in [o["id"] for o in ga.outlier_seeds(COUPLED)]


class TestCorpusStats:
    def test_counts_roles(self):
        stats = ga.corpus_stats(COUPLED)
        assert stats["seeds"] == 3
        assert stats["frontier"] == 4
        assert stats["nodes"] == 7
        assert stats["edges"] == 6

    def test_reports_year_range(self):
        assert ga.corpus_stats(COUPLED)["year_range"] == [2020, 2020]


class TestDescribeTopology:
    def test_depth_one_rejects_centrality(self):
        report = ga.describe_topology(COUPLED)
        assert report["supports"]["centrality"] is False
        assert "star" in report["reasons"]["centrality"]

    def test_cited_by_graph_cannot_support_coupling(self):
        """No reference edges at all — say so rather than return empty."""
        g = graph(
            [
                node("S1", ROLE_SEED),
                node("P", ROLE_FRONTIER, depth=1, reached=1),
            ],
            [("P", "S1")],
            direction="cited-by",
        )
        report = ga.describe_topology(g)
        assert report["supports"]["coupling"] is False
        assert "cited-by" in report["reasons"]["coupling"]

    def test_gap_papers_always_supported(self):
        assert ga.describe_topology(COUPLED)["supports"]["gap_papers"] is True

    def test_reports_truncation(self):
        g = graph([node("S1", ROLE_SEED)], [], truncated=True)
        assert ga.describe_topology(g)["truncated"] is True


class TestCommunities:
    def test_requires_the_extra_or_works(self):
        """Skips when networkx is absent — that is the documented behaviour."""
        pytest.importorskip("networkx")
        pairs = ga.bibliographic_coupling(COUPLED)
        found = ga.communities(pairs)
        assert found
        assert found[0]["size"] >= 2
        assert found[0]["representative"]

    def test_empty_projection_is_not_an_error(self):
        assert ga.communities([]) == []

    def test_missing_extra_raises_actionable_error(self, monkeypatch):
        """Simulate the extra not being installed."""
        import builtins

        real_import = builtins.__import__

        def _no_networkx(name, *args, **kwargs):
            if name == "networkx":
                raise ImportError("No module named 'networkx'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_networkx)
        with pytest.raises(ga.AnalysisUnsupported, match=r"\[analysis\]"):
            ga.communities([{"source": "a", "target": "b", "shared": 1}])


class TestGraphRoundTrip:
    """Analysis must be able to run on a graph exported earlier.

    Without a reader, every look at the same corpus re-spends API calls.
    """

    def _graph(self):
        return {
            "nodes": {
                "A": node("A", ROLE_SEED, doi="10.1/a", cited=5),
                "B": node("B", ROLE_FRONTIER, depth=1, reached=2, cited=99, doi="10.1/b"),
            },
            "edges": [("A", "B")],
            "unmatched": [],
            "meta": {"depth": 1, "direction": "references"},
        }

    @pytest.mark.parametrize("fmt,suffix", [("json", ".json"), ("graphml", ".graphml")])
    def test_round_trip_preserves_structure(self, tmp_path, fmt, suffix):
        from scopus_for_dobby.core import openalex as oa

        original = self._graph()
        path = tmp_path / f"g{suffix}"
        oa.GRAPH_WRITERS[fmt](original, path)
        loaded = oa.read_graph(path)

        assert set(loaded["nodes"]) == set(original["nodes"])
        assert loaded["edges"] == original["edges"]

    @pytest.mark.parametrize("fmt,suffix", [("json", ".json"), ("graphml", ".graphml")])
    def test_round_trip_preserves_types(self, tmp_path, fmt, suffix):
        """Text formats lose typing; the reader must restore it."""
        from scopus_for_dobby.core import openalex as oa

        path = tmp_path / f"g{suffix}"
        oa.GRAPH_WRITERS[fmt](self._graph(), path)
        b = oa.read_graph(path)["nodes"]["B"]

        assert b["role"] == ROLE_FRONTIER
        assert b["depth"] == 1
        assert b["reached_by"] == 2
        assert b["cited_by_count"] == 99
        assert b["is_seed"] is False

    def test_analysis_runs_on_a_loaded_graph(self, tmp_path):
        from scopus_for_dobby.core import openalex as oa

        path = tmp_path / "g.json"
        oa.write_json(COUPLED, path)
        loaded = oa.read_graph(path)

        assert ga.bibliographic_coupling(loaded)[0]["shared"] == 2
        assert ga.gap_papers(loaded)[0]["id"] == "A"

    def test_json_uses_the_modern_networkx_key(self, tmp_path):
        """Edges are keyed `edges`, which is where networkx landed.

        networkx 3.6 made `edges` the default. Older versions (3.4/3.5 — and
        3.4.2 is the newest installable on Python 3.10) still default to
        `links`, but accept `edges="edges"` explicitly. So the file is forward-
        compatible everywhere; only the bare call is version-dependent, which
        is why the explicit form is asserted for every version.
        """
        import json as _json

        from scopus_for_dobby.core import openalex as oa

        path = tmp_path / "g.json"
        oa.write_json(self._graph(), path)
        payload = _json.loads(path.read_text())
        assert "edges" in payload

        nx = pytest.importorskip("networkx")
        assert nx.node_link_graph(payload, edges="edges").number_of_edges() == 1

        major, minor = (int(p) for p in nx.__version__.split(".")[:2])
        if (major, minor) >= (3, 6):
            # The call people actually write, on a current networkx.
            assert nx.node_link_graph(payload).number_of_edges() == 1

    def test_reader_still_accepts_the_legacy_links_key(self, tmp_path):
        """Graphs exported before the change must keep loading."""
        import json as _json

        from scopus_for_dobby.core import openalex as oa

        path = tmp_path / "old.json"
        path.write_text(
            _json.dumps(
                {
                    "directed": True,
                    "nodes": [{"id": "A", "is_seed": True}, {"id": "B"}],
                    "links": [{"source": "A", "target": "B"}],
                }
            )
        )
        loaded = oa.read_graph(path)
        assert loaded["edges"] == [("A", "B")]

    def test_csv_is_write_only_and_says_so(self, tmp_path):
        from scopus_for_dobby.core import openalex as oa

        with pytest.raises(ValueError, match="write-only"):
            oa.read_graph(tmp_path / "x.csv")


class TestGapPaperQuality:
    """Gap papers is the actionable section — it must not carry noise."""

    def test_unresolved_stubs_are_excluded(self):
        """Works OpenAlex no longer returns survive as ID-labelled stubs.

        They keep the edge list consistent but a reader cannot go find them,
        so they have no place in a "read these next" list.
        """
        g = graph(
            [
                node("S1", ROLE_SEED),
                node("W999", ROLE_FRONTIER, depth=1, reached=3, cited=0, doi="", label="W999"),
                node("R", ROLE_FRONTIER, depth=1, reached=2, cited=10, doi="10.1/r"),
            ],
            [("S1", "W999"), ("S1", "R")],
        )
        ids = [row["id"] for row in ga.gap_papers(g)]
        assert "W999" not in ids
        assert "R" in ids

    def test_identifiable_papers_without_doi_are_kept(self):
        """No DOI but a real title is still actionable — keep it."""
        g = graph(
            [
                node("S1", ROLE_SEED),
                node("T", ROLE_FRONTIER, depth=1, reached=2, cited=5, doi="", label="A real title"),
            ],
            [("S1", "T")],
        )
        assert [row["id"] for row in ga.gap_papers(g)] == ["T"]
