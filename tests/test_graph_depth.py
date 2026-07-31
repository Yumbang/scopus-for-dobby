"""Depth-aware graph expansion and the relevance gate.

No network: `oa_get` is replaced by a fake OpenAlex built from a fixture, so
the expected node set at each depth is known by construction.

The gate is what makes depth viable at all — works carry ~35 references each,
so ungated expansion is ~15-25k nodes at depth 2 and millions at depth 3.
These tests pin that a node is expanded only when `min_reached` papers we
already hold point at it, and that roles/depths stay truthful.
"""

import pytest

from scopus_for_dobby.core import openalex as oa

# ── Fixture universe ─────────────────────────────────────────────────────────
#
#   S1, S2   seeds
#   A        referenced by BOTH seeds  -> passes a min_reached=2 gate
#   B        referenced by S1 only     -> stays frontier at that gate
#   C        referenced by S2 only     -> stays frontier
#   D, E     referenced by A           -> only appear if A was expanded (depth>=2)
#   F        referenced by D and E     -> one hop further again
#   X        referenced by S1 (level 1) AND by A (level 2) -> corroborated late

REFS = {
    "S1": ["A", "B", "X"],
    "S2": ["A", "C"],
    "A": ["D", "E", "X"],
    "B": ["D"],
    "C": ["E"],
    "D": ["F"],
    "E": ["F"],
    "F": [],
    "X": [],
}

DOIS = {"S1": "10.1/s1", "S2": "10.1/s2"}


def _work(sid):
    return {
        "id": f"https://openalex.org/{sid}",
        "display_name": f"Work {sid}",
        "publication_year": 2020,
        "doi": f"https://doi.org/{DOIS.get(sid, f'10.9/{sid.lower()}')}",
        "cited_by_count": 10,
        "referenced_works": [f"https://openalex.org/{r}" for r in REFS.get(sid, [])],
    }


@pytest.fixture
def fake_openalex(monkeypatch):
    """Serve /works from REFS; record the requests made."""
    calls = []

    def _fake_get(path, params=None):
        params = params or {}
        calls.append((path, params))
        filt = params.get("filter", "")
        if filt.startswith("doi:"):
            wanted = filt[len("doi:") :].split("|")
            by_doi = {v: k for k, v in DOIS.items()}
            return {"results": [_work(by_doi[d]) for d in wanted if d in by_doi]}
        if filt.startswith("openalex:"):
            wanted = filt[len("openalex:") :].split("|")
            return {"results": [_work(s) for s in wanted if s in REFS]}
        if filt.startswith("cites:"):
            return {"results": [], "meta": {}}
        return {"results": []}

    monkeypatch.setattr(oa, "oa_get", _fake_get)
    return calls


SEEDS = [{"eid": "e1", "doi": DOIS["S1"]}, {"eid": "e2", "doi": DOIS["S2"]}]


def build(**kwargs):
    kwargs.setdefault("direction", "references")
    return oa.build_citation_graph(SEEDS, **kwargs)


class TestDepthOne:
    def test_only_immediate_references(self, fake_openalex):
        g = build(depth=1)
        assert set(g["nodes"]) == {"S1", "S2", "A", "B", "C", "X"}

    def test_seeds_are_marked(self, fake_openalex):
        g = build(depth=1)
        assert g["nodes"]["S1"]["role"] == oa.ROLE_SEED
        assert g["nodes"]["S1"]["is_seed"] is True
        assert g["nodes"]["A"]["role"] == oa.ROLE_FRONTIER

    def test_reached_by_counts_distinct_holders(self, fake_openalex):
        g = build(depth=1)
        assert g["nodes"]["A"]["reached_by"] == 2  # both seeds cite A
        assert g["nodes"]["B"]["reached_by"] == 1

    def test_depth_is_recorded(self, fake_openalex):
        g = build(depth=1)
        assert g["nodes"]["S1"]["depth"] == 0
        assert g["nodes"]["A"]["depth"] == 1


class TestRelevanceGate:
    def test_only_corroborated_nodes_expand(self, fake_openalex):
        """A is cited by both seeds; B and C by one each."""
        g = build(depth=2, min_reached=2)
        assert g["nodes"]["A"]["role"] == oa.ROLE_EXPANDED
        assert g["nodes"]["B"]["role"] == oa.ROLE_FRONTIER
        assert g["nodes"]["C"]["role"] == oa.ROLE_FRONTIER
        # A's references entered the graph; B's and C's did not.
        assert {"D", "E"} <= set(g["nodes"])

    def test_lowering_the_gate_expands_more(self, fake_openalex):
        g = build(depth=2, min_reached=1)
        assert g["nodes"]["B"]["role"] == oa.ROLE_EXPANDED
        assert g["nodes"]["C"]["role"] == oa.ROLE_EXPANDED

    def test_depth_three_reaches_one_hop_further(self, fake_openalex):
        """With the gate open, each level advances the frontier by one hop."""
        assert "F" not in build(depth=2, min_reached=1)["nodes"]
        g3 = build(depth=3, min_reached=1)
        assert "F" in g3["nodes"]
        assert g3["nodes"]["F"]["depth"] == 3

    def test_gate_can_halt_expansion_before_the_depth_limit(self, fake_openalex):
        """Asking for depth 3 does not force three levels of fetching.

        At min_reached=2 only A is ever corroborated, so depth 3 finds nothing
        new — the gate, not the depth number, decides how far this goes.
        """
        g2 = build(depth=2, min_reached=2)
        g3 = build(depth=3, min_reached=2)
        assert set(g3["nodes"]) == set(g2["nodes"])

    def test_late_corroboration_still_expands(self, fake_openalex):
        """X is seen at level 1 (via S1) and corroborated at level 2 (via A).

        Its first-seen depth is 1, but it only clears the gate after level 2 —
        an expansion rule keyed on first-seen depth would skip it forever.
        """
        g = build(depth=3, min_reached=2)
        assert g["nodes"]["X"]["depth"] == 1
        assert g["nodes"]["X"]["reached_by"] == 2
        assert g["nodes"]["X"]["role"] == oa.ROLE_EXPANDED

    def test_frontier_nodes_never_gain_out_edges(self, fake_openalex):
        """The defining property: a frontier node's edges are truncated."""
        g = build(depth=2, min_reached=2)
        sources = {s for s, _ in g["edges"]}
        for sid, node in g["nodes"].items():
            if node["role"] == oa.ROLE_FRONTIER:
                assert sid not in sources, f"{sid} is frontier but has out-edges"


class TestBudget:
    def test_max_nodes_stops_and_reports(self, fake_openalex):
        g = build(depth=3, min_reached=1, max_nodes=4)
        assert g["meta"]["truncated"] is True
        assert len(g["nodes"]) >= 4

    def test_untruncated_runs_say_so(self, fake_openalex):
        g = build(depth=1)
        assert g["meta"]["truncated"] is False

    def test_meta_records_the_settings(self, fake_openalex):
        g = build(depth=2, min_reached=3, per_seed_limit=7)
        assert g["meta"]["depth"] == 2
        assert g["meta"]["min_reached"] == 3
        assert g["meta"]["per_seed_limit"] == 7
        assert g["meta"]["roles"]

    def test_depth_is_clamped(self, fake_openalex):
        assert build(depth=99)["meta"]["depth"] == oa.MAX_DEPTH
        assert build(depth=0)["meta"]["depth"] == 1

    def test_deep_direction_defaults_to_references(self, fake_openalex):
        """Citers cost one paginated request per node — not at depth."""
        build(depth=2, direction="both", min_reached=2)
        cites_calls = [p for _, p in fake_openalex if p.get("filter", "").startswith("cites:")]
        # Seeds only (2), not the expanded depth-1 node.
        assert len(cites_calls) == 2


class TestPlanExpansion:
    def test_counts_the_next_level_exactly(self, fake_openalex):
        g = build(depth=1)
        plan = oa.plan_expansion(g, depth=2, min_reached=2)
        assert plan["current_depth"] == 1
        assert plan["levels"][0]["exact"] is True
        assert plan["levels"][0]["expanding"] == 1  # only A clears the gate

    def test_projects_further_levels(self, fake_openalex):
        g = build(depth=1)
        plan = oa.plan_expansion(g, depth=3, min_reached=2)
        assert [level["level"] for level in plan["levels"]] == [2, 3]
        assert plan["levels"][1]["exact"] is False
