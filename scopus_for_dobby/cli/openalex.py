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
    """OpenAlex integration — enrichment, citation graphs, and analysis.

    Free, but metered: ~$0.0001 per request against a daily budget. Without an
    API key that budget is small and shared per IP address. Run `openalex key`
    to check or set one — free at https://openalex.org/settings/api.
    """


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
                default=None,
                help="Budget for expansion beyond your seeds "
                f"(default: max({oa.DEFAULT_MAX_NODES}, {oa.NODES_PER_SEED} x seeds)). "
                "Checked between levels, so a level never half-runs.",
            ),
            click.option(
                "--node-fields",
                type=click.Choice(sorted(oa.NODE_FIELD_SETS)),
                multiple=True,
                help="Extra OpenAlex fields on nodes (e.g. authorships). "
                "Opt-in: enlarges every response.",
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
    default="references",
    show_default=True,
    help="references = what seeds cite (batched, cheap); cited-by = what cites "
    "seeds (one request PER seed); both = each of the above",
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
    node_fields,
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
        node_fields=tuple(node_fields),
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
        "max_nodes": graph["meta"]["max_nodes"],
        "openalex_requests": graph["meta"]["requests"],
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
    skin.hint(f"     {graph['meta']['requests']} OpenAlex request(s)")
    if graph["meta"]["truncated"]:
        skin.warning(
            f"     Stopped before depth {graph['meta']['stopped_before_level']} at "
            f"--max-nodes {graph['meta']['max_nodes']}. Every level that ran is "
            f"complete; raise --max-nodes to go deeper."
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
    default="references",
    show_default=True,
    help="references = what seeds cite (batched, cheap); cited-by = what cites "
    "seeds (one request PER seed). Matches `graph`, so the same flags give the "
    "same graph in both commands.",
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
    node_fields,
):
    """Explain a citation graph: what the query found, missed, and what to read.

    Reports coverage, papers your corpus cites but doesn't contain, themes, and
    the works it rests on. A graph file is optional output, not the point.

    \b
    Examples:
      scopus-for-dobby openalex analyze --collection review
      scopus-for-dobby openalex analyze --collection review --depth 2 --communities
      scopus-for-dobby --json openalex analyze --from-file map.json
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
            node_fields=tuple(node_fields),
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
            themes = ga.communities(coupling, graph=graph, top=top)
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
        "reference_age": ga.reference_age(graph),
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
    if stats.get("coverage_from_file"):
        # A loaded graph does not carry which seeds failed to match or lacked a
        # DOI. Reporting 0 would be inventing a measurement.
        skin.hint(
            "  seed match / DOI coverage not recorded in the export — "
            "rebuild from the collection if you need it"
        )
    else:
        if stats["unmatched_seeds"]:
            skin.hint(f"  {len(stats['unmatched_seeds'])} seed(s) not found in OpenAlex")
        if report["seeds_without_doi"]:
            skin.hint(f"  {len(report['seeds_without_doi'])} seed(s) skipped (no DOI)")
    # The denominator for every reference-based figure below. Silent before,
    # and on a real corpus it removed 47 of 273 seeds from all of them.
    if stats.get("seeds_without_references"):
        skin.warning(
            f"  {stats['seeds_without_references']} seed(s) have no reference data in "
            f"OpenAlex — coupling, co-citation and gap papers are over the remaining "
            f"{stats['seeds_with_references']}."
        )
    if stats["truncated"]:
        skin.warning(
            f"  Stopped before depth {stats.get('stopped_before_level')} at --max-nodes: "
            f"levels that ran are complete, but the corpus was not expanded further."
        )
    if stats.get("openalex_requests") is not None:
        skin.hint(f"  {stats['openalex_requests']} OpenAlex request(s)")

    if report["gap_papers"]:
        click.echo()
        skin.info("Papers your corpus cites but does not contain:")
        for row in report["gap_papers"]:
            year = row["year"] or "n.d."
            click.echo(
                f"  [{row['seed_reached_by']} of your papers] {row['label'][:64]} ({year}) "
                f"— {row['cited_by_count']} citations"
            )
            if row["doi"]:
                click.echo(f"           doi:{row['doi']}")

    if report["themes"]:
        click.echo()
        mod = report["themes"][0].get("modularity")
        strength = ""
        if isinstance(mod, (int, float)):
            strength = f", modularity {mod:.2f}" + (" — weak split, hedge" if mod < 0.3 else "")
        skin.info(f"Themes ({len(report['themes'])} clusters{strength}):")
        for theme in report["themes"]:
            names = ", ".join(m["label"][:40] for m in theme["representative"][:2])
            click.echo(f"  #{theme['id']} — {theme['size']} papers: {names}")
            # What a theme shares says more about what it *is* than its titles.
            for ref in theme.get("top_shared_references", [])[:3]:
                click.echo(
                    f"        {ref['cited_by_members']}/{theme['size']} cite: "
                    f"{ref['label'][:56]}"
                )
    elif report.get("communities_error"):
        click.echo()
        skin.warning(report["communities_error"])

    age = report.get("reference_age") or {}
    if age.get("median_year"):
        click.echo()
        shares = age["shares"]
        skin.info(
            f"Reference age: median {age['median_year']:g}, "
            f"{shares.get('2015+', 0):.0%} from 2015+, "
            f"{shares.get('pre-1940', 0):.1%} pre-1940"
        )

    if report["coupling"]:
        click.echo()
        skin.info("Most closely related papers (shared references — research fronts):")
        for pair in report["coupling"][:top]:
            click.echo(
                f"  {pair['shared']} shared refs: {pair['source_label'][:34]} + "
                f"{pair['target_label'][:34]}"
            )

    if report["co_citation"]:
        click.echo()
        skin.info("Most co-cited works (the corpus's shared foundation):")
        for pair in report["co_citation"][:top]:
            click.echo(
                f"  {pair['shared']}x together: {pair['source_label'][:34]} + "
                f"{pair['target_label'][:34]}"
            )

    # Split by reason: telling someone their paper looks off-topic when we
    # simply have no reference data for it is a false accusation.
    unrelated = [r for r in report["outlier_seeds"] if r["reason"] == "unrelated"]
    no_data = [r for r in report["outlier_seeds"] if r["reason"] == "no_reference_data"]
    if unrelated:
        click.echo()
        skin.warning("Seeds sharing no references with the rest (possibly off-topic):")
        for row in unrelated:
            click.echo(f"  {row['label'][:70]}")
    if no_data:
        click.echo()
        skin.hint(
            f"{len(no_data)} seed(s) have no reference data in OpenAlex — "
            f"they cannot share references, which says nothing about their topic."
        )

    unsupported = [k for k, ok in topology["supports"].items() if not ok]
    if unsupported:
        click.echo()
        for key in unsupported:
            reason = topology["reasons"].get(key)
            if reason:
                skin.hint(f"{key}: {reason}")


@openalex.command("key")
@click.argument("api_key", required=False)
@handle_error
def oa_key(api_key):
    """Show or set the OpenAlex API key (free, and worth having).

    OpenAlex meters a daily budget of roughly $0.0001 per request. Without a
    key that budget is small and shared **per IP address** — another program on
    the same machine can exhaust it and take this CLI down with it. A free key
    is billed to you alone and is worth about 10x as much.

    Get one at https://openalex.org/settings/api
    """
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    if api_key:
        oa.set_api_key(api_key)
        if state.json_output:
            output({"openalex_api_key": "set"})
        else:
            skin.success("OpenAlex API key saved to ~/.scopus-for-dobby/config.json")
        return
    current = oa.get_api_key()
    if state.json_output:
        output({"openalex_api_key": "set" if current else None})
    elif current:
        # Never echo the key itself.
        skin.status("OpenAlex API key", f"set (…{current[-4:]})")
    else:
        skin.warning(
            "No OpenAlex API key set. You are on the anonymous per-IP budget "
            "(~1000 requests/day, shared with anything else on this machine)."
        )
        skin.hint("     Free key: https://openalex.org/settings/api "
                  "then: openalex key <KEY>")


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
