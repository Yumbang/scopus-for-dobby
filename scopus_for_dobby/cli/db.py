"""Local article database subcommands."""

import click

from scopus_for_dobby.core.session import get_session

from . import _client as db_mod
from ._output import handle_error, output
from ._state import state


def _resolve_eids(eid_tuple, indices, eids_from_stdin, eids_from_file) -> list[str]:
    eids = list(eid_tuple)
    if indices:
        session = get_session()
        idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        entries = session.get_entries_by_indices(idx_list)
        eids.extend(e.get("eid", "") for e in entries if e.get("eid"))
    if eids_from_file:
        with open(eids_from_file) as f:
            eids.extend(line.strip() for line in f if line.strip())
    if eids_from_stdin:
        import sys

        eids.extend(line.strip() for line in sys.stdin if line.strip())
    return [e for e in eids if e]


@click.group("db")
def db():
    """Local article database management."""


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
    else:
        entries = session.get_all_last_entries()

    if not entries:
        click.echo("No entries to add. Run a search first.", err=True)
        return

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    if collection is None and session.working_collection:
        collection = session.working_collection
        skin.info(f"Using working collection '{collection}'")

    tags = list(tag) if tag else None
    result = db_mod.add_entries(entries, tags=tags, collection=collection)

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

    if state.json_output:
        output(result)
        return

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    articles = result["articles"]
    if not articles:
        skin.warning("No articles found.")
        return

    session = get_session()
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
@click.option("--eids-from-stdin", is_flag=True, help="Read EIDs from stdin")
@click.option(
    "--eids-from-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Read EIDs from file",
)
@click.option("--confirm", is_flag=True, help="Skip confirmation")
@handle_error
def db_remove(indices, eid, eids_from_stdin, eids_from_file, confirm):
    """Remove articles from the local database."""
    eids = _resolve_eids(eid, indices, eids_from_stdin, eids_from_file)

    if not eids:
        click.echo("No articles specified for removal.", err=True)
        return

    if not confirm and not state.repl_mode and not state.json_output:
        click.confirm(f"Remove {len(eids)} article(s)?", abort=True)

    result = db_mod.remove_entries(eids)

    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Removed {result['removed']} articles ({result['total']} remaining)")


@db.command("tag")
@click.option("--indices", "-i", default=None, help="Comma-separated indices from last list/search")
@click.option("--eid", "-e", multiple=True, help="EID(s) to tag")
@click.option("--eids-from-stdin", is_flag=True, help="Read EIDs from stdin")
@click.option(
    "--eids-from-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Read EIDs from file",
)
@click.argument("tags", nargs=-1, required=True)
@handle_error
def db_tag(indices, eid, eids_from_stdin, eids_from_file, tags):
    """Add tags to articles."""
    eids = _resolve_eids(eid, indices, eids_from_stdin, eids_from_file)

    if not eids:
        click.echo("No articles specified.", err=True)
        return

    result = db_mod.tag_articles(eids, list(tags))

    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Tagged {result['tagged']} articles with: {', '.join(tags)}")


@db.command("untag")
@click.option("--indices", "-i", default=None, help="Comma-separated indices")
@click.option("--eid", "-e", multiple=True, help="EID(s)")
@click.option("--eids-from-stdin", is_flag=True, help="Read EIDs from stdin")
@click.option(
    "--eids-from-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Read EIDs from file",
)
@click.argument("tags", nargs=-1, required=True)
@handle_error
def db_untag(indices, eid, eids_from_stdin, eids_from_file, tags):
    """Remove tags from articles."""
    eids = _resolve_eids(eid, indices, eids_from_stdin, eids_from_file)

    result = db_mod.untag_articles(eids, list(tags))

    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Removed tags from {result['untagged']} articles")


@db.command("note")
@click.argument("eid")
@click.argument("note")
@handle_error
def db_note(eid, note):
    """Set a note on an article."""
    result = db_mod.set_note(eid, note)
    if state.json_output:
        output(result)
        return
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

    if state.json_output:
        output(result)
        return
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


def register(cli_group):
    cli_group.add_command(db)
