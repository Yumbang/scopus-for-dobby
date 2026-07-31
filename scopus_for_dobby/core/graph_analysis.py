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


def seed_citation_counts(graph: dict) -> Counter:
    """How many seeds cite each work, computed from the edge list.

    Deliberately derived rather than read from ``seed_reached_by``: graphs
    exported before that field existed would otherwise fall back to
    ``reached_by``, which counts expanded nodes too. On a real depth-2 graph
    that reported EPR as cited by 148 of the user's papers when the true figure
    was 38 — and a label reading "148 of your papers" is worse than the vague
    number it replaced. The edges are always present, so this is always exact.
    """
    seeds = {s for s, n in graph["nodes"].items() if n.get("role") == ROLE_SEED}
    counts: Counter = Counter()
    for src, dst in graph["edges"]:
        if src in seeds:
            counts[dst] += 1
    return counts


def seeds_without_references(graph: dict) -> list[str]:
    """Seeds carrying no reference data at all.

    OpenAlex simply has no reference list for some works. Those seeds enter
    the graph and are counted in every total, but contribute nothing to
    coupling, co-citation or gap papers — so every reference-based figure is
    really over this smaller denominator. On a real 273-seed corpus this was
    47 papers, and nothing in the output revealed it.
    """
    refs = _references_of(graph)
    return sorted(
        s
        for s, n in graph["nodes"].items()
        if n.get("role") == ROLE_SEED and not refs.get(s)
    )


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

    The most actionable output here, and the one least sensitive to topology.
    Ranked on ``seed_reached_by`` — how many of *your* papers cite it — not on
    ``reached_by``, which also counts expanded nodes and therefore overstates
    corpus interest at depth ≥2 (EPR: 148 vs 38 on a real corpus).
    ``cited_by_count`` is OpenAlex's own figure, complete regardless of how far
    we expanded. High on both, absent from your library → read it next.
    """
    known = {d for d in (normalize_doi(x) for x in known_dois) if d}
    seed_counts = seed_citation_counts(graph)
    out = []
    for sid, node in graph["nodes"].items():
        if node.get("is_seed"):
            continue
        doi = normalize_doi(node.get("doi"))
        if doi and doi in known:
            continue
        reached = node.get("reached_by", 0)
        seed_reached = seed_counts.get(sid, 0)
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
                "seed_reached_by": seed_reached,
                "role": node.get("role"),
            }
        )
    # Corroboration first: a paper five of your seeds cite matters more than a
    # famous one only one cites.
    out.sort(key=lambda r: (-r["seed_reached_by"], -r["cited_by_count"], r["id"]))
    return out[:limit]


def outlier_seeds(graph: dict) -> list[dict]:
    """Seeds sharing no references with any other seed.

    Two very different situations reach this list, and conflating them told
    users their papers were off-topic when we simply had no data:

    * ``unrelated`` — the seed has references, none shared. A real signal;
      usually a keyword collision worth pruning.
    * ``no_reference_data`` — OpenAlex holds no reference list for it, so it
      *cannot* share anything. Says nothing about the paper.

    Both are returned, tagged, so the caller can report them separately.
    """
    refs = _references_of(graph)
    seeds = [s for s, n in graph["nodes"].items() if n.get("role") == ROLE_SEED]
    coupled: set[str] = set()
    for a, b in combinations(sorted(s for s in seeds if s in refs), 2):
        if refs[a] & refs[b]:
            coupled.add(a)
            coupled.add(b)
    out = []
    for s in sorted(set(seeds) - coupled):
        count = len(refs.get(s, ()))
        out.append(
            {
                "id": s,
                "label": _label(graph, s),
                "references": count,
                "reason": "unrelated" if count else "no_reference_data",
            }
        )
    return out


def reference_age(graph: dict) -> dict:
    """How backward-looking this corpus is.

    Measured over ``seed -> reference`` edges rather than over nodes, so a work
    ten seeds cite counts ten times — the question is what the corpus *reaches
    for*, not what happens to be in the graph. The classic bibliometric read:
    a recent median means a fast-moving front, a long tail means the field
    still argues with its founding literature.
    """
    years = graph["nodes"]
    # Seed edges only. Expanded nodes are neighbourhood, not corpus — counting
    # their references dilutes the measure with literature the user never
    # collected (on a real graph it moved the median from 2014 to 2006).
    seeds = {s for s, n in graph["nodes"].items() if n.get("role") == ROLE_SEED}
    cited_years = [
        years[dst]["year"]
        for src, dst in graph["edges"]
        if src in seeds and isinstance(years.get(dst, {}).get("year"), int)
    ]
    if not cited_years:
        return {"references_with_year": 0, "median_year": None, "eras": {}, "shares": {}}

    cited_years.sort()
    n = len(cited_years)
    median = cited_years[n // 2] if n % 2 else (cited_years[n // 2 - 1] + cited_years[n // 2]) / 2

    eras = {"pre-1940": 0, "1940-1979": 0, "1980-1999": 0, "2000-2014": 0, "2015+": 0}
    for y in cited_years:
        if y < 1940:
            eras["pre-1940"] += 1
        elif y < 1980:
            eras["1940-1979"] += 1
        elif y < 2000:
            eras["1980-1999"] += 1
        elif y < 2015:
            eras["2000-2014"] += 1
        else:
            eras["2015+"] += 1

    return {
        "references_with_year": n,
        "median_year": median,
        "quartiles": [cited_years[n // 4], median, cited_years[(3 * n) // 4]],
        "eras": eras,
        "shares": {k: round(v / n, 4) for k, v in eras.items()},
    }


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
        # Seeds that matched OpenAlex but carry no reference list. They inflate
        # every seed total while contributing to no reference-based measure, so
        # `seeds_with_references` is the real denominator for those figures.
        "seeds_without_references": len(seeds_without_references(graph)),
        "seeds_with_references": roles[ROLE_SEED] - len(seeds_without_references(graph)),
        "depth": meta.get("depth", 1),
        "truncated": bool(meta.get("truncated")),
        "stopped_before_level": meta.get("stopped_before_level"),
        "openalex_requests": meta.get("requests"),
        "year_range": [min(years), max(years)] if years else None,
    }


# ── Communities (optional networkx) ───────────────────────────────────────────


def theme_composition(graph: dict, members: list[str], *, top: int = 5) -> list[dict]:
    """The references a theme's own papers most share.

    What actually names a cluster. The `representative` list only gives the
    highest-degree members — useful, but "these papers all cite Bell 1964" says
    far more about what a group *is* than any five of its titles.
    """
    refs = _references_of(graph)
    inside = [m for m in members if m in refs]
    counts: Counter = Counter()
    for m in inside:
        counts.update(refs[m])
    return [
        {
            "id": rid,
            "label": _label(graph, rid),
            "cited_by_members": count,
            "share": round(count / len(inside), 4) if inside else 0.0,
        }
        for rid, count in counts.most_common(top)
    ]


def communities(
    pairs: list[dict],
    *,
    resolution: float = 1.0,
    seed: int = 7,
    graph: dict | None = None,
    top: int = 5,
) -> list[dict]:
    """Cluster a projection into themes.

    Deliberately takes a *projection* (coupling or co-citation pairs), never
    the raw citation graph: a star has no community structure to find, so
    running this on the raw graph would invent groupings.

    Pass ``graph`` to attach each theme's most-shared references and labelled
    members. Member lists are bounded by ``top`` — a large theme is hundreds of
    bare IDs, which is unreadable and drowns the useful part of a JSON report.
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
        theme = {
            "id": i,
            "size": len(members),
            "members": [
                {"id": m, "label": labels.get(m, m)} for m in ranked[:top]
            ],
            "members_truncated": max(0, len(members) - top),
            "representative": [
                {"id": m, "label": labels.get(m, m)} for m in ranked[:5]
            ],
            "modularity": round(modularity, 4),
        }
        if graph is not None:
            theme["top_shared_references"] = theme_composition(graph, list(members), top=top)
        out.append(theme)
    return out
