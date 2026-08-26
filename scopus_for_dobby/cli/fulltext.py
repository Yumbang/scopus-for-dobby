"""Elsevier full-text fetch — cache XML locally, stamp the library.

Batch-friendly: a closed paper is one miss, not a failed run. Sources are
either a DuckDB pipeline (collection / tag / query) or explicit identifiers
(EID, DOI, Scopus ID, last-search indices, stdin, file).
"""

from __future__ import annotations

import sys

import click

from scopus_for_dobby.core import fulltext as ft
from scopus_for_dobby.core.session import get_session

from . import _client as db_mod
from ._output import handle_error, output
from ._state import state

_ALL = 100_000


def _articles_from_pipeline(collection, tag, query, limit) -> list[dict]:
    n = limit if limit is not None else _ALL
    return db_mod.list_articles(tag=tag, collection=collection, query=query, sort="added", limit=n)[
        "articles"
    ]


def _eids_from_indices(indices: str) -> list[str]:
    session = get_session()
    idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
    entries = session.get_entries_by_indices(idx_list)
    return [e.get("eid", "") for e in entries if e.get("eid")]


def _eids_from_file(path: str) -> list[str]:
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def _eids_from_stdin() -> list[str]:
    return [line.strip() for line in sys.stdin if line.strip()]


def resolve_items(
    identifiers: tuple[str, ...],
    *,
    collection: str | None,
    tag: str | None,
    query: str | None,
    indices: str | None,
    eids_from_file: str | None,
    eids_from_stdin: bool,
    limit: int | None,
) -> list[dict]:
    """Union pipeline rows and explicit identifiers; de-dupe by EID/DOI."""
    items: list[dict] = []
    seen: set[str] = set()

    def _add(item: dict) -> None:
        key = (item.get("eid") or "") or (item.get("doi") or "") or (item.get("identifier") or "")
        if not key or key in seen:
            return
        seen.add(key)
        items.append(item)

    if collection or tag or query:
        for article in _articles_from_pipeline(collection, tag, query, limit):
            _add(ft.item_from_article(article))

    idents: list[str] = list(identifiers)
    if indices:
        idents.extend(_eids_from_indices(indices))
    if eids_from_file:
        idents.extend(_eids_from_file(eids_from_file))
    if eids_from_stdin:
        idents.extend(_eids_from_stdin())

    for ident in idents:
        article = db_mod.lookup_article(ident)
        _add(ft.item_from_identifier(ident, article))

    if limit is not None:
        items = items[:limit]
    return items


def _stamp_if_in_db(row: dict) -> None:
    if row.get("status") not in (ft.STATUS_FETCHED, ft.STATUS_CACHED):
        return
    eid = row.get("eid") or ""
    if not eid:
        return
    db_mod.record_fulltext_fetch(eid, roles=row.get("roles"))


@click.command("fulltext")
@click.argument("identifiers", nargs=-1)
@click.option("--collection", "-c", default=None, help="All articles in this collection")
@click.option("--tag", "-t", default=None, help="All articles with this tag")
@click.option("--query", "-q", default=None, help="Text search over the local library")
@click.option(
    "--indices",
    "-i",
    default=None,
    help="Comma-separated indices from last search/list (e.g. 1,3,5)",
)
@click.option("--eids-from-file", type=click.Path(exists=True), default=None)
@click.option("--eids-from-stdin", is_flag=True, help="Read identifiers from stdin, one per line")
@click.option("--force", is_flag=True, help="Re-fetch even when a local XML cache exists")
@click.option("--limit", "-n", type=int, default=None, help="Cap the resolved batch")
@handle_error
def fulltext_cmd(
    identifiers,
    collection,
    tag,
    query,
    indices,
    eids_from_file,
    eids_from_stdin,
    force,
    limit,
):
    """Fetch Elsevier full text into a local markdown bundle.

    Closed / unsubscribed papers fail per item — the rest of the batch
    continues. Cached XML is reused unless --force. Batches run
    sequentially (Article Retrieval is 10 req/s; parallelism does not help).
    Each paper is a directory: xml/article.xml, manifest.json, head.md, sections/.

    \b
    Examples:
      scopus-for-dobby fulltext 10.1016/j.watres.2026.125855
      scopus-for-dobby fulltext --collection thesis-refs
      scopus-for-dobby fulltext 2-s2.0-105035063878 2-s2.0-85012345678
      scopus-for-dobby --json db list -c thesis-refs -n 1000 \\
        | jq -r '.articles[].eid' | scopus-for-dobby fulltext --eids-from-stdin
    """
    if not (
        identifiers or collection or tag or query or indices or eids_from_file or eids_from_stdin
    ):
        raise click.UsageError(
            "Provide identifiers (DOI / EID / Scopus ID), --indices, "
            "--eids-from-file / --eids-from-stdin, or a DuckDB pipeline "
            "(--collection / --tag / --query)."
        )

    items = resolve_items(
        identifiers,
        collection=collection,
        tag=tag,
        query=query,
        indices=indices,
        eids_from_file=eids_from_file,
        eids_from_stdin=eids_from_stdin,
        limit=limit,
    )
    if not items:
        raise click.UsageError("No articles resolved from those arguments.")

    batch = ft.fetch_batch(items, force=force)
    for row in batch["items"]:
        _stamp_if_in_db(row)

    summary = {
        "total": batch["total"],
        "counts": batch["counts"],
        "items": [
            {
                "eid": r.get("eid"),
                "doi": r.get("doi"),
                "status": r.get("status"),
                "path": r.get("path") or None,
                "reason": r.get("reason") or None,
                "in_db": r.get("in_db"),
                "oa_url": r.get("oa_url") or None,
                "outline": r.get("outline") or None,
            }
            for r in batch["items"]
        ],
    }

    if state.json_output:
        output(summary)
        return

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    counts = batch["counts"]
    fetched = counts.get(ft.STATUS_FETCHED, 0)
    cached = counts.get(ft.STATUS_CACHED, 0)
    miss = (
        counts.get(ft.STATUS_NOT_ENTITLED, 0)
        + counts.get(ft.STATUS_NOT_FOUND, 0)
        + counts.get(ft.STATUS_NO_IDENTIFIER, 0)
        + counts.get(ft.STATUS_ERROR, 0)
        + counts.get(ft.STATUS_SKIPPED_QUOTA, 0)
    )
    skin.success(
        f"Full text: {fetched} fetched, {cached} cached, {miss} missed ({batch['total']} total)"
    )
    if counts.get(ft.STATUS_NOT_ENTITLED):
        skin.hint(
            f"     {counts[ft.STATUS_NOT_ENTITLED]} not entitled "
            "(closed paper or this subscription cannot read it)"
        )
    if counts.get(ft.STATUS_SKIPPED_QUOTA):
        skin.hint(
            f"     {counts[ft.STATUS_SKIPPED_QUOTA]} skipped — "
            "Article Retrieval weekly quota exhausted"
        )
    for r in batch["items"]:
        if r["status"] in (ft.STATUS_FETCHED, ft.STATUS_CACHED):
            continue
        label = r.get("eid") or r.get("doi") or "?"
        reason = r.get("reason") or r["status"]
        skin.warning(f"  {label}: {r['status']} — {reason}")


def register(cli_group):
    cli_group.add_command(fulltext_cmd)
