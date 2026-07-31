"""Tests for the OpenAlex integration — client, enrichment, citation graphs.

All HTTP is mocked at the ``requests.get`` boundary; no network calls.
"""

import json
import xml.etree.ElementTree as ET

import pytest

from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.core import openalex as oa

# ── Fixtures ──────────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, payload, status_code=200, reason="OK"):
        self._payload = payload
        self.status_code = status_code
        self.reason = reason
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


@pytest.fixture
def oa_env(monkeypatch):
    """Silence throttling and isolate from the real config file."""
    monkeypatch.setattr(oa, "_throttle", lambda: None)
    monkeypatch.setattr(oa, "get_polite_email", lambda: None)


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield db_file
    db_mod.close_cached_connections()


def _work(wid, *, doi=None, title="Title", year=2020, cited=5, refs=None, **extra):
    w = {
        "id": f"https://openalex.org/{wid}",
        "display_name": title,
        "publication_year": year,
        "cited_by_count": cited,
        "doi": f"https://doi.org/{doi}" if doi else None,
    }
    if refs is not None:
        w["referenced_works"] = [f"https://openalex.org/{r}" for r in refs]
    w.update(extra)
    return w


# ── DOI / ID normalization ───────────────────────────────────────────────────


class TestIdentifiers:
    def test_normalize_doi_strips_prefixes_and_lowercases(self):
        assert oa.normalize_doi("https://doi.org/10.1/ABC") == "10.1/abc"
        assert oa.normalize_doi("doi:10.1/abc") == "10.1/abc"
        assert oa.normalize_doi("  10.1/Abc ") == "10.1/abc"

    def test_normalize_doi_empty(self):
        assert oa.normalize_doi(None) is None
        assert oa.normalize_doi("") is None

    def test_short_id(self):
        assert oa._short_id("https://openalex.org/W123") == "W123"
        assert oa._short_id(None) is None


# ── Works fetching ────────────────────────────────────────────────────────────


class TestFetchWorks:
    def test_dois_batched_at_50(self, oa_env, monkeypatch):
        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append(params)
            return FakeResponse({"results": []})

        monkeypatch.setattr(oa.requests, "get", fake_get)
        oa.fetch_works_by_dois([f"10.1/{i}" for i in range(120)])
        assert len(calls) == 3
        first_filter = calls[0]["filter"]
        assert first_filter.startswith("doi:")
        assert first_filter.count("|") == 49  # 50 values per OR-filter

    def test_dois_results_keyed_by_normalized_doi(self, oa_env, monkeypatch):
        monkeypatch.setattr(
            oa.requests,
            "get",
            lambda url, params=None, timeout=None: FakeResponse(
                {"results": [_work("W1", doi="10.1/ABC")]}
            ),
        )
        found = oa.fetch_works_by_dois(["https://doi.org/10.1/abc"])
        assert "10.1/abc" in found

    def test_citing_works_cursor_pagination_and_limit(self, oa_env, monkeypatch):
        pages = [
            FakeResponse(
                {"results": [_work(f"W{i}") for i in range(200)], "meta": {"next_cursor": "abc"}}
            ),
            FakeResponse(
                {
                    "results": [_work(f"W{i}") for i in range(200, 250)],
                    "meta": {"next_cursor": None},
                }
            ),
        ]
        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append(params)
            return pages[len(calls) - 1]

        monkeypatch.setattr(oa.requests, "get", fake_get)
        out = oa.fetch_citing_works("W999", limit=230)
        assert len(out) == 230
        assert calls[0]["cursor"] == "*"
        assert calls[1]["cursor"] == "abc"
        assert calls[0]["filter"] == "cites:W999"

    def test_error_is_sanitized(self, oa_env, monkeypatch):
        monkeypatch.setattr(
            oa.requests,
            "get",
            lambda url, params=None, timeout=None: FakeResponse(
                {"error": "secret internals"}, status_code=403, reason="Forbidden"
            ),
        )
        with pytest.raises(RuntimeError) as exc:
            oa.oa_get("/works")
        assert "secret internals" not in str(exc.value)
        assert "403" in str(exc.value)

    def test_polite_email_added_when_configured(self, oa_env, monkeypatch):
        captured = {}

        def fake_get(url, params=None, timeout=None):
            captured.update(params)
            return FakeResponse({"results": []})

        monkeypatch.setattr(oa.requests, "get", fake_get)
        monkeypatch.setattr(oa, "get_polite_email", lambda: "me@example.com")
        oa.oa_get("/works", {"filter": "doi:x"})
        assert captured["mailto"] == "me@example.com"


# ── Enrichment normalization ──────────────────────────────────────────────────


class TestNormalizeEnrichment:
    def test_prefers_pdf_then_landing_then_oa_url(self):
        w = _work(
            "W1",
            doi="10.1/a",
            best_oa_location={"pdf_url": "P", "landing_page_url": "L"},
            open_access={"oa_status": "gold", "oa_url": "O"},
        )
        assert oa.normalize_enrichment(w)["oa_url"] == "P"
        w["best_oa_location"] = {"landing_page_url": "L"}
        assert oa.normalize_enrichment(w)["oa_url"] == "L"
        w["best_oa_location"] = None
        assert oa.normalize_enrichment(w)["oa_url"] == "O"

    def test_topics_primary_first_dedup_capped(self):
        w = _work(
            "W1",
            primary_topic={"display_name": "A"},
            topics=[{"display_name": n} for n in ["A", "B", "C", "D", "E", "F"]],
        )
        topics = oa.normalize_enrichment(w)["topics"]
        assert topics[0] == "A"
        assert len(topics) == 5
        assert len(set(topics)) == 5

    def test_minimal_work(self):
        e = oa.normalize_enrichment({"id": "https://openalex.org/W1"})
        assert e["openalex_id"] == "W1"
        assert e["oa_status"] == ""
        assert e["oa_url"] == ""
        assert e["cited_by_count"] == 0
        assert e["topics"] == []


# ── Citation graph ────────────────────────────────────────────────────────────


@pytest.fixture
def graph_env(monkeypatch):
    """Stub the network layer of build_citation_graph.

    Seeds: S1 (doi 10.1/s1) references R1 and S2; S2 (doi 10.1/s2).
    C1 cites S1. R1 resolves; R2 (referenced by S2) does not (deleted work).
    """
    seed_works = {
        "10.1/s1": _work("S1", doi="10.1/s1", refs=["R1", "S2"]),
        "10.1/s2": _work("S2", doi="10.1/s2", refs=["R2"]),
    }
    monkeypatch.setattr(
        oa,
        "fetch_works_by_dois",
        lambda dois, select=None, on_progress=None: {
            d: seed_works[d] for d in (oa.normalize_doi(x) for x in dois) if d in seed_works
        },
    )
    monkeypatch.setattr(
        oa,
        "fetch_works_by_ids",
        lambda ids, select=None: {"R1": _work("R1", doi="10.1/r1")} if "R1" in set(ids) else {},
    )
    monkeypatch.setattr(
        oa,
        "fetch_citing_works",
        lambda wid, limit=200: [_work("C1")] if wid == "S1" else [],
    )


class TestCitationGraph:
    SEEDS = [
        {"eid": "e1", "doi": "10.1/s1"},
        {"eid": "e2", "doi": "10.1/s2"},
        {"eid": "e3", "doi": "10.1/missing"},
        {"eid": "e4", "doi": None},
    ]

    def test_references_direction(self, graph_env):
        g = oa.build_citation_graph(self.SEEDS, direction="references")
        assert ("S1", "R1") in g["edges"]
        assert ("S1", "S2") in g["edges"]  # seed-to-seed edge
        assert ("S2", "R2") in g["edges"]
        assert ("C1", "S1") not in g["edges"]
        assert g["nodes"]["R1"]["doi"] == "10.1/r1"  # resolved metadata
        assert g["nodes"]["R2"]["label"] == "R2"  # unresolvable stub
        assert g["nodes"]["S1"]["is_seed"] and g["nodes"]["S2"]["is_seed"]
        assert not g["nodes"]["R1"]["is_seed"]
        assert g["unmatched"] == ["e3"]  # DOI unknown to OpenAlex; e4 has no DOI

    def test_cited_by_direction(self, graph_env):
        g = oa.build_citation_graph(self.SEEDS, direction="cited-by")
        assert g["edges"] == [("C1", "S1")]

    def test_both_directions(self, graph_env):
        g = oa.build_citation_graph(self.SEEDS, direction="both")
        assert ("C1", "S1") in g["edges"]
        assert ("S1", "R1") in g["edges"]

    def test_per_seed_limit_truncates_references(self, graph_env):
        g = oa.build_citation_graph(self.SEEDS, direction="references", per_seed_limit=1)
        s1_refs = [e for e in g["edges"] if e[0] == "S1"]
        assert len(s1_refs) == 1


class TestGraphWriters:
    GRAPH = {
        "nodes": {
            "S1": {
                "id": "S1",
                "label": 'A "quoted" <title>',
                "year": 2020,
                "doi": "10.1/s1",
                "cited_by_count": 5,
                "is_seed": True,
            },
            "R1": {
                "id": "R1",
                "label": "Ref",
                "year": None,
                "doi": "",
                "cited_by_count": 0,
                "is_seed": False,
            },
        },
        "edges": [("S1", "R1")],
        "unmatched": [],
    }

    def test_graphml_is_well_formed(self, tmp_path):
        files = oa.write_graphml(self.GRAPH, tmp_path / "g.graphml")
        # S314: parsing a file this test just generated — not untrusted input.
        root = ET.parse(files[0]).getroot()  # noqa: S314
        ns = {"g": "http://graphml.graphdrawing.org/xmlns"}
        nodes = root.findall(".//g:node", ns)
        edges = root.findall(".//g:edge", ns)
        assert len(nodes) == 2
        assert len(edges) == 1
        assert edges[0].get("source") == "S1"
        labels = {d.text for n in nodes for d in n.findall("g:data", ns)}
        assert 'A "quoted" <title>' in labels  # escaping round-trips

    def test_csv_writes_node_and_edge_tables(self, tmp_path):
        files = oa.write_csv(self.GRAPH, tmp_path / "g.csv")
        assert len(files) == 2
        nodes_csv = (tmp_path / "g_nodes.csv").read_text()
        edges_csv = (tmp_path / "g_edges.csv").read_text()
        assert nodes_csv.startswith("Id,Label")
        assert "S1" in nodes_csv
        assert "Source,Target" in edges_csv
        assert "S1,R1" in edges_csv

    def test_json_node_link(self, tmp_path):
        """Edges are keyed `edges`, not the historical `links`.

        networkx 3.6 made `edges` the default, so a file using `links` makes
        the call people actually write — `node_link_graph(json.load(f))` —
        raise KeyError. `read_graph` still accepts either key.
        """
        files = oa.write_json(self.GRAPH, tmp_path / "g.json")
        data = json.loads((tmp_path / "g.json").read_text())
        assert data["directed"] is True
        assert {n["id"] for n in data["nodes"]} == {"S1", "R1"}
        assert data["edges"] == [{"source": "S1", "target": "R1"}]
        assert "links" not in data
        assert files == [str(tmp_path / "g.json")]


# ── DB enrichment + migration ─────────────────────────────────────────────────


SCOPUS_ENTRY = {
    "eid": "2-s2.0-001",
    "dc:title": "Seed Paper",
    "dc:creator": "Kim",
    "prism:doi": "10.1/s1",
}


class TestEnrichArticles:
    def test_enrich_updates_fields(self, tmp_db):
        db_mod.add_entries([SCOPUS_ENTRY])
        result = db_mod.enrich_articles(
            [
                {
                    "eid": "2-s2.0-001",
                    "openalex_id": "W1",
                    "oa_status": "gold",
                    "oa_url": "https://x/pdf",
                    "cited_by_count": 42,
                    "topics": ["ML", "CV"],
                },
                {"eid": "2-s2.0-unknown", "openalex_id": "W9"},
            ]
        )
        assert result == {"enriched": 1, "skipped": 1}
        art = db_mod.get_article("2-s2.0-001")
        assert art["openalex_id"] == "W1"
        assert art["oa_status"] == "gold"
        assert art["oa_url"] == "https://x/pdf"
        assert art["openalex_cited_by"] == 42
        assert art["openalex_topics"] == ["ML", "CV"]
        assert art["openalex_enriched_at"]

    def test_enrich_emits_event(self, tmp_db):
        db_mod.add_entries([SCOPUS_ENTRY])
        db_mod.enrich_articles([{"eid": "2-s2.0-001", "openalex_id": "W1"}])
        conn = db_mod._get_conn()
        kinds = [r[0] for r in conn.execute("SELECT kind FROM events").fetchall()]
        assert "article.enriched" in kinds


class TestSchemaMigration:
    def test_fresh_db_is_v2_with_columns(self, tmp_db):
        conn = db_mod._get_conn()
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 2
        cols = {r[1] for r in conn.execute("PRAGMA table_info('articles')").fetchall()}
        assert {
            "openalex_id",
            "oa_status",
            "oa_url",
            "openalex_cited_by",
            "openalex_topics",
            "openalex_enriched_at",
        } <= cols

    def test_v1_db_migrates_to_v2(self, tmp_db):
        # Build a fresh (v2) DB, then strip it back to v1 shape.
        conn = db_mod._get_conn()
        for col in (
            "openalex_id",
            "oa_status",
            "oa_url",
            "openalex_cited_by",
            "openalex_topics",
            "openalex_enriched_at",
        ):
            conn.execute(f"ALTER TABLE articles DROP COLUMN {col}")  # noqa: S608
        conn.execute("UPDATE schema_meta SET version = 1")
        db_mod._schema_initialized.clear()

        db_mod._ensure_schema(conn)

        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 2
        cols = {r[1] for r in conn.execute("PRAGMA table_info('articles')").fetchall()}
        assert "openalex_id" in cols
