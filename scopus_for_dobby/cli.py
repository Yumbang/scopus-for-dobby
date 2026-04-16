#!/usr/bin/env python3
"""scopus-for-dobby — Stateful CLI for Scopus academic research.

Usage:
    # Setup API key (free tier)
    scopus-for-dobby auth setup --api-key YOUR_KEY

    # Upgrade to institutional tier
    scopus-for-dobby auth setup --api-key YOUR_KEY --inst-token YOUR_TOKEN

    # Search papers
    scopus-for-dobby search "deep learning" --limit 20 --sort citedby-count

    # Get paper details
    scopus-for-dobby abstract 10.1016/j.example.2024

    # Save results to local DB
    scopus-for-dobby db add --from-last-search

    # Interactive REPL
    scopus-for-dobby
"""

import json
import sys
from datetime import datetime

import click

from scopus_for_dobby.core import abstract as abstract_mod
from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.core import auth as auth_mod
from scopus_for_dobby.core import export as export_mod
from scopus_for_dobby.core import search as search_mod
from scopus_for_dobby.core.session import get_session

# Global state
_json_output = False
_repl_mode = False


def output(data, message: str = ""):
    """Print output in JSON or human-readable format."""
    if _json_output:
        # Strip internal keys
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if not k.startswith("_")}
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        if message:
            click.echo(message)
        if isinstance(data, dict):
            _print_dict(data)
        elif isinstance(data, list):
            _print_list(data)
        else:
            click.echo(str(data))


def _print_dict(d: dict, indent: int = 0):
    prefix = "  " * indent
    for k, v in d.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            click.echo(f"{prefix}{k}:")
            _print_dict(v, indent + 1)
        elif isinstance(v, list):
            click.echo(f"{prefix}{k}:")
            _print_list(v, indent + 1)
        else:
            click.echo(f"{prefix}{k}: {v}")


def _print_list(items: list, indent: int = 0):
    prefix = "  " * indent
    for i, item in enumerate(items):
        if isinstance(item, dict):
            click.echo(f"{prefix}[{i}]")
            _print_dict(item, indent + 1)
        else:
            click.echo(f"{prefix}- {item}")


def handle_error(func):
    """Decorator for consistent error handling."""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if _json_output:
                click.echo(json.dumps({"error": str(e), "type": type(e).__name__}))
            else:
                click.echo(f"Error: {e}", err=True)
            if not _repl_mode:
                sys.exit(1)

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


# ── Main CLI Group ────────────────────────────────────────────────────────────


@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.pass_context
def cli(ctx, use_json):
    """scopus-for-dobby — Search, collect, and manage academic papers.

    Run without a subcommand to enter interactive REPL mode.
    """
    global _json_output
    _json_output = use_json

    if ctx.invoked_subcommand is None:
        ctx.invoke(repl)


# ── Auth Commands ─────────────────────────────────────────────────────────────


@cli.group()
def auth():
    """Authentication and API key management."""
    pass


@auth.command("setup")
@click.option("--api-key", required=True, help="Elsevier API key from dev.elsevier.com")
@click.option(
    "--inst-token", default=None, help="Institutional token (optional, for COMPLETE view)"
)
@handle_error
def auth_setup(api_key, inst_token):
    """Configure Scopus API credentials."""
    result = auth_mod.setup(api_key, inst_token)
    output(result, f"Configured ({result['tier']} tier).")


@auth.command("upgrade")
@click.option("--inst-token", required=True, help="Institutional token")
@handle_error
def auth_upgrade(inst_token):
    """Add institutional token to upgrade to COMPLETE view."""
    result = auth_mod.set_inst_token(inst_token)
    output(result, result["message"])


@auth.command("downgrade")
@handle_error
def auth_downgrade():
    """Remove institutional token, revert to free tier."""
    result = auth_mod.remove_inst_token()
    output(result, result["message"])


@auth.command("status")
@handle_error
def auth_status():
    """Check API key status and connectivity."""
    result = auth_mod.get_status()
    output(result)


@auth.command("logout")
@handle_error
def auth_logout():
    """Remove all saved credentials."""
    result = auth_mod.logout()
    output(result, "Credentials removed.")


# ── Search Commands ───────────────────────────────────────────────────────────


@cli.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option("--limit", "-n", type=int, default=25, help="Results to return (max 25 per page)")
@click.option(
    "--sort", "-s", default="relevancy", help="Sort: relevancy, citedby-count, -pubyear, +pubyear"
)
@click.option("--year", "-y", default=None, help="Year or range (e.g., 2024 or 2020-2024)")
@click.option("--subject", default=None, help="Subject area code (COMP, MEDI, PHYS, etc.)")
@click.option("--no-save", is_flag=True, help="Don't auto-save results to local DB")
@click.option("--tag", "-t", multiple=True, help="Tags to apply when saving (auto-save)")
@click.option("--collection", "-c", default=None, help="Collection to add results to (auto-save)")
@handle_error
def search_cmd(query, limit, sort, year, subject, no_save, tag, collection):
    """Search Scopus for papers.

    Results are automatically saved to the local database. Use --no-save
    to skip. The query is auto-wrapped in TITLE-ABS-KEY() unless it already
    contains Scopus field codes like AUTH(), AFFIL(), DOI(), etc.

    \b
    Examples:
      scopus-for-dobby search deep learning image segmentation
      scopus-for-dobby search "AUTH(Kim) AND AFFIL(Seoul National)" --sort citedby-count
      scopus-for-dobby search renewable energy --year 2022-2024 --no-save
      scopus-for-dobby search transformer --tag ml --collection thesis
    """
    query_str = " ".join(query)
    session = get_session()

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    result = search_mod.search(
        query=query_str,
        count=limit,
        sort=sort,
        date=year,
        subj=subject,
    )

    session.last_search = result
    session.add_to_history(query_str)

    entries = result["entries"]
    if not entries:
        skin.warning("No results found.")
        skin.hint("Try broadening your query or check Scopus field code syntax.")
        return

    for i, entry in enumerate(entries, 1):
        skin.print_paper(i, entry)

    # Auto-save to DB (default)
    if not no_save and entries:
        tags = list(tag) if tag else None
        db_result = db_mod.add_entries(entries, tags=tags, collection=collection)
        print()
        skin.success(
            f"Auto-saved: {db_result['added']} new, "
            f"{db_result['updated']} updated "
            f"({db_result['total']} total in DB)"
        )
    else:
        print()

    skin.info(f"Showing {len(entries)} of {result['total_results']} results")

    rate = result.get("_rate_limit", {})
    if rate and rate.get("remaining") is not None:
        skin.update_quota(rate["remaining"])
        skin.hint(f"API quota remaining: {rate['remaining']}")


@cli.command("search-all")
@click.argument("query", nargs=-1, required=True)
@click.option("--max", "max_results", type=int, default=100, help="Maximum total results to fetch")
@click.option("--sort", "-s", default="relevancy", help="Sort order")
@click.option("--year", "-y", default=None, help="Year or range")
@click.option("--subject", default=None, help="Subject area code")
@click.option("--no-save", is_flag=True, help="Don't auto-save results to local DB")
@click.option("--tag", "-t", multiple=True, help="Tags to apply when saving")
@click.option("--collection", "-c", default=None, help="Collection to add results to")
@handle_error
def search_all_cmd(query, max_results, sort, year, subject, no_save, tag, collection):
    """Fetch multiple pages of search results (paginated).

    Results are automatically saved to the local database.

    \b
    Example:
      scopus-for-dobby search-all "machine learning" --max 200 --sort -pubyear
      scopus-for-dobby search-all transformer --max 50 --no-save
    """
    query_str = " ".join(query)
    session = get_session()

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    def on_progress(fetched, total):
        skin.progress(fetched, total, f"Fetched {fetched}/{total}")

    result = search_mod.search_all_pages(
        query=query_str,
        max_results=max_results,
        sort=sort,
        date=year,
        subj=subject,
        progress_callback=on_progress,
    )

    session.last_search = result
    session.add_to_history(query_str)

    entries = result["entries"]
    for i, entry in enumerate(entries, 1):
        skin.print_paper(i, entry)

    print()
    skin.success(f"Fetched {result['fetched']} of {result['total_results']} total results")

    rate = result.get("_rate_limit", {})
    if rate and rate.get("remaining") is not None:
        skin.update_quota(rate["remaining"])

    # Auto-save to DB (default)
    if not no_save and entries:
        tags = list(tag) if tag else None
        db_result = db_mod.add_entries(entries, tags=tags, collection=collection)
        skin.success(
            f"Auto-saved: {db_result['added']} new, "
            f"{db_result['updated']} updated "
            f"({db_result['total']} total in DB)"
        )


# ── Abstract Retrieval ────────────────────────────────────────────────────────


@cli.command("abstract")
@click.argument("identifier")
@click.option("--view", default=None, help="View: META, META_ABS, FULL, REF, ENTITLED")
@handle_error
def abstract_cmd(identifier, view):
    """Retrieve detailed metadata for a single paper.

    IDENTIFIER can be a DOI, EID (2-s2.0-...), or Scopus ID.
    Auto-detects the identifier type.

    \b
    Examples:
      scopus-for-dobby abstract 10.1016/j.example.2024
      scopus-for-dobby abstract 2-s2.0-85012345678
    """
    session = get_session()

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    result = abstract_mod.retrieve(identifier, view)
    session.last_abstract = result

    rate = result.get("_rate_limit", {})
    if rate and rate.get("remaining") is not None:
        skin.update_quota(rate["remaining"])

    skin.section("Paper Details")
    skin.status("Title", result["title"])
    skin.status(
        "First Author",
        f"{result['first_author']}"
        + (f"  (AUID: {result['first_author_auid']})" if result.get("first_author_auid") else ""),
    )
    skin.status("Journal", result["journal"])

    loc_parts = []
    if result.get("volume"):
        loc_parts.append(f"Vol.{result['volume']}")
    if result.get("issue"):
        loc_parts.append(f"No.{result['issue']}")
    if result.get("pages"):
        loc_parts.append(result["pages"])
    if loc_parts:
        skin.status("Location", " ".join(loc_parts))

    skin.status("Date", result["cover_date"])
    skin.status("DOI", result["doi"])
    skin.status("EID", result["eid"])
    skin.status("Cited by", str(result["cited_by"]))
    skin.status("Open Access", "Yes" if result["open_access"] else "No")

    if result.get("affiliations"):
        affs = "; ".join(a["name"] for a in result["affiliations"] if a.get("name"))
        if affs:
            skin.status("Affiliations", affs)

    if result.get("abstract"):
        print()
        skin.status("Abstract", "")
        # Word wrap abstract
        abstract = result["abstract"]
        for i in range(0, len(abstract), 80):
            print(f"    {abstract[i : i + 80]}")

    if result.get("all_authors"):
        skin.section("All Authors")
        for a in result["all_authors"]:
            auid = f"  AUID: {a['auid']}" if a.get("auid") else ""
            print(f"    [{a.get('seq', '?')}] {a['name']}{auid}")

    if result.get("keywords"):
        skin.status("Author Keywords", result["keywords"])

    if result.get("index_keywords"):
        skin.status("Index Keywords", ", ".join(result["index_keywords"]))

    if result.get("subject_areas"):
        areas = [f"{a['name']} ({a['abbrev']})" for a in result["subject_areas"]]
        skin.status("Subject Areas", ", ".join(areas))

    # Auto-save / update DB with enriched abstract data
    db_result = db_mod.add_entries([result])
    if db_result["updated"]:
        skin.success("DB entry updated with enriched metadata")
    elif db_result["added"]:
        skin.success("Saved to DB")

    # Missing fields hint
    missing = []
    if not result.get("abstract"):
        missing.append("abstract")
    if not result.get("all_authors"):
        missing.append("full author list")
    if missing:
        print()
        skin.hint(f"Not available: {', '.join(missing)} (requires institutional key)")


# ── Database Commands ─────────────────────────────────────────────────────────


@cli.group("db")
def db():
    """Local article database management."""
    pass


@db.command("add")
@click.option(
    "--from-last-search", "from_search", is_flag=True, help="Add all results from last search"
)
@click.option(
    "--indices", "-i", default=None, help="Comma-separated indices from last search (e.g., 1,3,5)"
)
@click.option(
    "--from-last-abstract", "from_abstract", is_flag=True, help="Add last retrieved abstract"
)
@click.option("--tag", "-t", multiple=True, help="Tags to apply")
@click.option("--collection", "-c", default=None, help="Add to collection")
@handle_error
def db_add(from_search, indices, from_abstract, tag, collection):
    """Add articles to the local database.

    \b
    Examples:
      scopus-for-dobby db add --from-last-search --tag ml --tag survey
      scopus-for-dobby db add --indices 1,3,5 --collection "thesis-refs"
      scopus-for-dobby db add --from-last-abstract
    """
    session = get_session()
    entries = []

    if from_abstract and session.last_abstract:
        raw = session.last_abstract.get("_raw", {})
        core = raw.get("coredata", {})
        entries = [core] if core else [session.last_abstract]
    elif indices:
        idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        entries = session.get_entries_by_indices(idx_list)
    elif from_search:
        entries = session.get_all_last_entries()
    else:
        entries = session.get_all_last_entries()

    if not entries:
        click.echo("No entries to add. Run a search first.", err=True)
        return

    tags = list(tag) if tag else None
    result = db_mod.add_entries(entries, tags=tags, collection=collection)

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(
        f"Added {result['added']}, updated {result['updated']} "
        f"(total: {result['total']} articles in DB)"
    )


@db.command("list")
@click.option("--tag", "-t", default=None, help="Filter by tag")
@click.option("--collection", "-c", default=None, help="Filter by collection")
@click.option("--query", "-q", default=None, help="Text search in title/author/journal")
@click.option(
    "--sort",
    "-s",
    default="added",
    type=click.Choice(["added", "cited", "date", "title"]),
    help="Sort order",
)
@click.option("--limit", "-n", type=int, default=50, help="Max results")
@handle_error
def db_list(tag, collection, query, sort, limit):
    """List articles in the local database.

    \b
    Examples:
      scopus-for-dobby db list --tag survey --sort cited
      scopus-for-dobby db list --collection thesis-refs
      scopus-for-dobby db list --query "transformer" --limit 10
    """
    result = db_mod.list_articles(
        tag=tag,
        collection=collection,
        query=query,
        sort=sort,
        limit=limit,
    )

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    articles = result["articles"]
    if not articles:
        skin.warning("No articles found.")
        return

    session = get_session()
    # Store as last search so indices work
    session.last_search = {"entries": articles}

    for i, article in enumerate(articles, 1):
        skin.print_paper(i, article)
        tags = article.get("_tags", [])
        if tags:
            tag_str = ", ".join(tags)
            skin.hint(f"     Tags: {tag_str}")

    print()
    skin.info(
        f"Showing {len(articles)} of {result['total_matching']} matching "
        f"({result['total_in_db']} total in DB)"
    )


@db.command("remove")
@click.option("--indices", "-i", default=None, help="Comma-separated indices from last list")
@click.option("--eid", "-e", multiple=True, help="EID(s) to remove")
@click.option("--confirm", is_flag=True, help="Skip confirmation")
@handle_error
def db_remove(indices, eid, confirm):
    """Remove articles from the local database.

    \b
    Examples:
      scopus-for-dobby db remove --indices 1,3
      scopus-for-dobby db remove --eid 2-s2.0-85012345678
    """
    session = get_session()
    eids = list(eid)

    if indices:
        idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        entries = session.get_entries_by_indices(idx_list)
        eids.extend(e.get("eid", "") for e in entries if e.get("eid"))

    if not eids:
        click.echo("No articles specified for removal.", err=True)
        return

    if not confirm and not _repl_mode:
        click.confirm(f"Remove {len(eids)} article(s)?", abort=True)

    result = db_mod.remove_entries(eids)

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Removed {result['removed']} articles ({result['total']} remaining)")


@db.command("tag")
@click.option("--indices", "-i", default=None, help="Comma-separated indices from last list/search")
@click.option("--eid", "-e", multiple=True, help="EID(s) to tag")
@click.argument("tags", nargs=-1, required=True)
@handle_error
def db_tag(indices, eid, tags):
    """Add tags to articles.

    \b
    Examples:
      scopus-for-dobby db tag --indices 1,2,3 survey important
      scopus-for-dobby db tag --eid 2-s2.0-8501234 ml deep-learning
    """
    session = get_session()
    eids = list(eid)

    if indices:
        idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        entries = session.get_entries_by_indices(idx_list)
        eids.extend(e.get("eid", "") for e in entries if e.get("eid"))

    if not eids:
        click.echo("No articles specified.", err=True)
        return

    result = db_mod.tag_articles(eids, list(tags))

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Tagged {result['tagged']} articles with: {', '.join(tags)}")


@db.command("untag")
@click.option("--indices", "-i", default=None, help="Comma-separated indices")
@click.option("--eid", "-e", multiple=True, help="EID(s)")
@click.argument("tags", nargs=-1, required=True)
@handle_error
def db_untag(indices, eid, tags):
    """Remove tags from articles."""
    session = get_session()
    eids = list(eid)

    if indices:
        idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        entries = session.get_entries_by_indices(idx_list)
        eids.extend(e.get("eid", "") for e in entries if e.get("eid"))

    result = db_mod.untag_articles(eids, list(tags))

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Removed tags from {result['untagged']} articles")


@db.command("note")
@click.argument("eid")
@click.argument("note")
@handle_error
def db_note(eid, note):
    """Set a note on an article.

    \b
    Example:
      scopus-for-dobby db note 2-s2.0-85012345678 "Good methodology section"
    """
    db_mod.set_note(eid, note)
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Note saved on {eid}")


@db.command("info")
@click.argument("eid")
@handle_error
def db_info(eid):
    """Show full details of an article in the database."""
    article = db_mod.get_article(eid)
    output(article)


@db.command("stats")
@handle_error
def db_stats():
    """Show database statistics."""
    result = db_mod.stats()

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    skin.section("Database Stats")
    skin.status("Articles", str(result["total_articles"]))
    skin.status("Authors", str(result["total_authors"]))
    skin.status("Collections", str(result["total_collections"]))
    skin.status("Tags", str(result["total_tags"]))
    skin.status("DB size", f"{result['db_size_kb']} KB")
    skin.status("Location", result["db_path"])

    if result.get("tags"):
        skin.section("Tags")
        for tag, count in sorted(result["tags"].items(), key=lambda x: -x[1]):
            skin.status(f"  {tag}", str(count))

    if result.get("years"):
        skin.section("Year Distribution")
        for year, count in result["years"].items():
            skin.status(f"  {year}", str(count))


# ── Collection Commands ───────────────────────────────────────────────────────


@cli.group("collection")
def collection_cmd():
    """Collection management."""
    pass


@collection_cmd.command("list")
@handle_error
def collection_list():
    """List all collections."""
    result = db_mod.list_collections()
    colls = result.get("collections", {})

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    if not colls:
        skin.info("No collections yet. Create one with: collection create <name>")
        return

    skin.section("Collections")
    for name, meta in colls.items():
        skin.status(name, f"{meta['article_count']} articles (created {meta['created']})")


@collection_cmd.command("create")
@click.argument("name")
@handle_error
def collection_create(name):
    """Create a new collection."""
    db_mod.create_collection(name)
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Collection '{name}' created")


@collection_cmd.command("delete")
@click.argument("name")
@click.option("--confirm", is_flag=True, help="Skip confirmation")
@handle_error
def collection_delete(name, confirm):
    """Delete a collection (articles are kept in DB)."""
    if not confirm and not _repl_mode:
        click.confirm(f"Delete collection '{name}'?", abort=True)
    db_mod.delete_collection(name)
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Collection '{name}' deleted")


@collection_cmd.command("add")
@click.argument("name")
@click.option("--indices", "-i", default=None, help="Comma-separated indices from last list/search")
@click.option("--eid", "-e", multiple=True, help="EID(s) to add")
@handle_error
def collection_add(name, indices, eid):
    """Add articles to a collection.

    \b
    Examples:
      scopus-for-dobby collection add thesis-refs --indices 1,3,5
      scopus-for-dobby collection add thesis-refs --eid 2-s2.0-85012345678
    """
    session = get_session()
    eids = list(eid)

    if indices:
        idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        entries = session.get_entries_by_indices(idx_list)
        eids.extend(e.get("eid", "") for e in entries if e.get("eid"))

    if not eids:
        click.echo("No articles specified.", err=True)
        return

    result = db_mod.add_to_collection(name, eids)
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Added {result['added']} to '{name}' ({result['total']} total)")


@collection_cmd.command("remove")
@click.argument("name")
@click.option("--indices", "-i", default=None, help="Comma-separated indices")
@click.option("--eid", "-e", multiple=True, help="EID(s) to remove")
@handle_error
def collection_remove(name, indices, eid):
    """Remove articles from a collection."""
    session = get_session()
    eids = list(eid)

    if indices:
        idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        entries = session.get_entries_by_indices(idx_list)
        eids.extend(e.get("eid", "") for e in entries if e.get("eid"))

    result = db_mod.remove_from_collection(name, eids)
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Removed {result['removed']} from '{name}' ({result['total']} remaining)")


# ── Author Commands ───────────────────────────────────────────────────────────


@cli.group("author")
def author_cmd():
    """Author database — auto-populated from article data."""
    pass


@author_cmd.command("list")
@click.option("--query", "-q", default=None, help="Search by author name")
@click.option(
    "--sort",
    "-s",
    default="papers",
    type=click.Choice(["papers", "name", "added"]),
    help="Sort order",
)
@click.option("--limit", "-n", type=int, default=50, help="Max results")
@handle_error
def author_list(query, sort, limit):
    """List authors in the local database.

    Authors are auto-extracted from articles when they are saved.

    \b
    Examples:
      scopus-for-dobby author list --sort papers
      scopus-for-dobby author list --query "Kim" --sort name
    """
    result = db_mod.list_authors(query=query, sort=sort, limit=limit)

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    authors = result["authors"]
    if not authors:
        skin.warning("No authors found.")
        return

    skin.table(
        ["#", "Name", "AUID", "Papers", "Affiliations"],
        [
            [
                str(i),
                a["name"],
                a["auid"],
                str(a["paper_count"]),
                "; ".join(a["affiliations"][:2]) + ("..." if len(a["affiliations"]) > 2 else ""),
            ]
            for i, a in enumerate(authors, 1)
        ],
    )
    print()
    skin.info(f"Showing {len(authors)} of {result['total']} authors")


@author_cmd.command("info")
@click.argument("auid")
@handle_error
def author_info(auid):
    """Show author details, their articles, and co-authors.

    \b
    Example:
      scopus-for-dobby author info 55666793600
    """
    result = db_mod.get_author(auid)

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    skin.section(f"Author: {result['name']}")
    skin.status("AUID", result["auid"])
    if result.get("orcid"):
        skin.status("ORCID", result["orcid"])
    if result["affiliations"]:
        skin.status("Affiliations", "; ".join(result["affiliations"]))
    if result.get("h_index") is not None:
        skin.status("h-index", str(result["h_index"]))
    if result.get("document_count") is not None:
        skin.status("Total publications", str(result["document_count"]))
    if result.get("cited_by_count") is not None:
        skin.status("Cited by", str(result["cited_by_count"]))
    if result.get("coauthor_count") is not None:
        skin.status("Co-authors (Scopus)", str(result["coauthor_count"]))
    skin.status("Papers in DB", str(result["paper_count"]))
    if result.get("subject_areas"):
        areas = [f"{a['name']} ({a['abbrev']})" for a in result["subject_areas"][:5]]
        skin.status("Subject areas", ", ".join(areas))
        if len(result["subject_areas"]) > 5:
            skin.hint(f"     ... and {len(result['subject_areas']) - 5} more")
    if result.get("fetched_at"):
        skin.hint(f"  Profile fetched: {result['fetched_at']}")
    elif result.get("h_index") is None:
        skin.hint("  Run 'author fetch <AUID>' to get full profile metrics")
    if result.get("notes"):
        skin.status("Notes", result["notes"])

    if result["articles"]:
        skin.section("Articles")
        for i, a in enumerate(result["articles"], 1):
            pos = f"[#{a['author_position']}]" if a.get("author_position") else ""
            roles = []
            if a.get("is_first_author"):
                roles.append("1st")
            if a.get("is_corresponding"):
                roles.append("corr")
            role_str = f" ({', '.join(roles)})" if roles else ""
            cited = f"Cited: {a['cited_by']}" if a.get("cited_by") else ""
            print(f"  {i}. {a['title']}")
            print(
                f"     {a['journal']} ({str(a.get('cover_date', ''))[:4]}) {pos}{role_str} {cited}"
            )
            if a.get("doi"):
                skin.hint(f"     DOI: {a['doi']}")

    if result["coauthors"]:
        skin.section("Co-authors (in DB)")
        for ca in result["coauthors"][:10]:
            skin.status(
                f"  {ca['name']} ({ca['auid']})",
                f"{ca['shared_papers']} shared papers",
            )


@author_cmd.command("coauthors")
@click.argument("auid")
@handle_error
def author_coauthors(auid):
    """Find co-authors of a given author from the local DB.

    \b
    Example:
      scopus-for-dobby author coauthors 55666793600
    """
    result = db_mod.find_coauthors(auid)

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    skin.section(f"Co-authors of {result['author']['name']}")

    if not result["coauthors"]:
        skin.info("No co-authors found in local DB.")
        return

    skin.table(
        ["Name", "AUID", "Shared Papers", "Affiliations"],
        [
            [
                ca["name"],
                ca["auid"],
                str(ca["shared_papers"]),
                "; ".join(ca["affiliations"][:2]),
            ]
            for ca in result["coauthors"]
        ],
    )
    print()
    skin.info(f"{result['total']} co-authors found")


@author_cmd.command("fetch")
@click.argument("auid")
@handle_error
def author_fetch(auid):
    """Fetch full author profile from Scopus API.

    Retrieves h-index, document count, citation metrics, ORCID,
    co-author count, and subject areas.

    \b
    Example:
      scopus-for-dobby author fetch 26022315200
    """
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    skin.info(f"Fetching profile for {auid}...")
    result = db_mod.fetch_author_profile(auid)

    skin.success(f"Profile saved: {result['name']}")
    skin.status("h-index", str(result.get("h_index", "?")))
    skin.status("Publications", str(result.get("document_count", "?")))
    skin.status("Cited by", str(result.get("cited_by_count", "?")))
    skin.status("Co-authors", str(result.get("coauthor_count", "?")))
    if result.get("orcid"):
        skin.status("ORCID", result["orcid"])
    if result.get("subject_areas"):
        areas = [f"{a['name']}" for a in result["subject_areas"][:5]]
        skin.status("Subject areas", ", ".join(areas))


@author_cmd.command("note")
@click.argument("auid")
@click.argument("note")
@handle_error
def author_note(auid, note):
    """Set a note on an author.

    \b
    Example:
      scopus-for-dobby author note 55666793600 "Potential collaborator"
    """
    db_mod.set_author_note(auid, note)
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Note saved on author {auid}")


# ── Export Commands ───────────────────────────────────────────────────────────


@cli.command("export")
@click.option(
    "--format", "fmt", type=click.Choice(["xlsx", "bibtex", "ris"]), default="xlsx", help="Export format"
)
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--tag", "-t", default=None, help="Export only articles with this tag")
@click.option("--collection", "-c", default=None, help="Export only this collection")
@click.option(
    "--from-last-search",
    "from_search",
    is_flag=True,
    help="Export last search results (not from DB)",
)
@handle_error
def export_cmd(fmt, output, tag, collection, from_search):
    """Export articles to XLSX or BibTeX.

    By default, exports from the local database. Use --from-last-search
    to export the current search results directly.

    \b
    Examples:
      scopus-for-dobby export --format xlsx -o papers.xlsx
      scopus-for-dobby export --format bibtex --collection thesis-refs
      scopus-for-dobby export --from-last-search --format bibtex -o refs.bib
    """
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    if from_search:
        session = get_session()
        entries = session.get_all_last_entries()
        if not entries:
            skin.error("No search results to export. Run a search first.")
            return
        # Normalize search entries for export
        articles = []
        for e in entries:
            try:
                articles.append(db_mod._normalize_entry(e))
            except ValueError:
                articles.append(e)
    else:
        result = db_mod.list_articles(tag=tag, collection=collection, limit=10000)
        articles = result["articles"]

    if not articles:
        skin.error("No articles to export.")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "xlsx":
        out = output or f"scopus_export_{ts}.xlsx"
        if not out.endswith(".xlsx"):
            out += ".xlsx"
        result = export_mod.export_xlsx(articles, out)
    elif fmt == "bibtex":
        out = output or f"scopus_export_{ts}.bib"
        if not out.endswith(".bib"):
            out += ".bib"
        result = export_mod.export_bibtex(articles, out)
    else:
        out = output or f"scopus_export_{ts}.ris"
        if not out.endswith(".ris"):
            out += ".ris"
        result = export_mod.export_ris(articles, out)

    skin.success(f"Exported {result['exported']} articles to {result['output']}")


# ── Plugin Commands ───────────────────────────────────────────────────────────


@cli.group("plugin")
def plugin_cmd():
    """Plugin integrations (e.g., Zotero)."""
    pass


@plugin_cmd.command("list")
@handle_error
def plugin_list():
    """List available plugins and their status."""
    from scopus_for_dobby.plugins import PLUGIN_REGISTRY
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    plugins = PLUGIN_REGISTRY.list_all()
    if not plugins:
        skin.info("No plugins available.")
        return

    skin.section("Plugins")
    for p in plugins:
        st = p.status()
        icon = "\u2713" if st["ready"] else "\u2717"
        skin.status(f"  {icon} {p.name}", f"{p.description} — {st['message']}")


@plugin_cmd.command("send")
@click.argument("plugin_name")
@click.option("--tag", "-t", default=None, help="Filter by tag")
@click.option("--collection", "-c", default=None, help="Filter by collection")
@click.option("--from-last-search", "from_search", is_flag=True, help="Send last search results")
@click.option("--indices", "-i", default=None, help="Comma-separated indices from last search/list")
@handle_error
def plugin_send(plugin_name, tag, collection, from_search, indices):
    """Send articles to a plugin target.

    \b
    Examples:
      scopus-for-dobby plugin send zotero --from-last-search
      scopus-for-dobby plugin send zotero --collection thesis-refs
      scopus-for-dobby plugin send zotero --indices 1,3,5
      scopus-for-dobby plugin send zotero --tag survey
    """
    from scopus_for_dobby.plugins import PLUGIN_REGISTRY
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    plugin = PLUGIN_REGISTRY.get(plugin_name)
    if not plugin:
        available = ", ".join(p.name for p in PLUGIN_REGISTRY.list_all())
        skin.error(f"Unknown plugin: {plugin_name}. Available: {available}")
        return

    # Resolve articles
    if from_search or indices:
        session = get_session()
        if indices:
            idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
            articles = session.get_entries_by_indices(idx_list)
            # Normalize raw search entries
            normalized = []
            for e in articles:
                try:
                    normalized.append(db_mod._normalize_entry(e))
                except ValueError:
                    normalized.append(e)
            articles = normalized
        else:
            entries = session.get_all_last_entries()
            articles = []
            for e in entries:
                try:
                    articles.append(db_mod._normalize_entry(e))
                except ValueError:
                    articles.append(e)
    else:
        result = db_mod.list_articles(tag=tag, collection=collection, limit=10000)
        articles = result["articles"]

    if not articles:
        skin.error("No articles to send.")
        return

    result = plugin.send(articles)
    skin.success(
        f"Sent {result.get('sent', 0)} articles to {plugin_name} (via {result.get('method', '?')})"
    )


@plugin_cmd.group("zotero")
def plugin_zotero():
    """Zotero plugin configuration."""
    pass


@plugin_zotero.command("setup")
@click.option("--user-id", required=True, help="Zotero user ID")
@click.option("--api-key", required=True, help="Zotero API key from zotero.org/settings/keys")
@handle_error
def plugin_zotero_setup(user_id, api_key):
    """Configure Zotero Web API credentials for offline use."""
    from scopus_for_dobby.plugins.zotero import ZoteroPlugin
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    result = ZoteroPlugin.setup(user_id, api_key)
    skin.success(f"Zotero Web API configured (user: {result['user_id']})")


@plugin_zotero.command("status")
@handle_error
def plugin_zotero_status():
    """Check Zotero connectivity."""
    from scopus_for_dobby.plugins import PLUGIN_REGISTRY
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    plugin = PLUGIN_REGISTRY.get("zotero")
    st = plugin.status()
    if st["ready"]:
        skin.success(st["message"])
    else:
        skin.warning(st["message"])


@plugin_zotero.command("logout")
@handle_error
def plugin_zotero_logout():
    """Remove Zotero Web API credentials."""
    from scopus_for_dobby.plugins.zotero import ZoteroPlugin
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    ZoteroPlugin.logout()
    skin.success("Zotero credentials removed.")


# ── REPL ──────────────────────────────────────────────────────────────────────


@cli.command()
@handle_error
def repl():
    """Start interactive REPL session."""
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    global _repl_mode
    _repl_mode = True

    skin = ReplSkin()
    skin.print_banner()

    pt_session = skin.create_prompt_session()

    _repl_commands = {
        "auth": "setup | upgrade | downgrade | status | logout",
        "search": "<query> [--limit N] [--sort FIELD] [--year RANGE]",
        "search-all": "<query> [--max N] — fetch multiple pages",
        "abstract": "<DOI|EID|ID> — get paper details",
        "db": "add | list | remove | tag | untag | note | info | stats",
        "author": "list | info | fetch | coauthors | note",
        "collection": "list | create | delete | add | remove",
        "export": "--format xlsx|bibtex [--collection NAME]",
        "plugin": "list | send <name> | zotero setup|status|logout",
        "help": "Show this help",
        "quit": "Exit REPL",
    }

    # Check auth on start
    try:
        status = auth_mod.get_status()
        if status.get("api_connected"):
            remaining = status.get("rate_limit_remaining")
            skin.update_quota(remaining)
            skin.success(
                f"Connected ({status.get('tier', 'free')} tier) — "
                f"quota remaining: {remaining if remaining is not None else '?'}"
            )
        elif status.get("configured"):
            skin.warning("API key configured but connection failed. Check your key.")
        else:
            skin.info("Not configured. Run: auth setup --api-key YOUR_KEY")
    except Exception:
        skin.info("Run 'auth setup --api-key YOUR_KEY' to get started.")

    # Show DB stats if populated
    try:
        st = db_mod.stats()
        if st["total_articles"] > 0:
            skin.info(
                f"Local DB: {st['total_articles']} articles, {st['total_collections']} collections"
            )
    except Exception:
        pass

    while True:
        try:
            # Build context
            session = get_session()
            ctx_parts = []
            tier = ""
            try:
                config = auth_mod.load_config()
                tier = config.get("tier", "")
            except Exception:
                pass
            if tier:
                ctx_parts.append(tier)
            if session.working_collection:
                ctx_parts.append(f"coll:{session.working_collection}")

            context = " | ".join(ctx_parts) if ctx_parts else ""

            line = skin.get_input(pt_session, context=context)
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                skin.print_goodbye()
                break
            if line.lower() == "help":
                skin.help(_repl_commands)
                continue

            # Parse and execute
            args = line.split()
            try:
                cli.main(args, standalone_mode=False)
            except SystemExit:
                pass
            except click.exceptions.UsageError as e:
                skin.warning(f"Usage: {e}")
            except Exception as e:
                skin.error(str(e))

        except (EOFError, KeyboardInterrupt):
            skin.print_goodbye()
            break

    _repl_mode = False


# ── Entry Point ───────────────────────────────────────────────────────────────


def main():
    cli()


if __name__ == "__main__":
    main()
