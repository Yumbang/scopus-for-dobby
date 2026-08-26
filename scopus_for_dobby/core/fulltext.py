"""Elsevier Article Retrieval — full-text XML, local cache, author-role parse.

Wraps ``GET /content/article/{doi|scopus_id}/...`` (ScienceDirect Article
Retrieval, not Scopus Abstract Retrieval). Full text is entitlement-gated:
a 401/403 on one paper is a per-item miss, not a batch abort.

Each paper is a directory ``~/.scopus-for-dobby/fulltext/<eid>/`` with
XML under ``xml/article.xml`` plus markdown/assets from :mod:`fulltext_bundle`.
DuckDB
only stores a fetch stamp and, when footnotes parse, author-role flags.
The body is never written into ``articles.abstract``.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path
from xml.etree import ElementTree as ET

from scopus_for_dobby.core.fulltext_bundle import BUNDLE_VERSION, materialize
from scopus_for_dobby.utils.api_client import (
    CONFIG_DIR,
    QuotaExceeded,
    request_elsevier,
)

CACHE_DIRNAME = "fulltext"

# Statuses a batch item can land in. ``skipped_quota`` is applied to the
# remainder of a batch after HTTP 429 — that one *does* stop the loop.
STATUS_CACHED = "cached"
STATUS_FETCHED = "fetched"
STATUS_NOT_ENTITLED = "not_entitled"
STATUS_NOT_FOUND = "not_found"
STATUS_NO_IDENTIFIER = "no_identifier"
STATUS_ERROR = "error"
STATUS_SKIPPED_QUOTA = "skipped_quota"

_EQUAL_RE = re.compile(
    r"contributed equally|equal(?:ly)? contribut|joint first|co-?first",
    re.I,
)
_CORR_RE = re.compile(r"corresponding author", re.I)
_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")


def _cache_root() -> Path:
    path = CONFIG_DIR / CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = _cache_root()
    migrate_cache_layout()
    return path


def _safe_eid(eid: str) -> str:
    return _SAFE_KEY.sub("_", (eid or "").strip()) or "unknown"


def bundle_dir(eid: str) -> Path:
    """On-disk directory for one paper's XML + markdown bundle."""
    return _cache_root() / _safe_eid(eid)


SOURCE_REL = "xml/article.xml"


def source_path(eid: str) -> Path:
    return bundle_dir(eid) / SOURCE_REL


def legacy_xml_path(eid: str) -> Path:
    return _cache_root() / f"{_safe_eid(eid)}.xml"


def cache_path(eid: str) -> Path:
    """Directory for the paper bundle (legacy name kept for callers)."""
    return bundle_dir(eid)


def _relocate(src: Path, dest: Path) -> None:
    if not src.is_file() or dest.is_file() or src.resolve() == dest.resolve():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)
    dest.chmod(0o600)


def migrate_legacy_xml(eid: str) -> None:
    """Tuck leftover XML into ``fulltext/<eid>/xml/article.xml``."""
    dest = source_path(eid)
    _relocate(legacy_xml_path(eid), dest)
    _relocate(bundle_dir(eid) / "source.xml", dest)


def migrate_cache_layout() -> None:
    """Move every top-level ``*.xml`` and old ``source.xml`` into ``xml/``."""
    root = _cache_root()
    if not root.is_dir():
        return
    for p in root.glob("*.xml"):
        if p.is_file():
            migrate_legacy_xml(p.stem)
    for d in root.iterdir():
        if d.is_dir():
            _relocate(d / "source.xml", d / SOURCE_REL)


def has_cache(eid: str) -> bool:
    if not eid:
        return False
    migrate_legacy_xml(eid)
    path = source_path(eid)
    return path.is_file() and path.stat().st_size > 0


def read_cache(eid: str) -> str | None:
    migrate_legacy_xml(eid)
    path = source_path(eid)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def write_source(eid: str, xml: str) -> Path:
    dest = bundle_dir(eid)
    dest.mkdir(parents=True, exist_ok=True)
    dest.chmod(0o700)
    path = source_path(eid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    path.chmod(0o600)
    return dest


def write_cache(eid: str, xml: str, *, doi: str = "") -> Path:
    """Write XML and materialize markdown/assets. Returns the bundle directory."""
    dest = write_source(eid, xml)
    materialize(xml, dest, eid=eid, doi=doi)
    return dest


INDEX_NAME = "index.json"


def _index_path() -> Path:
    return _cache_root() / INDEX_NAME


def _load_index() -> dict:
    path = _index_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def index_doi(doi: str | None, eid: str) -> None:
    """Remember which bundle holds a DOI, so a later DOI-only fetch is a cache hit.

    A paper fetched by DOI lands under the EID its XML carries, which a DOI
    alone cannot reconstruct. Without this map every ``fulltext <doi>`` for a
    paper outside the library would re-spend quota on an article already on disk.
    """
    key = normalize_doi(doi)
    if not key or not eid:
        return
    index = _load_index()
    if index.get(key) == eid:
        return
    index[key] = eid
    path = _index_path()
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _scan_manifests_for_doi(doi: str) -> str:
    """Recover a DOI→EID mapping from bundles written before the index existed."""
    root = _cache_root()
    if not root.is_dir():
        return ""
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        manifest = d / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if normalize_doi(data.get("doi")) == doi:
            return data.get("eid") or d.name
    return ""


def cached_eid_for(item: dict) -> str:
    """EID of the bundle already holding this item's XML, or ``""``."""
    eid = (item.get("eid") or "").strip()
    if eid and has_cache(eid):
        return eid
    doi = normalize_doi(item.get("doi"))
    if not doi:
        return ""
    candidate = _load_index().get(doi) or ""
    if candidate and has_cache(candidate):
        return candidate
    candidate = _scan_manifests_for_doi(doi)
    if candidate and has_cache(candidate):
        index_doi(doi, candidate)
        return candidate
    return ""


def discard_cache(eid: str) -> None:
    """Delete a bundle whose XML cannot be parsed, so the next fetch can heal it."""
    dest = bundle_dir(eid)
    root = _cache_root().resolve()
    try:
        if dest.resolve().parent != root or not dest.is_dir():
            return
    except OSError:
        return
    shutil.rmtree(dest, ignore_errors=True)


def json_manifest(dest: Path) -> dict | None:
    path = dest / "manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_bundle(eid: str, xml: str, *, doi: str = "") -> dict:
    """Materialize markdown/assets if ``manifest.json`` is missing."""
    dest = bundle_dir(eid)
    manifest_path = dest / "manifest.json"
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if existing.get("parser") == BUNDLE_VERSION:
            return existing
    return materialize(xml, dest, eid=eid, doi=doi)


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi or None


def article_endpoint(item: dict) -> str | None:
    """Pick the Article Retrieval path for a resolved item. None if unusable."""
    doi = normalize_doi(item.get("doi") or "")
    if doi:
        return f"/content/article/doi/{doi}"
    sid = (item.get("scopus_id") or "").strip()
    if sid.startswith("SCOPUS_ID:"):
        sid = sid[len("SCOPUS_ID:") :]
    if sid:
        return f"/content/article/scopus_id/{sid}"
    ident = (item.get("identifier") or item.get("eid") or "").strip()
    if ident.startswith("2-s2.0-"):
        return f"/content/article/scopus_id/{ident[7:]}"
    if "/" in ident:
        doi = normalize_doi(ident)
        return f"/content/article/doi/{doi}" if doi else None
    if ident:
        return f"/content/article/scopus_id/{ident}"
    return None


def looks_like_fulltext(xml: str) -> bool:
    """True when the payload carries article body, not abstract-only META."""
    if not xml:
        return False
    head = xml[:2000].lstrip()
    if head.startswith("{") or "<service-error" in xml or "<error-response" in xml:
        return False
    markers = (
        "<ce:sections",
        "<xocs:rawtext",
        "<originalText",
        "ce:sections",
        "xocs:rawtext",
    )
    return any(m in xml for m in markers)


def _parse_xml(xml: str) -> ET.Element:
    """Parse Elsevier Article Retrieval XML.

    The payload is fetched over TLS from api.elsevier.com with our key, or
    reread from the cache we wrote ourselves. Not user-supplied markup.
    """
    return ET.fromstring(xml)  # noqa: S314


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text_of(el: ET.Element) -> str:
    return "".join(el.itertext()).strip()


def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def parse_roles(xml: str) -> dict:
    """Extract co-first / corresponding authors from Elsevier full-text XML.

    Returns ``{first_auids, first_names, corr_auids, corr_names}``. Empty
    lists mean the footnotes were not found — callers must not wipe existing
    flags in that case.
    """
    empty = {
        "first_auids": [],
        "first_names": [],
        "corr_auids": [],
        "corr_names": [],
    }
    if not xml or not looks_like_fulltext(xml):
        return empty
    try:
        root = _parse_xml(xml)
    except ET.ParseError:
        return _roles_from_flat_text(xml)

    footnotes: dict[str, str] = {}
    authors: list[dict] = []

    for el in root.iter():
        name = _local(el.tag)
        if name in {"footnote", "note-para", "textfn"}:
            fid = el.get("id") or el.get("{http://www.w3.org/XML/1998/namespace}id")
            if fid:
                footnotes[fid] = _text_of(el)
            elif name == "note-para" and el.get("id"):
                footnotes[el.get("id")] = _text_of(el)
        if name == "correspondence":
            fid = el.get("id") or "correspondence"
            footnotes[fid] = _text_of(el)
        if name == "author":
            authors.append(_author_from_el(el))

    # Footnotes nested as children without id on the para: walk again for
    # <ce:footnote id="fn1"><ce:note-para>...</ce:note-para></ce:footnote>
    for el in root.iter():
        if _local(el.tag) != "footnote":
            continue
        fid = el.get("id")
        if fid and fid not in footnotes:
            footnotes[fid] = _text_of(el)

    equal_ids = {fid for fid, text in footnotes.items() if _EQUAL_RE.search(text or "")}
    corr_ids = {fid for fid, text in footnotes.items() if _CORR_RE.search(text or "")}

    first_auids, first_names = [], []
    corr_auids, corr_names = [], []
    for a in authors:
        refs = set(a.get("refs") or [])
        if equal_ids & refs:
            if a.get("auid"):
                first_auids.append(a["auid"])
            if a.get("name"):
                first_names.append(a["name"])
        if corr_ids & refs or a.get("is_corresponding"):
            if a.get("auid"):
                corr_auids.append(a["auid"])
            if a.get("name"):
                corr_names.append(a["name"])

    if not (first_names or corr_names):
        flat = _roles_from_flat_text(xml)
        if flat["first_names"] or flat["corr_names"]:
            return flat

    return {
        "first_auids": first_auids,
        "first_names": first_names,
        "corr_auids": corr_auids,
        "corr_names": corr_names,
    }


def _author_from_el(el: ET.Element) -> dict:
    auid = (
        el.get("author-id")
        or el.get("auid")
        or el.get("{http://www.elsevier.com/xml/common/dtd}author-id")
        or ""
    )
    given = surname = indexed = ""
    refs: list[str] = []
    is_corr = False
    for child in el.iter():
        loc = _local(child.tag)
        if loc == "given-name" and not given:
            given = _text_of(child)
        elif loc == "surname" and not surname:
            surname = _text_of(child)
        elif loc == "indexed-name" and not indexed:
            indexed = _text_of(child)
        elif loc in {"cross-ref", "cross-out"}:
            refid = child.get("refid") or child.get("id") or ""
            if refid:
                refs.append(refid)
        elif loc == "e-address":
            is_corr = True
    if not auid:
        auid = el.get("id") or ""
        # ce:author id="au1" is not a Scopus AUID — drop non-numeric ids.
        if auid and not auid.isdigit():
            auid = ""
    name = indexed or " ".join(p for p in (given, surname) if p).strip()
    if given and surname and not indexed:
        # Match Scopus indexed-name shape: "Moon J."
        initial = given[0] + "." if given else ""
        name = f"{surname} {initial}".strip()
    return {"auid": auid, "name": name, "refs": refs, "is_corresponding": is_corr}


def _roles_from_flat_text(xml: str) -> dict:
    """Fallback when XML is flattened (JSON originalText) or unparseable."""
    empty = {
        "first_auids": [],
        "first_names": [],
        "corr_auids": [],
        "corr_names": [],
    }
    if not _EQUAL_RE.search(xml) and not _CORR_RE.search(xml):
        return empty
    # "Jeongwoo Moon … a 1" / "Kwanho Jeong … e ⁎" — best-effort.
    first_names, corr_names = [], []
    # Pattern: Given Surname ... 1   (footnote marker 1 near the name)
    for m in re.finditer(
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s+[A-Z][a-z]+)\s+(?:Writing|[a-z]).{0,40}?\b1\b",
        xml,
    ):
        first_names.append(m.group(1).strip())
    for m in re.finditer(
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\s+[A-Z][a-z]+)\s+(?:Writing|[a-z]).{0,40}?⁎",
        xml,
    ):
        corr_names.append(m.group(1).strip())
    return {
        "first_auids": [],
        "first_names": first_names,
        "corr_auids": [],
        "corr_names": corr_names,
    }


def parse_outline(xml: str) -> list[str]:
    """Section titles in document order. Empty if XML has no section markup."""
    if not xml or not looks_like_fulltext(xml):
        return []
    try:
        root = _parse_xml(xml)
    except ET.ParseError:
        return []
    titles = []
    for el in root.iter():
        if _local(el.tag) == "section-title":
            t = _text_of(el)
            if t:
                titles.append(t)
    return titles


def extract_eid_from_xml(xml: str) -> str | None:
    """Scopus EID if the payload carries one (``2-s2.0-...``)."""
    m = re.search(r"2-s2\.0-\d+", xml)
    if m:
        return m.group(0)
    try:
        root = _parse_xml(xml)
    except ET.ParseError:
        return None
    for el in root.iter():
        if _local(el.tag) == "eid":
            text = _text_of(el)
            if text.startswith("2-s2.0-"):
                return text
            if text.startswith("1-s2.0-"):
                # ScienceDirect EID — keep looking for Scopus form.
                continue
    return None


def classify_http(status: int, body: str) -> str:
    if status == 200 and looks_like_fulltext(body):
        return STATUS_FETCHED
    if status in (401, 403):
        return STATUS_NOT_ENTITLED
    if status == 404:
        return STATUS_NOT_FOUND
    if status == 200:
        # META_ABS / error JSON served as 200.
        return STATUS_NOT_ENTITLED
    return STATUS_ERROR


def fetch_one(item: dict, *, force: bool = False, request=None) -> dict:
    """Fetch one paper's XML. Never raises on entitlement failure.

    ``item`` needs at least ``eid`` or ``identifier`` plus a DOI/scopus_id
    when possible. Raises ``QuotaExceeded`` on 429.
    """
    if request is None:
        request = request_elsevier
    eid = (item.get("eid") or "").strip()
    doi = normalize_doi(item.get("doi"))
    result = {
        "eid": eid,
        "doi": doi or item.get("doi") or "",
        "in_db": bool(item.get("in_db")),
        "oa_url": item.get("oa_url") or "",
        "path": str(bundle_dir(eid)) if eid else "",
        "status": STATUS_ERROR,
        "reason": "",
        "eid_discovered": False,
        "roles": {
            "first_auids": [],
            "first_names": [],
            "corr_auids": [],
            "corr_names": [],
        },
        "outline": [],
        "manifest": None,
    }

    cached = "" if force else cached_eid_for(item)
    if cached:
        xml = read_cache(cached) or ""
        try:
            manifest = ensure_bundle(cached, xml, doi=result["doi"])
        except ET.ParseError:
            # The cached XML is unusable — most likely a truncated response
            # written before it was validated. Drop it and fetch again rather
            # than raising on every future call for this paper.
            discard_cache(cached)
        else:
            result["eid"] = cached
            result["eid_discovered"] = cached != eid
            result["status"] = STATUS_CACHED
            result["path"] = str(bundle_dir(cached))
            result["roles"] = parse_roles(xml)
            result["manifest"] = manifest
            result["outline"] = [s["title"] for s in manifest.get("sections") or []]
            index_doi(result["doi"], cached)
            return result

    endpoint = article_endpoint(item)
    if not endpoint:
        result["status"] = STATUS_NO_IDENTIFIER
        result["reason"] = "no DOI or Scopus ID to retrieve against"
        return result

    resp = request(endpoint, {"view": "FULL"})
    status = resp["status"]
    body = resp["text"]
    kind = classify_http(status, body)
    result["status"] = kind
    if resp.get("remaining") is not None:
        result["remaining"] = resp["remaining"]

    if kind != STATUS_FETCHED:
        if kind == STATUS_NOT_ENTITLED:
            result["reason"] = "not entitled (closed paper, or this key cannot read full text)"
            if result["oa_url"]:
                result["reason"] += f"; open-access URL: {result['oa_url']}"
        elif kind == STATUS_NOT_FOUND:
            result["reason"] = "not an Elsevier article, or unknown identifier"
        else:
            result["reason"] = f"HTTP {status}"
        return result

    try:
        _parse_xml(body)
    except ET.ParseError as exc:
        # Never cache a payload the bundle writer cannot parse: it would poison
        # the directory and raise on every later call, --force included.
        result["status"] = STATUS_ERROR
        result["reason"] = f"malformed XML from Elsevier ({exc}); nothing cached"
        return result

    resolved_eid = eid or extract_eid_from_xml(body) or ""
    if not resolved_eid:
        # Still cache under a DOI-derived key so a later DB add can move it.
        resolved_eid = (doi or "unknown").replace("/", "_")
    path = write_cache(resolved_eid, body, doi=result["doi"])
    index_doi(result["doi"], resolved_eid)
    result["eid"] = resolved_eid
    result["eid_discovered"] = resolved_eid != eid
    result["path"] = str(path)
    result["roles"] = parse_roles(body)
    manifest = json_manifest(path)
    result["manifest"] = manifest
    result["outline"] = [s["title"] for s in (manifest or {}).get("sections") or []]
    return result


def fetch_batch(
    items: list[dict],
    *,
    force: bool = False,
    request=None,
) -> dict:
    """Fetch many papers, one HTTP call after another.

    Article Retrieval is capped at 10 req/s. Parallel/async fetches would
    only hit that ceiling sooner; the client throttle (0.11s) is the rate
    limiter. Entitlement misses continue; 429 stops the rest.
    """
    if request is None:
        request = request_elsevier
    results: list[dict] = []
    for i, item in enumerate(items):
        try:
            results.append(fetch_one(item, force=force, request=request))
        except QuotaExceeded as exc:
            row = _skip_quota(item)
            row["reason"] = str(exc)
            results.append(row)
            results.extend(_skip_quota(rest) for rest in items[i + 1 :])
            break
        except Exception as exc:  # noqa: BLE001 — one bad paper must not end the run
            results.append(_error_row(item, f"{type(exc).__name__}: {exc}"))

    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"items": results, "counts": counts, "total": len(results)}


def _miss_row(item: dict, status: str, reason: str) -> dict:
    """A per-item outcome with no XML behind it. Same shape as ``fetch_one``."""
    eid = (item.get("eid") or "").strip()
    return {
        "eid": eid,
        "doi": item.get("doi") or "",
        "in_db": bool(item.get("in_db")),
        "oa_url": item.get("oa_url") or "",
        "path": str(bundle_dir(eid)) if eid else "",
        "status": status,
        "reason": reason,
        "eid_discovered": False,
        "roles": {
            "first_auids": [],
            "first_names": [],
            "corr_auids": [],
            "corr_names": [],
        },
        "outline": [],
        "manifest": None,
    }


def _skip_quota(item: dict) -> dict:
    return _miss_row(
        item,
        STATUS_SKIPPED_QUOTA,
        "weekly Article Retrieval quota exhausted; remaining items skipped",
    )


def _error_row(item: dict, reason: str) -> dict:
    return _miss_row(item, STATUS_ERROR, reason)


def item_from_article(article: dict) -> dict:
    """Shape a DB article row into a fetch item."""
    return {
        "eid": article.get("eid") or "",
        "doi": article.get("doi") or "",
        "scopus_id": article.get("scopus_id") or "",
        "oa_url": article.get("oa_url") or "",
        "in_db": True,
        "identifier": article.get("eid") or "",
    }


def item_from_identifier(identifier: str, article: dict | None = None) -> dict:
    ident = identifier.strip()
    if article:
        item = item_from_article(article)
        item["identifier"] = ident
        return item
    doi = normalize_doi(ident) if "/" in ident else None
    eid = ident if ident.startswith("2-s2.0-") else ""
    scopus_id = "" if (eid or doi) else ident
    return {
        "eid": eid,
        "doi": doi or "",
        "scopus_id": scopus_id,
        "oa_url": "",
        "in_db": False,
        "identifier": ident,
    }
