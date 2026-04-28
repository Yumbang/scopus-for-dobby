"""Author database subcommands."""

import click

from . import _client as db_mod
from ._output import handle_error


@click.group("author")
def author_cmd():
    """Author database — auto-populated from article data."""


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


def register(cli_group):
    cli_group.add_command(author_cmd)
