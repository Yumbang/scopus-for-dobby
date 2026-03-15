"""Abstract Retrieval API — get detailed metadata for a single paper.

Wraps: GET /content/abstract/{doi|eid|scopus_id}
Quota: 10,000/week, 9 req/sec
"""

from scopus_for_dobby.utils.api_client import api_get, load_config


def retrieve_by_doi(doi: str, view: str | None = None) -> dict:
    """Retrieve paper metadata by DOI.

    Args:
        doi: Digital Object Identifier.
        view: Override view (META, META_ABS, FULL, REF, ENTITLED).

    Returns:
        Formatted paper metadata.
    """
    return _retrieve(f"/content/abstract/doi/{doi}", view)


def retrieve_by_eid(eid: str, view: str | None = None) -> dict:
    """Retrieve paper metadata by EID.

    Args:
        eid: Scopus EID (e.g., '2-s2.0-85012345678').
        view: Override view.

    Returns:
        Formatted paper metadata.
    """
    return _retrieve(f"/content/abstract/eid/{eid}", view)


def retrieve_by_scopus_id(scopus_id: str, view: str | None = None) -> dict:
    """Retrieve paper metadata by Scopus ID.

    Args:
        scopus_id: Scopus document ID.
        view: Override view.

    Returns:
        Formatted paper metadata.
    """
    return _retrieve(f"/content/abstract/scopus_id/{scopus_id}", view)


def retrieve(identifier: str, view: str | None = None) -> dict:
    """Auto-detect identifier type and retrieve.

    Detects DOI (contains '/'), EID (starts with '2-s2.0-'), or Scopus ID.

    Args:
        identifier: DOI, EID, or Scopus ID.
        view: Override view.

    Returns:
        Formatted paper metadata.
    """
    identifier = identifier.strip()
    if identifier.startswith("2-s2.0-"):
        return retrieve_by_eid(identifier, view)
    elif "/" in identifier:
        return retrieve_by_doi(identifier, view)
    else:
        return retrieve_by_scopus_id(identifier, view)


def _retrieve(endpoint: str, view: str | None = None) -> dict:
    """Internal retrieval with auto view detection."""
    if view is None:
        config = load_config()
        view = "FULL" if config.get("tier") == "institutional" else "META"

    params = {"view": view}
    resp = api_get(endpoint, params=params)

    raw = resp.get("abstracts-retrieval-response", {})
    core = raw.get("coredata", {})
    affs = raw.get("affiliation", [])
    authors_block = raw.get("authors", {})

    result = _format_paper(core, affs, authors_block, raw)
    result["_raw"] = raw
    result["_rate_limit"] = resp.get("_rate_limit")
    return result


def _format_paper(core: dict, affs: list | dict, authors_block: dict,
                  raw: dict | None = None) -> dict:
    """Format abstract retrieval response into a clean dict."""
    # First author
    creator = core.get("dc:creator", "")
    first_author = ""
    first_author_auid = ""
    if isinstance(creator, dict):
        authors = creator.get("author", [])
        if authors:
            pn = authors[0].get("preferred-name", {})
            first_author = pn.get("ce:indexed-name", "")
            first_author_auid = authors[0].get("@auid", "")
    elif isinstance(creator, str):
        first_author = creator

    # Scopus ID
    sid = core.get("dc:identifier", "")
    scopus_id = str(sid).replace("SCOPUS_ID:", "") if sid else ""

    # Affiliations
    aff_list = []
    if isinstance(affs, list):
        for a in affs:
            aff_list.append({
                "name": a.get("affilname", ""),
                "city": a.get("affiliation-city", ""),
                "country": a.get("affiliation-country", ""),
            })

    # All authors (institutional only)
    all_authors = []
    if isinstance(authors_block, dict):
        for a in authors_block.get("author", []):
            pn = a.get("preferred-name", {})
            all_authors.append({
                "name": pn.get("ce:indexed-name", ""),
                "auid": a.get("@auid", ""),
                "seq": a.get("@seq", ""),
            })

    # Author keywords (from coredata)
    auth_keywords = core.get("authkeywords", "")

    # Index keywords (Scopus-assigned, from top-level idxterms)
    index_keywords = []
    if raw:
        idxterms = raw.get("idxterms", {})
        if isinstance(idxterms, dict):
            for term in idxterms.get("mainterm", []):
                if isinstance(term, dict):
                    index_keywords.append(term.get("$", ""))
                elif isinstance(term, str):
                    index_keywords.append(term)

    # Subject areas (from top-level subject-areas)
    subject_areas = []
    if raw:
        subj_block = raw.get("subject-areas", {})
        if isinstance(subj_block, dict):
            for area in subj_block.get("subject-area", []):
                if isinstance(area, dict):
                    subject_areas.append({
                        "name": area.get("$", ""),
                        "code": area.get("@code", ""),
                        "abbrev": area.get("@abbrev", ""),
                    })

    # Corresponding authors (from item.bibrecord.head.correspondence)
    corresponding_authors = []
    if raw:
        item = raw.get("item", {})
        bib = item.get("bibrecord", {}) if isinstance(item, dict) else {}
        head = bib.get("head", {}) if isinstance(bib, dict) else {}
        corr = head.get("correspondence", {}) if isinstance(head, dict) else {}
        if isinstance(corr, dict):
            corr = [corr]
        if isinstance(corr, list):
            for c in corr:
                person = c.get("person", {})
                if isinstance(person, dict):
                    cname = person.get("ce:indexed-name", "")
                    if cname:
                        corresponding_authors.append(cname)

    return {
        "title": core.get("dc:title", ""),
        "first_author": first_author,
        "first_author_auid": first_author_auid,
        "all_authors": all_authors,
        "journal": core.get("prism:publicationName", ""),
        "volume": core.get("prism:volume", ""),
        "issue": core.get("prism:issueIdentifier", ""),
        "pages": core.get("prism:pageRange", "") or core.get("article-number", ""),
        "cover_date": core.get("prism:coverDate", ""),
        "doi": core.get("prism:doi", ""),
        "eid": core.get("eid", ""),
        "scopus_id": scopus_id,
        "cited_by": core.get("citedby-count", "0"),
        "open_access": str(core.get("openaccess", "0")) == "1",
        "abstract": core.get("dc:description", ""),
        "keywords": auth_keywords,
        "index_keywords": index_keywords,
        "subject_areas": subject_areas,
        "issn": core.get("prism:issn", ""),
        "source_type": core.get("prism:aggregationType", ""),
        "affiliations": aff_list,
        "corresponding_authors": corresponding_authors,
    }
