"""Search and abstract retrieval subcommands."""

import click

from scopus_for_dobby.core import abstract as abstract_mod
from scopus_for_dobby.core import search as search_mod
from scopus_for_dobby.core.session import get_session

from . import _client as db_mod
from ._output import handle_error


@click.command("search")
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


@click.command("search-all")
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

    if not no_save and entries:
        tags = list(tag) if tag else None
        db_result = db_mod.add_entries(entries, tags=tags, collection=collection)
        skin.success(
            f"Auto-saved: {db_result['added']} new, "
            f"{db_result['updated']} updated "
            f"({db_result['total']} total in DB)"
        )


@click.command("abstract")
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

    db_result = db_mod.add_entries([result])
    if db_result["updated"]:
        skin.success("DB entry updated with enriched metadata")
    elif db_result["added"]:
        skin.success("Saved to DB")

    missing = []
    if not result.get("abstract"):
        missing.append("abstract")
    if not result.get("all_authors"):
        missing.append("full author list")
    if missing:
        print()
        skin.hint(f"Not available: {', '.join(missing)} (requires institutional key)")


def register(cli_group):
    cli_group.add_command(search_cmd)
    cli_group.add_command(search_all_cmd)
    cli_group.add_command(abstract_cmd)
