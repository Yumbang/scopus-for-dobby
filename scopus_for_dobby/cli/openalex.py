"""OpenAlex subcommands — DOI enrichment and citation-graph export.

Enrichment writes through the daemon into the local DB; citation graphs
are never stored — they are written straight to GraphML/CSV/JSON files.
"""

from pathlib import Path

import click

from scopus_for_dobby.core import openalex as oa

from . import _client as db_mod
from ._output import handle_error, output
from ._state import state

_FORMATS = ("graphml", "csv", "json")

# "Whole DB" for client-side filtering — far above any realistic library size.
_ALL = 100_000


@click.group("openalex")
def openalex():
    """OpenAlex integration (free, keyless) — enrichment and citation graphs."""


@openalex.command("enrich")
@click.option("--collection", "-c", default=None, help="Only articles in this collection")
@click.option("--tag", "-t", default=None, help="Only articles with this tag")
@click.option("--force", is_flag=True, help="Re-enrich articles that already have OpenAlex data")
@click.option("--limit", "-n", type=int, default=None, help="Max articles to enrich")
@handle_error
def oa_enrich(collection, tag, force, limit):
    """Enrich saved articles with OpenAlex data, matched by DOI.

    Pulls open-access status + best OA link (often a free PDF), OpenAlex
    citation counts, and topic labels into the local database.

    \b
    Examples:
      scopus-for-dobby openalex enrich
      scopus-for-dobby openalex enrich --collection thesis --force
    """
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    articles = db_mod.list_articles(tag=tag, collection=collection, limit=_ALL)["articles"]
    no_doi = sum(1 for a in articles if not a.get("doi"))
    candidates = [a for a in articles if a.get("doi") and (force or not a.get("openalex_id"))]
    if limit:
        candidates = candidates[:limit]

    if not candidates:
        msg = "Nothing to enrich"
        if no_doi:
            msg += f" ({no_doi} article(s) have no DOI)"
        if state.json_output:
            output({"enriched": 0, "no_doi": no_doi})
        else:
            skin.warning(msg + ".")
        return

    if not state.json_output:
        skin.info(f"Querying OpenAlex for {len(candidates)} DOI(s)...")

    works = oa.fetch_works_by_dois([a["doi"] for a in candidates])
    by_doi = {oa.normalize_doi(a["doi"]): a for a in candidates}
    enrichments = []
    for doi, work in works.items():
        article = by_doi.get(doi)
        if article:
            enrichments.append({"eid": article["eid"], **oa.normalize_enrichment(work)})
    not_found = len(candidates) - len(enrichments)

    result = db_mod.enrich_articles(enrichments)
    oa_found = sum(1 for e in enrichments if e.get("oa_url"))

    summary = {
        "enriched": result["enriched"],
        "open_access_links": oa_found,
        "not_in_openalex": not_found,
        "no_doi": no_doi,
    }
    if state.json_output:
        output(summary)
        return
    skin.success(f"Enriched {result['enriched']} article(s) — {oa_found} with an open-access link")
    if not_found:
        skin.hint(f"     {not_found} DOI(s) not found in OpenAlex")
    if no_doi:
        skin.hint(f"     {no_doi} article(s) skipped (no DOI)")


@openalex.command("graph")
@click.argument("eids", nargs=-1)
@click.option("--collection", "-c", default=None, help="Seed from all articles in a collection")
@click.option("--tag", "-t", default=None, help="Seed from all articles with a tag")
@click.option(
    "--direction",
    "-d",
    type=click.Choice(["references", "cited-by", "both"]),
    default="both",
    help="references = what seeds cite; cited-by = what cites seeds",
)
@click.option(
    "--per-seed-limit", type=int, default=200, help="Max references/citers fetched per seed"
)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(_FORMATS),
    default=None,
    help="Output format (default: inferred from -o extension, else graphml)",
)
@click.option("--output", "-o", "out_path", default=None, help="Output file path")
@handle_error
def oa_graph(eids, collection, tag, direction, per_seed_limit, fmt, out_path):
    """Export a citation graph around saved articles to a graph file.

    Nodes are works, a directed edge A -> B means "A cites B". The graph
    is NOT stored in the database — it is written to GraphML (Gephi,
    Cytoscape), CSV node/edge tables, or node-link JSON (networkx).

    \b
    Examples:
      scopus-for-dobby openalex graph --collection thesis -o thesis.graphml
      scopus-for-dobby openalex graph 2-s2.0-85... -d cited-by -f csv -o cites.csv
    """
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    if collection or tag:
        seeds = db_mod.list_articles(tag=tag, collection=collection, limit=_ALL)["articles"]
    elif eids:
        seeds = [db_mod.get_article(e) for e in eids]
    else:
        raise click.UsageError("Provide article EIDs, --collection, or --tag to seed the graph.")

    no_doi = [s["eid"] for s in seeds if not s.get("doi")]
    seeds = [s for s in seeds if s.get("doi")]
    if not seeds:
        raise click.ClickException("None of the seed articles have a DOI.")

    # Resolve format and output path from each other.
    if fmt is None and out_path:
        suffix = Path(out_path).suffix.lstrip(".").lower()
        fmt = suffix if suffix in _FORMATS else "graphml"
    fmt = fmt or "graphml"
    out_path = out_path or f"citation_graph.{fmt}"

    if not state.json_output:
        skin.info(
            f"Building {direction} graph from {len(seeds)} seed(s) (limit {per_seed_limit}/seed)..."
        )

    graph = oa.build_citation_graph(seeds, direction=direction, per_seed_limit=per_seed_limit)
    files = oa.GRAPH_WRITERS[fmt](graph, out_path)

    summary = {
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "seeds": len(seeds),
        "seeds_not_in_openalex": graph["unmatched"],
        "seeds_without_doi": no_doi,
        "files": files,
    }
    if state.json_output:
        output(summary)
        return
    skin.success(
        f"Graph written: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges "
        f"-> {', '.join(files)}"
    )
    if graph["unmatched"]:
        skin.hint(f"     {len(graph['unmatched'])} seed(s) not found in OpenAlex")
    if no_doi:
        skin.hint(f"     {len(no_doi)} seed(s) skipped (no DOI)")


@openalex.command("email")
@click.argument("address", required=False)
@handle_error
def oa_email(address):
    """Show or set the polite-pool email (faster, more reliable API access)."""
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    if address:
        oa.set_polite_email(address)
        if state.json_output:
            output({"openalex_email": address})
        else:
            skin.success(f"OpenAlex polite-pool email set to {address}")
        return
    current = oa.get_polite_email()
    if state.json_output:
        output({"openalex_email": current})
    elif current:
        skin.status("OpenAlex email", current)
    else:
        skin.warning("No polite-pool email set. Set one with: openalex email you@example.com")


def register(cli_group):
    cli_group.add_command(openalex)
