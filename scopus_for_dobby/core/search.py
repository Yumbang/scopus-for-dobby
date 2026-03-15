"""Scopus Search API — find papers by query, author, affiliation, etc.

Wraps: GET /content/search/scopus
Quota: 20,000/week, 9 req/sec
"""

from scopus_for_dobby.utils.api_client import api_get, load_config

# ── Field codes reference (used for smart query building) ─────────────────────

FIELD_CODES = {
    "TITLE-ABS-KEY", "TITLE", "ABS", "KEY", "AUTH", "FIRSTAUTH",
    "AFFIL", "SRCTITLE", "ISSN", "ISBN", "DOI", "PUBYEAR",
    "AU-ID", "AF-ID", "REFEID", "FUND-SPONSOR", "LANGUAGE", "DOCTYPE",
}


def _has_field_code(query: str) -> bool:
    """Check if query already contains Scopus field codes."""
    upper = query.upper()
    return any(f"{code}(" in upper or f"{code} " in upper
               for code in FIELD_CODES)


def search(
    query: str,
    count: int = 25,
    start: int = 0,
    sort: str = "relevancy",
    date: str | None = None,
    subj: str | None = None,
    view: str | None = None,
) -> dict:
    """Search Scopus for papers.

    Args:
        query: Search query. If no field codes detected, wraps in TITLE-ABS-KEY().
        count: Results per page (max 25).
        start: Zero-based offset for pagination.
        sort: Sort field (relevancy, citedby-count, -pubyear, etc.).
        date: Year range filter (e.g., '2020-2024').
        subj: Subject area code (e.g., 'COMP', 'MEDI').
        view: Override view (auto-detected from tier if None).

    Returns:
        Dict with entries list, total count, and pagination info.
    """
    # Auto-wrap in TITLE-ABS-KEY if no field codes
    if not _has_field_code(query):
        query = f"TITLE-ABS-KEY({query})"

    # Determine view from tier
    if view is None:
        config = load_config()
        view = "COMPLETE" if config.get("tier") == "institutional" else "STANDARD"

    params = {
        "query": query,
        "count": min(count, 25),
        "start": start,
        "sort": sort,
        "view": view,
    }

    if date:
        params["date"] = date
    if subj:
        params["subj"] = subj

    resp = api_get("/content/search/scopus", params=params)
    results = resp.get("search-results", {})

    entries = results.get("entry", [])
    # Filter out error entries (Scopus returns error objects in entry list)
    entries = [e for e in entries if "error" not in e]

    return {
        "total_results": int(results.get("opensearch:totalResults", 0)),
        "start_index": int(results.get("opensearch:startIndex", 0)),
        "items_per_page": int(results.get("opensearch:itemsPerPage", 0)),
        "entries": entries,
        "query": query,
        "_rate_limit": resp.get("_rate_limit"),
    }


def search_all_pages(
    query: str,
    max_results: int = 100,
    sort: str = "relevancy",
    date: str | None = None,
    subj: str | None = None,
    view: str | None = None,
    progress_callback=None,
) -> dict:
    """Fetch multiple pages of search results.

    Args:
        query: Search query.
        max_results: Maximum total results to fetch.
        sort: Sort field.
        date: Year range filter.
        subj: Subject area.
        view: Override view.
        progress_callback: Called with (fetched_count, total) after each page.

    Returns:
        Dict with all entries and total count.
    """
    all_entries = []
    start = 0
    total = None

    while True:
        page = search(
            query=query, count=25, start=start,
            sort=sort, date=date, subj=subj, view=view,
        )

        if total is None:
            total = page["total_results"]

        entries = page["entries"]
        if not entries:
            break

        all_entries.extend(entries)

        if progress_callback:
            progress_callback(len(all_entries), min(total, max_results))

        if len(all_entries) >= max_results or len(all_entries) >= total:
            break

        start += len(entries)

    all_entries = all_entries[:max_results]

    return {
        "total_results": total,
        "fetched": len(all_entries),
        "entries": all_entries,
        "query": query,
    }


def search_by_author_id(
    author_id: str,
    count: int = 25,
    start: int = 0,
    sort: str = "-pubyear",
    date: str | None = None,
) -> dict:
    """Search papers by Scopus Author ID (AU-ID).

    Args:
        author_id: Scopus Author ID.
        count: Results per page.
        start: Pagination offset.
        sort: Sort order (default: newest first).
        date: Year range filter.

    Returns:
        Search results for this author.
    """
    query = f"AU-ID({author_id})"
    return search(query=query, count=count, start=start, sort=sort, date=date)
