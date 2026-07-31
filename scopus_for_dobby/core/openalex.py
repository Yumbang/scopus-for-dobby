"""OpenAlex API client — DOI enrichment and citation graphs.

All OpenAlex REST calls go through this module. OpenAlex
(https://docs.openalex.org) is free and keyless; an optional
``openalex_email`` in config.json joins the polite pool for faster,
more reliable service. Limits: 100k requests/day, max 10 req/s.

Citation graphs are never persisted to DuckDB — they are built in
memory and written out as GraphML / CSV / node-link JSON for tools
like Gephi, Cytoscape, and networkx.

Base URL: https://api.openalex.org
"""

from __future__ import annotations

import csv
import json
import logging
import time
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

import requests

from scopus_for_dobby.utils.api_client import load_config, save_config

logger = logging.getLogger(__name__)

BASE_URL = "https://api.openalex.org"

# OpenAlex allows 10 req/s; stay just under it.
_THROTTLE_INTERVAL = 0.11
_last_call = 0.0

# OpenAlex OR-filters accept at most 50 values per filter.
_BATCH = 50

# OpenAlex caps per-page at 200.
_MAX_PER_PAGE = 200

# Trimmed field set for graph neighbours — keeps responses small.
_GRAPH_SELECT = "id,display_name,publication_year,doi,cited_by_count"


# ── Polite pool ───────────────────────────────────────────────────────────────


def get_polite_email() -> str | None:
    """Email registered for the OpenAlex polite pool, or None."""
    return load_config().get("openalex_email") or None


def set_polite_email(email: str) -> None:
    """Persist the polite-pool email to config.json."""
    config = load_config()
    config["openalex_email"] = email
    save_config(config)


# ── HTTP ──────────────────────────────────────────────────────────────────────


def _throttle():
    global _last_call
    wait = _THROTTLE_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


#: Every OpenAlex request this process has made. Commands report it so the
#: cost of a run is visible: without it neither the user nor an agent can say
#: what a graph build spent, or budget against it mid-run.
_request_count = 0


def request_count() -> int:
    return _request_count


def oa_get(path: str, params: dict | None = None) -> dict:
    """GET an OpenAlex endpoint and return the parsed JSON.

    Raises RuntimeError with a sanitized message on failure — response
    bodies go to the debug log only, mirroring ``api_client.api_get``.
    """
    global _request_count
    _request_count += 1
    params = dict(params or {})
    email = get_polite_email()
    if email:
        params["mailto"] = email
    _throttle()
    resp = requests.get(f"{BASE_URL}{path}", params=params, timeout=30)
    if resp.status_code == 200:
        return resp.json()
    logger.debug("OpenAlex error body for %s: %s", path, resp.text[:500])
    reason = resp.reason or "error"
    raise RuntimeError(f"OpenAlex error: HTTP {resp.status_code} on {path} ({reason}).")


# ── Identifiers ───────────────────────────────────────────────────────────────


def normalize_doi(doi: str | None) -> str | None:
    """Lowercase a DOI and strip URL/scheme prefixes; None for empty input."""
    if not doi:
        return None
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi or None


def _short_id(openalex_url: str | None) -> str | None:
    """``https://openalex.org/W123`` → ``W123``."""
    if not openalex_url:
        return None
    return openalex_url.rsplit("/", 1)[-1]


# ── Works ─────────────────────────────────────────────────────────────────────


def fetch_works_by_dois(dois, *, select: str | None = None, on_progress=None) -> dict[str, dict]:
    """Fetch works for the given DOIs in OR-filter batches of 50.

    Returns ``{normalized_doi: work}``; DOIs unknown to OpenAlex are
    simply absent from the result.
    """
    todo = sorted({d for d in (normalize_doi(x) for x in dois) if d})
    found: dict[str, dict] = {}
    for i in range(0, len(todo), _BATCH):
        chunk = todo[i : i + _BATCH]
        params: dict = {"filter": "doi:" + "|".join(chunk), "per-page": _BATCH}
        if select:
            params["select"] = select
        resp = oa_get("/works", params)
        for work in resp.get("results", []):
            doi = normalize_doi(work.get("doi"))
            if doi:
                found[doi] = work
        if on_progress:
            on_progress(min(i + _BATCH, len(todo)), len(todo))
    return found


def fetch_works_by_ids(ids, *, select: str = _GRAPH_SELECT) -> dict[str, dict]:
    """Fetch works by short OpenAlex IDs (``W...``). Returns ``{short_id: work}``."""
    todo = sorted({i for i in ids if i})
    found: dict[str, dict] = {}
    for i in range(0, len(todo), _BATCH):
        chunk = todo[i : i + _BATCH]
        resp = oa_get(
            "/works",
            {"filter": "openalex:" + "|".join(chunk), "per-page": _BATCH, "select": select},
        )
        for work in resp.get("results", []):
            sid = _short_id(work.get("id"))
            if sid:
                found[sid] = work
    return found


def fetch_citing_works(openalex_id: str, *, limit: int = 200) -> list[dict]:
    """Works that cite ``openalex_id``, cursor-paginated up to ``limit``."""
    out: list[dict] = []
    cursor = "*"
    while cursor and len(out) < limit:
        resp = oa_get(
            "/works",
            {
                "filter": f"cites:{openalex_id}",
                "per-page": min(_MAX_PER_PAGE, limit - len(out)),
                "cursor": cursor,
                "select": _GRAPH_SELECT,
            },
        )
        results = resp.get("results", [])
        if not results:
            break
        out.extend(results)
        cursor = (resp.get("meta") or {}).get("next_cursor")
    return out[:limit]


# ── Enrichment ────────────────────────────────────────────────────────────────


def normalize_enrichment(work: dict) -> dict:
    """Reduce a full OpenAlex work to the fields stored on an article row."""
    oa = work.get("open_access") or {}
    best = work.get("best_oa_location") or {}
    topics: list[str] = []
    primary = (work.get("primary_topic") or {}).get("display_name")
    if primary:
        topics.append(primary)
    for t in work.get("topics") or []:
        name = t.get("display_name")
        if name and name not in topics:
            topics.append(name)
    return {
        "doi": normalize_doi(work.get("doi")),
        "openalex_id": _short_id(work.get("id")) or "",
        "oa_status": oa.get("oa_status") or "",
        "oa_url": best.get("pdf_url") or best.get("landing_page_url") or oa.get("oa_url") or "",
        "cited_by_count": work.get("cited_by_count") or 0,
        "topics": topics[:5],
    }


# ── Citation graph ────────────────────────────────────────────────────────────


#: Node roles. ``frontier`` nodes were never expanded, so their edge lists are
#: truncated by where we stopped — structural metrics must exclude them.
ROLE_SEED = "seed"
ROLE_EXPANDED = "expanded"
ROLE_FRONTIER = "frontier"

MAX_DEPTH = 3
DEFAULT_MAX_NODES = 5000
DEFAULT_MIN_REACHED = 2

#: Depth-1 size scales with the corpus: works carry ~19-50 references each, so
#: a fixed 5000 caps out around 270 seeds. Larger corpora would spend their
#: whole budget before finishing level 1. The default now grows with the seed
#: count; an explicit --max-nodes always wins.
NODES_PER_SEED = 25

#: Extra OpenAlex fields callers can request on nodes. Author data is opt-in,
#: not default: it answers a whole class of person-level question ("does this
#: corpus still cite Bohr") that the graph otherwise cannot, but it materially
#: enlarges every response payload, and most graph work never needs it.
NODE_FIELD_SETS = {"authorships": "authorships"}


def default_max_nodes(seed_count: int) -> int:
    return max(DEFAULT_MAX_NODES, NODES_PER_SEED * seed_count)


def _wants(direction: str, kind: str) -> bool:
    return direction in (kind, "both")


def build_citation_graph(
    seeds: list[dict],
    *,
    direction: str = "both",
    per_seed_limit: int = 200,
    depth: int = 1,
    min_reached: int = DEFAULT_MIN_REACHED,
    max_nodes: int | None = None,
    deep_direction: str = "references",
    node_fields: tuple[str, ...] = (),
    on_progress=None,
) -> dict:
    """Build a citation graph around ``seeds`` (local article dicts with DOIs).

    Nodes are OpenAlex works; a directed edge A → B means "A cites B".

    ``depth`` (1–3) controls how far the neighbourhood is expanded. Depth 1 is
    the seeds' immediate references/citers — a star, with no edges among
    non-seed nodes. Beyond that, expansion is **relevance-gated**: a node is
    expanded at the next level only when at least ``min_reached`` papers we
    already hold point at it. Without that gate the frontier grows by ~35× per
    level (millions of nodes by depth 3); with it, the graph stays on-topic and
    the gate count doubles as the "this matters to your corpus" signal.

    ``deep_direction`` applies to levels beyond the first, defaulting to
    references only: citers cost one paginated request *per node*, while
    references arrive 50 at a time.

    Every node carries ``role`` (seed / expanded / frontier), ``depth``, and
    ``reached_by``. Frontier nodes have deliberately incomplete edges.

    Returns ``{"nodes": {short_id: attrs}, "edges": [(src, dst), ...],
    "unmatched": [...], "meta": {...}}`` — held in memory, never written to
    DuckDB.
    """
    depth = max(1, min(int(depth), MAX_DEPTH))

    seed_by_doi: dict[str, dict] = {}
    for s in seeds:
        d = normalize_doi(s.get("doi"))
        if d:
            seed_by_doi[d] = s

    if max_nodes is None:
        max_nodes = default_max_nodes(len(seed_by_doi))

    extra = [NODE_FIELD_SETS[f] for f in node_fields if f in NODE_FIELD_SETS]
    node_select = ",".join([_GRAPH_SELECT, *extra])

    requests_before = request_count()
    works = fetch_works_by_dois(seed_by_doi.keys(), select=node_select + ",referenced_works")
    unmatched = [seed_by_doi[d].get("eid", d) for d in seed_by_doi if d not in works]

    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    reached: dict[str, set[str]] = {}
    refs_cache: dict[str, list[str]] = {}
    expanded: set[str] = set()
    truncated = False
    stopped_before_level: int | None = None

    def _stub(sid: str, level: int) -> dict:
        return {
            "id": sid,
            "label": sid,
            "year": None,
            "doi": "",
            "cited_by_count": 0,
            "is_seed": False,
            "role": ROLE_FRONTIER,
            "depth": level,
            "reached_by": 0,
        }

    def _fill(sid: str, work: dict) -> None:
        node = nodes[sid]
        node["label"] = work.get("display_name") or node["label"]
        node["year"] = work.get("publication_year")
        node["doi"] = normalize_doi(work.get("doi")) or ""
        node["cited_by_count"] = work.get("cited_by_count") or 0
        if "authorships" in extra:
            names = [
                (a.get("author") or {}).get("display_name", "")
                for a in work.get("authorships") or []
            ]
            names = [n for n in names if n]
            node["authors"] = names
            node["first_author"] = names[0] if names else ""

    def _touch(sid: str, level: int, by: str | None = None) -> None:
        if sid not in nodes:
            nodes[sid] = _stub(sid, level)
        if by:
            reached.setdefault(sid, set()).add(by)

    def _cache_refs(sid: str, work: dict) -> None:
        refs_cache[sid] = [
            r for r in (_short_id(x) for x in work.get("referenced_works") or []) if r
        ]

    # ── depth 0: the user's batch ────────────────────────────────────────────
    for work in works.values():
        sid = _short_id(work.get("id"))
        if not sid:
            continue
        _touch(sid, 0)
        _fill(sid, work)
        nodes[sid].update({"is_seed": True, "role": ROLE_SEED, "depth": 0})
        _cache_refs(sid, work)

    # ── levels 1..depth ──────────────────────────────────────────────────────
    #
    # The node budget is checked BETWEEN levels, never inside one. Breaking
    # mid-level used to abandon the seeds later in the iteration order, and
    # those seeds kept ``role: seed`` — which the analysis layer reads as
    # "this node's reference list is complete". So a truncated graph silently
    # computed coupling, co-citation and outliers over papers whose references
    # were never fetched, and then told the user they looked off-topic.
    # Levels are now atomic: either every node in a level is expanded or the
    # level does not start, so a role always means what it says.
    for level in range(1, depth + 1):
        if level == 1:
            # Seeds are the user's own selection — no gate applies to them,
            # and the budget never blocks them. The cap governs expansion
            # *beyond* the corpus; refusing to process the input the user
            # explicitly chose would be the wrong kind of thrift.
            to_expand = [s for s, n in nodes.items() if n["depth"] == 0]
        elif len(nodes) >= max_nodes:
            truncated = True
            stopped_before_level = level
            break
        else:
            # Any node the corpus has corroborated and that we have not
            # expanded yet — deliberately NOT restricted to nodes first seen at
            # the previous level. A paper can be seen once at depth 1 and only
            # become corroborated when a depth-2 node also cites it; keying on
            # first-seen depth would skip it forever.
            to_expand = [
                s
                for s in nodes
                if s not in expanded and len(reached.get(s, ())) >= min_reached
            ]
        if not to_expand:
            break

        level_direction = direction if level == 1 else deep_direction
        pending_meta: set[str] = set()

        for done, sid in enumerate(to_expand, 1):
            if _wants(level_direction, "references"):
                for ref in refs_cache.get(sid, [])[:per_seed_limit]:
                    edges.add((sid, ref))
                    _touch(ref, level, by=sid)
                    if ref not in expanded and not nodes[ref].get("_filled"):
                        pending_meta.add(ref)
            if _wants(level_direction, "cited-by"):
                for citer in fetch_citing_works(sid, limit=per_seed_limit):
                    cid = _short_id(citer.get("id"))
                    if not cid:
                        continue
                    _touch(cid, level, by=sid)
                    _fill(cid, citer)
                    nodes[cid]["_filled"] = True
                    edges.add((cid, sid))

            expanded.add(sid)
            if nodes[sid]["role"] != ROLE_SEED:
                nodes[sid]["role"] = ROLE_EXPANDED
            if on_progress:
                on_progress(done, len(to_expand))

        # Referenced works arrive as bare IDs — resolve metadata in batches.
        # Pull `referenced_works` too when another level might expand them.
        if pending_meta:
            select = node_select + (",referenced_works" if level < depth else "")
            for sid, work in fetch_works_by_ids(pending_meta, select=select).items():
                if sid in nodes:
                    _fill(sid, work)
                    nodes[sid]["_filled"] = True
                    if level < depth:
                        _cache_refs(sid, work)

    # ``reached_by`` counts every expanding node that points at a work, which is
    # the right signal for the relevance gate but NOT the question a reader
    # asks of a gap paper. "How much of *my library* cites this" is seed-only,
    # and the two diverge sharply with depth — on a real 273-seed corpus, EPR
    # showed reached_by 148 against 38 actual seed citations. Emit both.
    seed_ids = {s for s, n in nodes.items() if n["role"] == ROLE_SEED}
    seed_citations: Counter = Counter()
    for src, dst in edges:
        if src in seed_ids:
            seed_citations[dst] += 1

    for sid, node in nodes.items():
        node["reached_by"] = len(reached.get(sid, ()))
        node["seed_reached_by"] = seed_citations.get(sid, 0)
        node.pop("_filled", None)

    roles = Counter(n["role"] for n in nodes.values())
    return {
        "nodes": nodes,
        "edges": sorted(edges),
        "unmatched": unmatched,
        "meta": {
            "depth": depth,
            "direction": direction,
            "deep_direction": deep_direction if depth > 1 else None,
            "min_reached": min_reached,
            "per_seed_limit": per_seed_limit,
            "max_nodes": max_nodes,
            "truncated": truncated,
            "stopped_before_level": stopped_before_level,
            "node_fields": list(node_fields),
            "requests": request_count() - requests_before,
            "roles": dict(roles),
        },
    }


def plan_expansion(graph: dict, *, depth: int, min_reached: int = DEFAULT_MIN_REACHED) -> dict:
    """Project the cost of expanding ``graph`` further, without fetching.

    Honest about its limits: the level immediately after the graph's current
    depth is counted exactly (those nodes and their reach are known), and
    anything past that is a projection using the observed average fan-out.
    """
    nodes = graph["nodes"]
    current = graph.get("meta", {}).get("depth", 1)
    refs_per_node = _avg_fanout(graph)

    gated = [
        s
        for s, n in nodes.items()
        if n["depth"] == current and n["role"] == ROLE_FRONTIER and n["reached_by"] >= min_reached
    ]
    levels = []
    projected_nodes = len(nodes)
    expanding = len(gated)
    for level in range(current + 1, depth + 1):
        new_nodes = int(expanding * refs_per_node)
        levels.append(
            {
                "level": level,
                "expanding": expanding,
                "estimated_new_nodes": new_nodes,
                "estimated_requests": -(-expanding * int(refs_per_node) // _BATCH) or 1,
                "exact": level == current + 1,
            }
        )
        projected_nodes += new_nodes
        # Past the first projected level, assume the same share clears the gate.
        expanding = max(1, int(new_nodes * (len(gated) / max(len(nodes), 1))))
    return {
        "current_depth": current,
        "current_nodes": len(nodes),
        "target_depth": depth,
        "avg_references_per_node": round(refs_per_node, 1),
        "levels": levels,
        "projected_total_nodes": projected_nodes,
    }


def _avg_fanout(graph: dict) -> float:
    """Mean out-degree over nodes that were actually expanded."""
    expanded = {s for s, n in graph["nodes"].items() if n["role"] in (ROLE_SEED, ROLE_EXPANDED)}
    if not expanded:
        return 0.0
    out = Counter(s for s, _ in graph["edges"] if s in expanded)
    return sum(out.values()) / len(expanded) if out else 0.0


# ── Graph writers ─────────────────────────────────────────────────────────────


#: Node attributes written to every format, in order. ``is_seed`` predates
#: roles and is kept so existing Gephi workflows and older exports still work.
NODE_KEYS: tuple[tuple[str, str], ...] = (
    ("label", "string"),
    ("year", "int"),
    ("doi", "string"),
    ("cited_by_count", "int"),
    ("is_seed", "boolean"),
    ("role", "string"),
    ("depth", "int"),
    ("reached_by", "int"),
)


def write_graphml(graph: dict, path: str | Path) -> list[str]:
    """Write the graph as directed GraphML (Gephi/Cytoscape/networkx)."""
    path = Path(path)
    keys = list(NODE_KEYS)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    ]
    for name, typ in keys:
        lines.append(f'  <key id="{name}" for="node" attr.name="{name}" attr.type="{typ}"/>')
    lines.append('  <graph id="citations" edgedefault="directed">')
    for sid, attrs in sorted(graph["nodes"].items()):
        lines.append(f'    <node id="{escape(sid)}">')
        for name, _ in keys:
            value = attrs.get(name)
            if value is None:
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            lines.append(f'      <data key="{name}">{escape(str(value))}</data>')
        lines.append("    </node>")
    for src, dst in graph["edges"]:
        lines.append(f'    <edge source="{escape(src)}" target="{escape(dst)}"/>')
    lines.append("  </graph>")
    lines.append("</graphml>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [str(path)]


def write_csv(graph: dict, path: str | Path) -> list[str]:
    """Write ``<stem>_nodes.csv`` + ``<stem>_edges.csv`` (Gephi import format)."""
    path = Path(path)
    nodes_path = path.with_name(f"{path.stem}_nodes.csv")
    edges_path = path.with_name(f"{path.stem}_edges.csv")
    extra = [name for name, _ in NODE_KEYS if name not in ("label",)]
    with open(nodes_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Gephi expects an ``Id``/``Label`` header on the nodes table.
        writer.writerow(["Id", "Label", *extra])
        for sid, attrs in sorted(graph["nodes"].items()):
            writer.writerow(
                [
                    sid,
                    attrs.get("label", ""),
                    *(attrs.get(name, "") if attrs.get(name) is not None else "" for name in extra),
                ]
            )
    with open(edges_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Target"])
        writer.writerows(graph["edges"])
    return [str(nodes_path), str(edges_path)]


def write_json(graph: dict, path: str | Path) -> list[str]:
    """Write node-link JSON loadable via ``networkx.node_link_graph``.

    The edge list is keyed ``edges``, not the historical ``links``: networkx
    3.6 made ``edges`` the default, so ``node_link_graph(json.load(f))`` — the
    call everyone actually writes — raises ``KeyError: 'edges'`` on a file
    using the old key. ``read_graph`` still accepts either, so graphs exported
    by older versions keep loading.
    """
    path = Path(path)
    payload = {
        "directed": True,
        "multigraph": False,
        "graph": dict(graph.get("meta") or {}),
        "nodes": [dict(attrs) for _, attrs in sorted(graph["nodes"].items())],
        "edges": [{"source": s, "target": t} for s, t in graph["edges"]],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return [str(path)]


GRAPH_WRITERS = {"graphml": write_graphml, "csv": write_csv, "json": write_json}


# ── Graph readers ─────────────────────────────────────────────────────────────
#
# Analysis needs to run on a graph that was exported earlier, otherwise every
# look at the same corpus re-spends API calls.

_INT_KEYS = {"year", "cited_by_count", "depth", "reached_by"}


def _coerce(attrs: dict) -> dict:
    """Restore attribute types lost to text formats."""
    out = dict(attrs)
    for key in _INT_KEYS:
        value = out.get(key)
        if isinstance(value, str):
            out[key] = int(value) if value.strip().lstrip("-").isdigit() else None
    seed = out.get("is_seed")
    if isinstance(seed, str):
        out["is_seed"] = seed.strip().lower() in ("true", "1", "yes")
    out.setdefault("role", ROLE_SEED if out.get("is_seed") else ROLE_FRONTIER)
    out.setdefault("depth", 0 if out.get("is_seed") else 1)
    out.setdefault("reached_by", 0)
    return out


def read_json_graph(path: str | Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = {n["id"]: _coerce(n) for n in payload.get("nodes", [])}
    links = payload.get("links") or payload.get("edges") or []
    edges = sorted((link["source"], link["target"]) for link in links)
    return {"nodes": nodes, "edges": edges, "unmatched": [], "meta": payload.get("graph") or {}}


def read_graphml(path: str | Path) -> dict:
    ns = "{http://graphml.graphdrawing.org/xmlns}"
    # S314: the input is a graph file the user exported locally with
    # `openalex graph`, on a single-user personal tool — not network input.
    # Not worth a defusedxml dependency for one reader; revisit if graphs ever
    # arrive from an untrusted source.
    root = ElementTree.parse(str(path)).getroot()  # noqa: S314
    graph_el = root.find(f"{ns}graph")
    if graph_el is None:
        raise ValueError(f"No <graph> element in {path}")
    nodes: dict[str, dict] = {}
    for node_el in graph_el.findall(f"{ns}node"):
        sid = node_el.get("id")
        attrs = {"id": sid}
        for data in node_el.findall(f"{ns}data"):
            attrs[data.get("key")] = data.text
        nodes[sid] = _coerce(attrs)
    edges = sorted(
        (e.get("source"), e.get("target")) for e in graph_el.findall(f"{ns}edge")
    )
    return {"nodes": nodes, "edges": edges, "unmatched": [], "meta": {}}


GRAPH_READERS = {"graphml": read_graphml, "json": read_json_graph}


def read_graph(path: str | Path) -> dict:
    """Load a graph written by ``GRAPH_WRITERS``, inferring format from suffix.

    The CSV writer emits two files rather than one, so it is export-only;
    round-tripping uses GraphML or JSON.
    """
    path = Path(path)
    suffix = path.suffix.lstrip(".").lower()
    try:
        reader = GRAPH_READERS[suffix]
    except KeyError:
        raise ValueError(
            f"Cannot read {path.name}: expected one of "
            f"{', '.join(sorted(GRAPH_READERS))} (CSV export is write-only)."
        ) from None
    return reader(path)
