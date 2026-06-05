"""Export subcommand."""

from datetime import datetime

import click

from scopus_for_dobby.core import export as export_mod
from scopus_for_dobby.core.session import get_session

from . import _client as db_mod
from ._output import handle_error


@click.command("export")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["xlsx", "bibtex", "ris"]),
    default="xlsx",
    help="Export format",
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
        articles = []
        for e in entries:
            try:
                articles.append(db_mod._normalize_entry(e))
            except ValueError:
                articles.append(e)
    else:
        if collection is None:
            session = get_session()
            if session.working_collection:
                collection = session.working_collection
                skin.info(f"Using working collection '{collection}'")
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


def register(cli_group):
    cli_group.add_command(export_cmd)
