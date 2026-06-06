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
from pathlib import Path
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


def oa_get(path: str, params: dict | None = None) -> dict:
    """GET an OpenAlex endpoint and return the parsed JSON.

    Raises RuntimeError with a sanitized message on failure — response
    bodies go to the debug log only, mirroring ``api_client.api_get``.
    """
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


def build_citation_graph(
    seeds: list[dict],
    *,
    direction: str = "both",
    per_seed_limit: int = 200,
    on_progress=None,
) -> dict:
    """Build a citation graph around ``seeds`` (local article dicts with DOIs).

    Nodes are OpenAlex works; a directed edge A → B means "A cites B".
    ``direction``: ``references`` (what seeds cite), ``cited-by`` (what
    cites seeds), or ``both``. Returns ``{"nodes": {short_id: attrs},
    "edges": [(src, dst), ...], "unmatched": [seed eids]}`` — held fully
    in memory, never written to DuckDB.
    """
    seed_by_doi: dict[str, dict] = {}
    for s in seeds:
        d = normalize_doi(s.get("doi"))
        if d:
            seed_by_doi[d] = s
    works = fetch_works_by_dois(seed_by_doi.keys(), select=_GRAPH_SELECT + ",referenced_works")
    unmatched = [seed_by_doi[d].get("eid", d) for d in seed_by_doi if d not in works]

    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()

    def _add_node(work: dict, *, is_seed: bool = False) -> str | None:
        sid = _short_id(work.get("id"))
        if not sid:
            return None
        existing = nodes.get(sid)
        if existing:
            existing["is_seed"] = existing["is_seed"] or is_seed
            return sid
        nodes[sid] = {
            "id": sid,
            "label": work.get("display_name") or "",
            "year": work.get("publication_year"),
            "doi": normalize_doi(work.get("doi")) or "",
            "cited_by_count": work.get("cited_by_count") or 0,
            "is_seed": is_seed,
        }
        return sid

    seed_works: dict[str, dict] = {}
    for work in works.values():
        sid = _add_node(work, is_seed=True)
        if sid:
            seed_works[sid] = work

    refs_to_resolve: set[str] = set()
    for done, (sid, work) in enumerate(seed_works.items(), 1):
        if direction in ("references", "both"):
            refs = [r for r in (_short_id(x) for x in work.get("referenced_works") or []) if r]
            for ref in refs[:per_seed_limit]:
                edges.add((sid, ref))
                if ref not in nodes:
                    refs_to_resolve.add(ref)
        if direction in ("cited-by", "both"):
            for citer in fetch_citing_works(sid, limit=per_seed_limit):
                cid = _add_node(citer)
                if cid:
                    edges.add((cid, sid))
        if on_progress:
            on_progress(done, len(seed_works))

    # Referenced works are listed by ID only — resolve their metadata in
    # batches. Works OpenAlex has deleted/merged keep a stub node so the
    # edge list stays consistent.
    if refs_to_resolve:
        for work in fetch_works_by_ids(refs_to_resolve).values():
            _add_node(work)
        for missing in refs_to_resolve - set(nodes):
            nodes[missing] = {
                "id": missing,
                "label": missing,
                "year": None,
                "doi": "",
                "cited_by_count": 0,
                "is_seed": False,
            }

    return {"nodes": nodes, "edges": sorted(edges), "unmatched": unmatched}


# ── Graph writers ─────────────────────────────────────────────────────────────


def write_graphml(graph: dict, path: str | Path) -> list[str]:
    """Write the graph as directed GraphML (Gephi/Cytoscape/networkx)."""
    path = Path(path)
    keys = [
        ("label", "string"),
        ("year", "int"),
        ("doi", "string"),
        ("cited_by_count", "int"),
        ("is_seed", "boolean"),
    ]
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
    with open(nodes_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Gephi expects an ``Id``/``Label`` header on the nodes table.
        writer.writerow(["Id", "Label", "year", "doi", "cited_by_count", "is_seed"])
        for sid, attrs in sorted(graph["nodes"].items()):
            writer.writerow(
                [
                    sid,
                    attrs.get("label", ""),
                    attrs.get("year") or "",
                    attrs.get("doi", ""),
                    attrs.get("cited_by_count", 0),
                    attrs.get("is_seed", False),
                ]
            )
    with open(edges_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Target"])
        writer.writerows(graph["edges"])
    return [str(nodes_path), str(edges_path)]


def write_json(graph: dict, path: str | Path) -> list[str]:
    """Write node-link JSON loadable via ``networkx.node_link_graph``."""
    path = Path(path)
    payload = {
        "directed": True,
        "multigraph": False,
        "graph": {},
        "nodes": [dict(attrs) for _, attrs in sorted(graph["nodes"].items())],
        "links": [{"source": s, "target": t} for s, t in graph["edges"]],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return [str(path)]


GRAPH_WRITERS = {"graphml": write_graphml, "csv": write_csv, "json": write_json}
