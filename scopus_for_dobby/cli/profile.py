"""``profile`` — what a set of saved papers is actually about.

Reads the controlled vocabularies already sitting in the DB
(``openalex_topics``, ``index_keywords``, ``subject_areas``) rather than doing
NLP on titles. Those fields are sparse, so every human rendering leads with
coverage: a topic list computed from a tenth of the corpus is worse than no
topic list, and the user has to see the denominator to know which they got.
"""

import click

from scopus_for_dobby.core import text_analysis as ta

from . import _client as db_mod
from ._output import handle_error, output
from ._state import state

# "Whole DB" for client-side profiling — far above any realistic library size.
_ALL = 100_000

# CLI-facing names for the vocabulary columns.
_FIELD_MAP = {
    "topics": "openalex_topics",
    "index-keywords": "index_keywords",
    "author-keywords": "keywords",
    "subjects": "subject_areas",
    # `keywords` is ambiguous — the database has both a Scopus-indexed field and
    # an author-supplied one. Kept pointing at the indexed field for anyone who
    # already typed it, but the explicit names above are what the docs use.
    "keywords": "index_keywords",
}

_FIELD_TITLES = {
    "openalex_topics": "OpenAlex topics",
    "index_keywords": "Scopus index keywords",
    "subject_areas": "Scopus subject areas",
    "keywords": "Author keywords",
}

# Below this share of the corpus, the profile describes a minority of the papers
# and gets a warning before anyone reads a number off it.
_LOW_COVERAGE = 0.5


def _pct(share: float) -> str:
    return f"{share * 100:.0f}%"


@click.command("profile")
@click.argument("eids", nargs=-1)
@click.option("--collection", "-c", default=None, help="Profile one collection")
@click.option(
    "--project",
    "-p",
    default=None,
    help="Profile every collection in a project (deduplicated); excludes --collection",
)
@click.option("--tag", "-t", default=None, help="Profile articles with this tag")
@click.option(
    "--field",
    "-f",
    type=click.Choice(
        ["auto", "topics", "index-keywords", "author-keywords", "subjects", "keywords"]
    ),
    default="auto",
    help="Vocabulary to profile (default: auto — the best-covered one)",
)
@click.option("--top", "-n", type=int, default=15, help="Entries per section")
@click.option("--terms", is_flag=True, help="Also count title terms (words and bigrams)")
@click.option("--co-occurrence", is_flag=True, help="Also show label pairs sharing an article")
@handle_error
def profile(eids, collection, project, tag, field, top, terms, co_occurrence):
    """Profile what a set of saved articles is about.

    Counts the curated vocabularies Scopus and OpenAlex already attached to the
    articles. Coverage is reported first, because these fields only appear after
    `openalex enrich` (topics) or an abstract fetch (index keywords, subjects).

    \b
    Examples:
      scopus-for-dobby profile
      scopus-for-dobby profile --collection thesis --terms
      scopus-for-dobby profile --project thesis
      scopus-for-dobby profile --tag ml --field topics --co-occurrence
      scopus-for-dobby --json profile --collection thesis
    """
    if project and collection:
        raise click.UsageError("Pass either --project or --collection, not both.")

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    if eids:
        articles = [db_mod.get_article(e) for e in eids]
    else:
        articles = db_mod.list_articles(
            tag=tag, collection=collection, project=project, limit=_ALL
        )["articles"]

    cov = ta.coverage(articles)
    result = {
        "articles": len(articles),
        "scope": {"collection": collection, "project": project, "tag": tag, "eids": list(eids)},
        # Filled in below; declared up front so the JSON shape does not change
        # when the corpus is empty.
        "field": {"requested": field, "chosen": None, "coverage": 0.0, "note": None},
        "coverage": cov,
        "years": ta.year_distribution(articles),
    }

    if not articles:
        if state.json_output:
            output(result)
        else:
            skin.warning("No articles matched — nothing to profile.")
        return

    # Resolve the vocabulary. ``auto`` may find nothing at all, in which case
    # free-text terms are the only signal left and we switch to them rather than
    # printing an empty table.
    chosen = None
    auto_note = None
    if field == "auto":
        pick = ta.best_field(articles)
        chosen = pick["field"]
        if chosen:
            auto_note = f"Auto-selected {chosen} — {_pct(pick['coverage'])} coverage"
        else:
            auto_note = "No controlled vocabulary present — falling back to title terms"
            terms = True
    else:
        chosen = _FIELD_MAP[field]

    result["field"] = {
        "requested": field,
        "chosen": chosen,
        "coverage": cov["fields"].get(chosen, {}).get("share", 0.0) if chosen else 0.0,
        "note": auto_note,
    }

    if chosen:
        result["profile"] = ta.vocabulary_profile(articles, field=chosen, top=top)
        if co_occurrence:
            result["co_occurrence"] = ta.co_occurrence(
                articles, field=chosen, min_count=2, top=top
            )
    if terms:
        result["terms"] = {
            "words": ta.term_frequency(articles, fields=("title",), top=top),
            "bigrams": ta.term_frequency(articles, fields=("title",), top=top, ngram=2),
        }

    if state.json_output:
        output(result)
        return

    _render(skin, result, top)


def _render(skin, result, top):
    total = result["articles"]

    skin.section("Corpus Profile")
    scope = result["scope"]
    where = scope["collection"] and f"collection '{scope['collection']}'"
    where = where or (scope.get("project") and f"project '{scope['project']}'")
    where = where or (scope["tag"] and f"tag '{scope['tag']}'")
    where = where or (scope["eids"] and f"{len(scope['eids'])} named article(s)")
    skin.status("Articles", f"{total}" + (f" ({where})" if where else " (whole library)"))

    years = result["years"]
    if years["with_year"]:
        span = f"{years['earliest']}-{years['latest']}, median {years['median']}"
        if years["missing"]:
            span += f" ({years['missing']} without a usable date)"
        skin.status("Years", span)

    # Coverage first — every number below is a share of one of these denominators.
    skin.section("Field coverage")
    for name, stat in result["coverage"]["fields"].items():
        skin.status(f"  {name}", f"{stat['count']}/{total} ({_pct(stat['share'])})")

    field = result.get("field", {})
    note = field.get("note")
    if note:
        skin.info(note)

    prof = result.get("profile")
    if prof:
        if prof["with_field"] == 0:
            skin.warning(
                f"No article carries {prof['field']} — nothing to profile. "
                "Run `openalex enrich` for topics, or fetch abstracts for keywords/subjects."
            )
        else:
            if prof["coverage"] < _LOW_COVERAGE:
                skin.warning(
                    f"Only {_pct(prof['coverage'])} coverage: the profile below describes "
                    f"{prof['with_field']} of {total} articles, not the corpus."
                )
            title = _FIELD_TITLES.get(prof["field"], prof["field"])
            skin.section(f"{title} ({prof['distinct']} distinct)")
            skin.hint(f"  share of the {prof['with_field']} article(s) carrying this field")
            skin.table(
                ["#", "Label", "Articles", "Share"],
                [
                    [str(i), row["label"], str(row["count"]), _pct(row["share"])]
                    for i, row in enumerate(prof["labels"], 1)
                ],
            )

    co = result.get("co_occurrence")
    if co is not None:
        skin.section("Co-occurring labels")
        if not co["pairs"]:
            skin.hint("  no label pair appears on 2+ articles")
        else:
            skin.table(
                ["Label A", "Label B", "Together", "Jaccard"],
                [
                    [p["a"], p["b"], str(p["count"]), f"{p['jaccard']:.2f}"]
                    for p in co["pairs"]
                ],
            )

    term_blocks = result.get("terms")
    if term_blocks:
        for label, block in (("Title words", "words"), ("Title bigrams", "bigrams")):
            data = term_blocks[block]
            skin.section(f"{label} (from {data['with_text']} of {total} articles)")
            if not data["terms"]:
                skin.hint("  nothing above the stopword filter")
                continue
            skin.table(
                ["Term", "Articles", "Share"],
                [
                    [row["term"], str(row["count"]), _pct(row["share"])]
                    for row in data["terms"]
                ],
            )

    print()
    skin.hint(f"  Showing up to {top} entries per section — raise it with --top.")


def register(cli_group):
    cli_group.add_command(profile)
