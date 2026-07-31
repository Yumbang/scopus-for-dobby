"""Read a citation graph and say something useful about it.

The point is not a picture. It is answering three questions about a set of
search results: *what did this actually find*, *what did it miss*, and *what
should be read next*.

**Everything here is constrained by graph topology, and that is the whole
difficulty.** A depth-1 graph is a star: edges run only seed → reference and
citer → seed, with none among non-seed nodes. On a star, every path is at most
two hops, so betweenness concentrates on the seeds by construction and PageRank
merely re-reads the seed set. Running those measures anyway produces confident
noise, which is worse than producing nothing.

Two rules follow, and the functions below enforce them:

1. **Structural measures may only see ``seed`` and ``expanded`` nodes.** A
   ``frontier`` node was never expanded, so its missing edges are an artefact
   of where we stopped, not a fact about the literature.
2. **Attribute-based ranking may see every node.** ``cited_by_count`` comes
   from OpenAlex and is complete regardless of expansion — which is exactly why
   gap detection, the most useful output here, works at any depth.

Projections (coupling, co-citation) are what make the graph analysable: they
turn a star into a network that genuinely has structure to find.

Pure functions over the graph dict. No I/O, no DuckDB, no third-party imports
except the optional networkx used for community detection.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from scopus_for_dobby.core.openalex import (
    ROLE_EXPANDED,
    ROLE_FRONTIER,
    ROLE_SEED,
    normalize_doi,
)

#: Roles whose out-edges are complete enough for structural measures.
COMPLETE_ROLES = (ROLE_SEED, ROLE_EXPANDED)


class AnalysisUnsupported(ValueError):
    """The graph's shape cannot support the requested analysis."""


# ── Helpers ───────────────────────────────────────────────────────────────────


def _complete_nodes(graph: dict) -> set[str]:
    return {s for s, n in graph["nodes"].items() if n.get("role") in COMPLETE_ROLES}


def _references_of(graph: dict) -> dict[str, set[str]]:
    """``{node: set(referenced nodes)}`` for nodes with complete out-edges."""
    complete = _complete_nodes(graph)
    refs: dict[str, set[str]] = defaultdict(set)
    for src, dst in graph["edges"]:
        if src in complete:
            refs[src].add(dst)
    return refs


def _label(graph: dict, sid: str) -> str:
    return graph["nodes"].get(sid, {}).get("label") or sid


def describe_topology(graph: dict) -> dict:
    """Which analyses this particular graph supports, and why.

    Returned rather than raised so a caller can report the limitation instead
    of failing — a `-d cited-by` graph is a legitimate graph, it just cannot
    answer coupling questions.
    """
    nodes = graph["nodes"]
    roles = Counter(n.get("role", ROLE_FRONTIER) for n in nodes.values())
    meta = graph.get("meta") or {}
    depth = meta.get("depth", 1)
    refs = _references_of(graph)
    has_out_edges = any(refs.values())
    n_complete = roles[ROLE_SEED] + roles[ROLE_EXPANDED]

    reasons = {}
    if not has_out_edges:
        reasons["coupling"] = (
            "This graph has no reference edges — it was built with "
            "-d cited-by. Rebuild with -d references or -d both."
        )
        reasons["co_citation"] = reasons["coupling"]
    elif n_complete < 2:
        reasons["coupling"] = "Needs at least 2 papers with complete references."
        reasons["co_citation"] = reasons["coupling"]

    if depth < 2:
        reasons["centrality"] = (
            "A depth-1 graph is a star: every path is at most 2 hops, so "
            "centrality reflects the shape, not the literature. Use --depth 2 "
            "or read the coupling/co-citation projections instead."
        )
    else:
        reasons["centrality"] = (
            "Frontier nodes have truncated edges, so centrality remains biased "
            "toward the expanded core. Prefer the projections."
        )

    return {
        "depth": depth,
        "direction": meta.get("direction"),
        "roles": dict(roles),
        "complete_nodes": n_complete,
        "truncated": bool(meta.get("truncated")),
        "supports": {
            "coupling": "coupling" not in reasons,
            "co_citation": "co_citation" not in reasons,
            "gap_papers": True,
            "centrality": False,
        },
        "reasons": reasons,
    }


# ── Projections ───────────────────────────────────────────────────────────────


def bibliographic_coupling(graph: dict, *, min_shared: int = 1) -> list[dict]:
    """Papers linked by the references they share — *current research fronts*.

    Two papers are coupled when they cite the same earlier work; the more they
    share, the more likely they address the same problem. Computed only over
    nodes with complete out-edges, since a truncated reference list would
    understate every pair it touches.
    """
    refs = _references_of(graph)
    pairs = []
    for a, b in combinations(sorted(refs), 2):
        shared = refs[a] & refs[b]
        if len(shared) >= min_shared:
            pairs.append(
                {
                    "source": a,
                    "target": b,
                    "source_label": _label(graph, a),
                    "target_label": _label(graph, b),
                    "shared": len(shared),
                    "shared_ids": sorted(shared),
                }
            )
    pairs.sort(key=lambda p: (-p["shared"], p["source"], p["target"]))
    return pairs


def co_citation(graph: dict, *, min_shared: int = 2) -> list[dict]:
    """References that our papers cite together — the *intellectual base*.

    The mirror of coupling: instead of asking which of our papers look alike,
    it asks which older works our corpus keeps reaching for as a set.
    """
    refs = _references_of(graph)
    citers: dict[str, set[str]] = defaultdict(set)
    for citer, cited in refs.items():
        for target in cited:
            citers[target].add(citer)

    pairs = []
    for a, b in combinations(sorted(citers), 2):
        shared = citers[a] & citers[b]
        if len(shared) >= min_shared:
            pairs.append(
                {
                    "source": a,
                    "target": b,
                    "source_label": _label(graph, a),
                    "target_label": _label(graph, b),
                    "shared": len(shared),
                }
            )
    pairs.sort(key=lambda p: (-p["shared"], p["source"], p["target"]))
    return pairs


# ── Findings ──────────────────────────────────────────────────────────────────


def gap_papers(graph: dict, known_dois=(), *, limit: int = 20) -> list[dict]:
    """Works the corpus repeatedly cites but does not contain.

    The most actionable output here, and the one least sensitive to topology:
    ``reached_by`` says how much of your own library points at a paper, and
    ``cited_by_count`` is OpenAlex's own figure, complete regardless of how far
    we expanded. High on both, absent from your library → read it next.
    """
    known = {d for d in (normalize_doi(x) for x in known_dois) if d}
    out = []
    for sid, node in graph["nodes"].items():
        if node.get("is_seed"):
            continue
        doi = normalize_doi(node.get("doi"))
        if doi and doi in known:
            continue
        reached = node.get("reached_by", 0)
        if reached < 1:
            continue
        # Works OpenAlex no longer returns (deleted or merged) survive as stubs
        # labelled with their own ID, to keep the edge list consistent. They
        # are real nodes but nothing a reader could go and find, so they have
        # no place in a "read these next" list.
        if not doi and (node.get("label") or sid) == sid:
            continue
        out.append(
            {
                "id": sid,
                "label": node.get("label") or sid,
                "year": node.get("year"),
                "doi": doi or "",
                "cited_by_count": node.get("cited_by_count") or 0,
                "reached_by": reached,
                "role": node.get("role"),
            }
        )
    # Corroboration first: a paper five of your seeds cite matters more than a
    # famous one only one cites.
    out.sort(key=lambda r: (-r["reached_by"], -r["cited_by_count"], r["id"]))
    return out[:limit]


def outlier_seeds(graph: dict) -> list[dict]:
    """Seeds sharing no references with any other seed.

    Usually a sign the search returned something off-topic — worth pruning
    before the collection is used for anything else.
    """
    refs = _references_of(graph)
    seeds = [s for s, n in graph["nodes"].items() if n.get("role") == ROLE_SEED]
    coupled: set[str] = set()
    for a, b in combinations(sorted(s for s in seeds if s in refs), 2):
        if refs[a] & refs[b]:
            coupled.add(a)
            coupled.add(b)
    return [
        {
            "id": s,
            "label": _label(graph, s),
            "references": len(refs.get(s, ())),
        }
        for s in sorted(set(seeds) - coupled)
    ]


def corpus_stats(graph: dict) -> dict:
    """Coverage and shape — read this before trusting anything else."""
    nodes = graph["nodes"]
    roles = Counter(n.get("role", ROLE_FRONTIER) for n in nodes.values())
    years = [n["year"] for n in nodes.values() if isinstance(n.get("year"), int)]
    meta = graph.get("meta") or {}
    return {
        "nodes": len(nodes),
        "edges": len(graph["edges"]),
        "seeds": roles[ROLE_SEED],
        "expanded": roles[ROLE_EXPANDED],
        "frontier": roles[ROLE_FRONTIER],
        "unmatched_seeds": list(graph.get("unmatched") or []),
        "depth": meta.get("depth", 1),
        "truncated": bool(meta.get("truncated")),
        "year_range": [min(years), max(years)] if years else None,
    }


# ── Communities (optional networkx) ───────────────────────────────────────────


def communities(pairs: list[dict], *, resolution: float = 1.0, seed: int = 7) -> list[dict]:
    """Cluster a projection into themes.

    Deliberately takes a *projection* (coupling or co-citation pairs), never
    the raw citation graph: a star has no community structure to find, so
    running this on the raw graph would invent groupings.
    """
    # Nothing to cluster is not a dependency problem — answer before importing.
    if not pairs:
        return []

    try:
        import networkx as nx
    except ImportError as e:
        raise AnalysisUnsupported(
            "Community detection needs the optional [analysis] extra. "
            "Install it with: uv tool install --reinstall --editable '.[analysis]'"
        ) from e

    g = nx.Graph()
    for pair in pairs:
        g.add_edge(pair["source"], pair["target"], weight=pair["shared"])

    labels = {}
    for pair in pairs:
        labels[pair["source"]] = pair.get("source_label", pair["source"])
        labels[pair["target"]] = pair.get("target_label", pair["target"])

    found = nx.community.louvain_communities(g, weight="weight", resolution=resolution, seed=seed)
    modularity = nx.community.modularity(g, found, weight="weight")

    out = []
    for i, members in enumerate(sorted(found, key=len, reverse=True), 1):
        ranked = sorted(members, key=lambda m: -g.degree(m, weight="weight"))
        out.append(
            {
                "id": i,
                "size": len(members),
                "members": sorted(members),
                "representative": [
                    {"id": m, "label": labels.get(m, m)} for m in ranked[:5]
                ],
                "modularity": round(modularity, 4),
            }
        )
    return out
