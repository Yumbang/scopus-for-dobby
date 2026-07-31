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


def _resolve_seeds(eids, collection, tag) -> tuple[list[dict], list[str]]:
    """Resolve a seed batch from EIDs, a collection, or a tag.

    Shared by ``graph`` and ``analyze`` so the two can never disagree about
    what "a batch of papers" means. Returns ``(seeds_with_dois, eids_without)``
    — seeds need a DOI to be matched against OpenAlex.
    """
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
    return seeds, no_doi


def _depth_options(func):
    """Options shared by ``graph`` and ``analyze``."""
    for option in reversed(
        [
            click.option(
                "--depth",
                type=click.IntRange(1, oa.MAX_DEPTH),
                default=1,
                show_default=True,
                help="How many expansion levels. Beyond 1, only corroborated nodes expand.",
            ),
            click.option(
                "--min-reached",
                type=int,
                default=oa.DEFAULT_MIN_REACHED,
                show_default=True,
                help="Expand a node only if this many papers you hold point at it.",
            ),
            click.option(
                "--max-nodes",
                type=int,
                default=oa.DEFAULT_MAX_NODES,
                show_default=True,
                help="Stop expanding past this many nodes.",
            ),
            click.option(
                "--deep-direction",
                type=click.Choice(["references", "cited-by", "both"]),
                default="references",
                show_default=True,
                help="Direction for levels beyond the first (citers cost 1 request/node).",
            ),
        ]
    ):
        func = option(func)
    return func


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
@_depth_options
@handle_error
def oa_graph(
    eids,
    collection,
    tag,
    direction,
    per_seed_limit,
    fmt,
    out_path,
    depth,
    min_reached,
    max_nodes,
    deep_direction,
):
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

    seeds, no_doi = _resolve_seeds(eids, collection, tag)

    # Resolve format and output path from each other.
    if fmt is None and out_path:
        suffix = Path(out_path).suffix.lstrip(".").lower()
        fmt = suffix if suffix in _FORMATS else "graphml"
    fmt = fmt or "graphml"
    out_path = out_path or f"citation_graph.{fmt}"

    if not state.json_output:
        depth_note = f", depth {depth}" if depth > 1 else ""
        skin.info(
            f"Building {direction} graph from {len(seeds)} seed(s) "
            f"(limit {per_seed_limit}/seed{depth_note})..."
        )

    graph = oa.build_citation_graph(
        seeds,
        direction=direction,
        per_seed_limit=per_seed_limit,
        depth=depth,
        min_reached=min_reached,
        max_nodes=max_nodes,
        deep_direction=deep_direction,
    )
    files = oa.GRAPH_WRITERS[fmt](graph, out_path)

    summary = {
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "seeds": len(seeds),
        "seeds_not_in_openalex": graph["unmatched"],
        "seeds_without_doi": no_doi,
        "roles": graph["meta"]["roles"],
        "depth": graph["meta"]["depth"],
        "truncated": graph["meta"]["truncated"],
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
    if graph["meta"]["truncated"]:
        skin.warning(
            f"     Stopped at --max-nodes {max_nodes}: the graph is incomplete."
        )


@openalex.command("analyze")
@click.argument("eids", nargs=-1)
@click.option("--collection", "-c", default=None, help="Seed from all articles in a collection")
@click.option("--tag", "-t", default=None, help="Seed from all articles with a tag")
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Analyze a graph exported earlier instead of building one (no API calls).",
)
@click.option(
    "--direction",
    "-d",
    type=click.Choice(["references", "cited-by", "both"]),
    default="both",
    show_default=True,
    help="references = what seeds cite; cited-by = what cites seeds. "
    "Matches `graph`, so the same flags give the same graph in both commands.",
)
@click.option("--per-seed-limit", type=int, default=200, show_default=True)
@click.option("--top", "-n", type=int, default=10, show_default=True, help="Rows per section")
@click.option("--communities", "want_communities", is_flag=True, help="Cluster into themes ([analysis] extra)")
@click.option("--dry-run", is_flag=True, help="Build depth 1, then report what going deeper would cost.")
@_depth_options
@handle_error
def oa_analyze(
    eids,
    collection,
    tag,
    from_file,
    direction,
    per_seed_limit,
    top,
    want_communities,
    dry_run,
    depth,
    min_reached,
    max_nodes,
    deep_direction,
):
    """Explain a citation graph: what the query found, missed, and what to read.

    Reports coverage, papers your corpus cites but doesn't contain, themes, and
    the works it rests on. A graph file is optional output, not the point.

    \b
    Examples:
      scopus-for-dobby openalex analyze --collection review
      scopus-for-dobby openalex analyze --collection review --depth 2 --communities
      scopus-for-dobby openalex analyze --from-file map.json --json
      scopus-for-dobby openalex analyze --collection review --depth 3 --dry-run
    """
    from scopus_for_dobby.core import graph_analysis as ga
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    no_doi: list[str] = []

    if from_file:
        graph = oa.read_graph(from_file)
    else:
        seeds, no_doi = _resolve_seeds(eids, collection, tag)
        # --dry-run builds depth 1 (needed anyway, and cheap) and then projects
        # rather than pretending to know costs without looking.
        build_depth = 1 if dry_run else depth
        if not state.json_output:
            skin.info(f"Building graph from {len(seeds)} seed(s), depth {build_depth}...")
        graph = oa.build_citation_graph(
            seeds,
            direction=direction,
            per_seed_limit=per_seed_limit,
            depth=build_depth,
            min_reached=min_reached,
            max_nodes=max_nodes,
            deep_direction=deep_direction,
        )

    if dry_run and not from_file:
        plan = oa.plan_expansion(graph, depth=depth, min_reached=min_reached)
        if state.json_output:
            output(plan)
            return
        skin.status("Current", f"depth {plan['current_depth']}, {plan['current_nodes']} nodes")
        skin.status("Avg refs/node", str(plan["avg_references_per_node"]))
        for level in plan["levels"]:
            kind = "exact" if level["exact"] else "projected"
            click.echo(
                f"  depth {level['level']}: expand {level['expanding']} node(s) "
                f"-> ~{level['estimated_new_nodes']} new nodes, "
                f"~{level['estimated_requests']} request(s)  [{kind}]"
            )
        click.echo(f"  projected total: ~{plan['projected_total_nodes']} nodes")
        return

    topology = ga.describe_topology(graph)
    stats = ga.corpus_stats(graph)
    known = [n.get("doi") for n in graph["nodes"].values() if n.get("is_seed")]
    gaps = ga.gap_papers(graph, known_dois=known, limit=top)
    coupling = ga.bibliographic_coupling(graph) if topology["supports"]["coupling"] else []
    cocited = ga.co_citation(graph) if topology["supports"]["co_citation"] else []
    outliers = ga.outlier_seeds(graph) if topology["supports"]["coupling"] else []

    themes = []
    community_error = None
    if want_communities:
        try:
            themes = ga.communities(coupling)
        except ga.AnalysisUnsupported as e:
            community_error = str(e)

    report = {
        "topology": topology,
        "stats": stats,
        "seeds_without_doi": no_doi,
        "gap_papers": gaps,
        "coupling": coupling[:top],
        "co_citation": cocited[:top],
        "outlier_seeds": outliers,
        "themes": themes,
    }
    if community_error:
        report["communities_error"] = community_error

    if state.json_output:
        output(report)
        return

    _print_report(skin, report, top)


def _print_report(skin, report: dict, top: int) -> None:
    """Human output: findings first, caveats attached to what they qualify."""
    stats, topology = report["stats"], report["topology"]

    skin.status(
        "Corpus",
        f"{stats['seeds']} seed(s), {stats['nodes']} nodes, {stats['edges']} edges, "
        f"depth {stats['depth']}",
    )
    if stats["unmatched_seeds"]:
        skin.hint(f"  {len(stats['unmatched_seeds'])} seed(s) not found in OpenAlex")
    if report["seeds_without_doi"]:
        skin.hint(f"  {len(report['seeds_without_doi'])} seed(s) skipped (no DOI)")
    if stats["truncated"]:
        skin.warning("  Graph was truncated at --max-nodes: findings are partial.")

    if report["gap_papers"]:
        click.echo()
        skin.info("Papers your corpus cites but does not contain:")
        for row in report["gap_papers"]:
            year = row["year"] or "n.d."
            click.echo(
                f"  [{row['reached_by']}x] {row['label'][:70]} ({year}) "
                f"— {row['cited_by_count']} citations"
            )
            if row["doi"]:
                click.echo(f"           doi:{row['doi']}")

    if report["themes"]:
        click.echo()
        skin.info(f"Themes ({len(report['themes'])} clusters):")
        for theme in report["themes"]:
            names = ", ".join(m["label"][:40] for m in theme["representative"][:2])
            click.echo(f"  #{theme['id']} — {theme['size']} papers: {names}")
    elif report.get("communities_error"):
        click.echo()
        skin.warning(report["communities_error"])

    if report["co_citation"]:
        click.echo()
        skin.info("Most co-cited works (the corpus's shared foundation):")
        for pair in report["co_citation"][:top]:
            click.echo(
                f"  {pair['shared']}x together: {pair['source_label'][:34]} + "
                f"{pair['target_label'][:34]}"
            )

    if report["outlier_seeds"]:
        click.echo()
        skin.warning("Seeds sharing no references with the rest (possibly off-topic):")
        for row in report["outlier_seeds"]:
            click.echo(f"  {row['label'][:70]}")

    unsupported = [k for k, ok in topology["supports"].items() if not ok]
    if unsupported:
        click.echo()
        for key in unsupported:
            reason = topology["reasons"].get(key)
            if reason:
                skin.hint(f"{key}: {reason}")


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
