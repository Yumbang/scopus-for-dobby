"""Export subcommand."""

from datetime import datetime

import click

from scopus_for_dobby.core import export as export_mod
from scopus_for_dobby.core.session import get_session

from . import _client as db_mod
from ._output import handle_error, output
from ._state import state

# Same "whole library" ceiling as profile, fulltext, and openalex. A fourth
# copy on purpose — folding them into one helper is a separate cleanup.
_ALL = 100_000


def _export_empty(fmt: str, human: str, reason: str) -> None:
    """Nothing to write. JSON gets a payload; the human path keeps its error line."""
    if state.json_output:
        output({"exported": 0, "format": fmt, "output": None, "reason": reason})
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    ReplSkin().error(human)


@click.command("export")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["xlsx", "bibtex", "ris"]),
    default="xlsx",
    help="Export format",
)
@click.option("--output", "-o", "output_path", default=None, help="Output file path")
@click.option("--tag", "-t", default=None, help="Export only articles with this tag")
@click.option("--collection", "-c", default=None, help="Export only this collection")
@click.option(
    "--from-last-search",
    "from_search",
    is_flag=True,
    help="Export last search results (not from DB)",
)
@handle_error
def export_cmd(fmt, output_path, tag, collection, from_search):
    """Export articles to XLSX, BibTeX, or RIS.

    By default, exports from the local database. Use --from-last-search
    to export the current search results directly.

    \b
    Examples:
      scopus-for-dobby export --format xlsx -o papers.xlsx
      scopus-for-dobby export --format bibtex --collection thesis-refs
      scopus-for-dobby export --from-last-search --format bibtex -o refs.bib
    """
    # Counts exist only for a database read. --from-last-search has neither.
    counts = None

    if from_search:
        session = get_session()
        entries = session.get_all_last_entries()
        if not entries:
            _export_empty(
                fmt,
                "No search results to export. Run a search first.",
                "no search results",
            )
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
                if not state.json_output:
                    from scopus_for_dobby.utils.repl_skin import ReplSkin

                    ReplSkin().info(f"Using working collection '{collection}'")
        listed = db_mod.list_articles(tag=tag, collection=collection, limit=_ALL)
        articles = listed["articles"]
        counts = (listed["total_matching"], listed["total_in_db"])

    if not articles:
        _export_empty(fmt, "No articles to export.", "no articles")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "xlsx":
        out = output_path or f"scopus_export_{ts}.xlsx"
        if not out.endswith(".xlsx"):
            out += ".xlsx"
        result = export_mod.export_xlsx(articles, out)
    elif fmt == "bibtex":
        out = output_path or f"scopus_export_{ts}.bib"
        if not out.endswith(".bib"):
            out += ".bib"
        result = export_mod.export_bibtex(articles, out)
    else:
        out = output_path or f"scopus_export_{ts}.ris"
        if not out.endswith(".ris"):
            out += ".ris"
        result = export_mod.export_ris(articles, out)

    payload = {
        "exported": result["exported"],
        "format": result["format"],
        "output": result["output"],
    }
    if "tier" in result:
        payload["tier"] = result["tier"]
    truncated = False
    if counts is not None:
        total_matching, total_in_db = counts
        payload["total_matching"] = total_matching
        payload["total_in_db"] = total_in_db
        truncated = total_matching > len(articles)
        if truncated:
            payload["truncated"] = True

    if state.json_output:
        output(payload)
        return

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Exported {result['exported']} articles to {result['output']}")
    if truncated:
        total_matching, total_in_db = counts
        skin.warning(
            f"Exported {len(articles)} of {total_matching} matching ({total_in_db} total in DB)"
        )


def register(cli_group):
    cli_group.add_command(export_cmd)
