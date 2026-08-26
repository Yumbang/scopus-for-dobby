"""Turn Elsevier Article Retrieval XML into a readable on-disk bundle.

Agents should open ``manifest.json`` and then ``head.md`` / ``sections/*.md``.
``xml/article.xml`` is the regenerate-from original; do not parse it in a skill.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

from scopus_for_dobby.core.mathml_latex import mathml_to_latex
from scopus_for_dobby.utils.api_client import QuotaExceeded, api_get_raw

# Bump when the markdown renderer changes so cached bundles regenerate.
BUNDLE_VERSION = 3

_SAFE_SLUG = re.compile(r"[^a-z0-9]+")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_xml(xml: str) -> ET.Element:
    return ET.fromstring(xml)  # noqa: S314 — Elsevier API / our cache


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def _child(el: ET.Element, name: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def _find(el: ET.Element, name: str) -> ET.Element | None:
    for c in el.iter():
        if _local(c.tag) == name:
            return c
    return None


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def _slug(title: str, fallback: str = "section") -> str:
    raw = unicodedata.normalize("NFKD", title or "")
    ascii_ = raw.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SAFE_SLUG.sub("-", ascii_).strip("-")
    return (slug[:60] or fallback).rstrip("-")


def inline(el: ET.Element) -> str:
    """Flatten a paragraph-like node to markdown-ish text."""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for c in el:
        name = _local(c.tag)
        if name in {"cross-ref", "cross-out"}:
            label = "".join(c.itertext()).strip() or c.get("refid") or ""
            parts.append(label)
        elif name == "math":
            parts.append(f"${mathml_to_latex(c)}$")
        elif name in {"display", "formula", "display-formula"}:
            parts.append(_display_math(c))
        elif name == "italic":
            parts.append(f"*{inline(c)}*")
        elif name == "bold":
            parts.append(f"**{inline(c)}**")
        elif name == "sup":
            parts.append(f"^{inline(c)}")
        elif name in {"inf", "sub"}:
            parts.append(f"_{inline(c)}")
        elif name in {"list"}:
            parts.append("\n" + _list_md(c) + "\n")
        else:
            parts.append(inline(c))
        if c.tail:
            parts.append(c.tail)
    return "".join(parts)


def _display_math(el: ET.Element) -> str:
    """Render ``ce:display`` / ``ce:formula`` as a tagged display equation."""
    formula = el if _local(el.tag) == "formula" else _child(el, "formula") or el
    label = _text(_child(formula, "label"))
    math = None
    for c in formula.iter():
        if _local(c.tag) == "math":
            math = c
            break
    latex = mathml_to_latex(math)
    tag = ""
    if label:
        num = label.strip()
        if num.startswith("(") and num.endswith(")"):
            num = num[1:-1]
        tag = f"\\tag{{{num}}}"
    body = latex if not tag else f"{latex}\n{tag}"
    return f"\n\n$$\n{body}\n$$\n\n"


def _list_md(el: ET.Element) -> str:
    lines = []
    for item in el.iter():
        if _local(item.tag) == "list-item":
            lines.append(f"- {_text(item)}")
    return "\n".join(lines)


def _para_blocks(parent: ET.Element) -> list[str]:
    """Direct paragraph-like children, not nested sections."""
    blocks = []
    for c in parent:
        name = _local(c.tag)
        if name == "section":
            continue
        if name in {"para", "simple-para", "nomenclature-para", "display", "formula"}:
            t = inline(c).strip()
            if t:
                blocks.append(t)
        elif name in {"section-title", "label"}:
            continue
    return blocks


def _find_article(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if _local(el.tag) == "article":
            return el
    return root


def _find_head(article: ET.Element) -> ET.Element | None:
    for c in article:
        if _local(c.tag) == "head":
            return c
    return _find(article, "head")


def _find_sections(article: ET.Element) -> ET.Element | None:
    for c in article:
        if _local(c.tag) == "sections":
            return c
        if _local(c.tag) == "body":
            found = _child(c, "sections")
            if found is not None:
                return found
    return _find(article, "sections")


def _coredata_title(root: ET.Element) -> str:
    for el in root:
        if _local(el.tag) == "coredata":
            t = _child(el, "title")
            if t is not None:
                return _text(t)
    return ""


def _render_head_md(root: ET.Element, article: ET.Element) -> str:
    head = _find_head(article)
    title = ""
    if head is not None:
        title = _text(_child(head, "title"))
    title = title or _coredata_title(root) or "Untitled"

    lines = [f"# {title}", ""]
    if head is None:
        return "\n".join(lines).rstrip() + "\n"

    group = _child(head, "author-group")
    if group is not None:
        authors = []
        for au in _children(group, "author"):
            given = _text(_child(au, "given-name"))
            surname = _text(_child(au, "surname"))
            name = " ".join(p for p in (given, surname) if p)
            refs = [cr.get("refid") for cr in au.iter() if _local(cr.tag) == "cross-ref"]
            refs = [r for r in refs if r]
            mark = f" ({', '.join(refs)})" if refs else ""
            if name:
                authors.append(f"- {name}{mark}")
        if authors:
            lines += ["## Authors", *authors, ""]

        affs = []
        for aff in _children(group, "affiliation"):
            aid = aff.get("id") or ""
            affs.append(f"- `{aid}`: {_text(aff)}")
        if affs:
            lines += ["## Affiliations", *affs, ""]

        notes = []
        for tag in ("footnote", "correspondence"):
            for el in _children(group, tag):
                nid = el.get("id") or tag
                notes.append(f"- `{nid}`: {_text(el)}")
        if notes:
            lines += ["## Notes", *notes, ""]

    for dates_name in ("date-received", "date-revised", "date-accepted"):
        el = _child(head, dates_name) if head is not None else None
        if el is not None:
            d = "-".join(el.get(k, "") for k in ("year", "month", "day") if el.get(k))
            if d:
                lines.append(f"- {dates_name.replace('date-', '')}: {d}")
    if any(x.startswith("- ") for x in lines[-3:]):
        lines.append("")

    for abs_el in _children(head, "abstract") if head is not None else []:
        klass = abs_el.get("class") or "abstract"
        body = "\n\n".join(_para_blocks(abs_el) or [_text(abs_el)])
        if not body:
            continue
        heading = "Abstract" if klass == "author" else f"Abstract ({klass})"
        lines += [f"## {heading}", "", body, ""]

    for keys in _children(head, "keywords") if head is not None else []:
        kws = [_text(k) for k in keys.iter() if _local(k.tag) == "keyword" and _text(k)]
        if kws:
            klass = keys.get("class") or "keyword"
            heading = "Keywords" if klass == "keyword" else f"Keywords ({klass})"
            lines += [f"## {heading}", "", ", ".join(kws), ""]

    return "\n".join(lines).rstrip() + "\n"


def _walk_sections(sections: ET.Element, prefix: tuple[int, ...] = ()) -> list[dict]:
    out: list[dict] = []
    n = 0
    for child in sections:
        if _local(child.tag) != "section":
            continue
        n += 1
        nums = prefix + (n,)
        label = ".".join(f"{i:02d}" for i in nums)
        title = _text(_child(child, "section-title")) or f"Section {label}"
        filename = f"{label}-{_slug(title)}.md"
        nested = _walk_sections(child, nums)
        out.append(
            {
                "id": child.get("id") or "",
                "title": title,
                "file": f"sections/{filename}",
                "label": label,
                "blocks": _para_blocks(child),
                "children": nested,
            }
        )
    return out


def _write_sections(dest: Path, nodes: list[dict]) -> None:
    for node in nodes:
        lines = [f"# {node['title']}", ""]
        lines.extend(b + "\n" for b in node["blocks"])
        _write(dest / node["file"], "\n".join(lines).rstrip() + "\n")
        _write_sections(dest, node["children"])


def _outline(nodes: list[dict]) -> list[dict]:
    return [
        {
            "id": n["id"],
            "title": n["title"],
            "file": n["file"],
            "children": _outline(n["children"]),
        }
        for n in nodes
    ]


def _table_md(table: ET.Element) -> str:
    label = _text(_child(table, "label"))
    caption = _text(_child(table, "caption"))
    lines = []
    if label:
        lines.append(f"# {label}")
        lines.append("")
    if caption:
        lines.append(caption)
        lines.append("")
    tgroup = _find(table, "tgroup")
    if tgroup is None:
        return "\n".join(lines).rstrip() + "\n"
    rows: list[list[str]] = []
    for row in tgroup.iter():
        if _local(row.tag) != "row":
            continue
        cells = [_text(e) for e in row if _local(e.tag) == "entry"]
        if cells:
            rows.append(cells)
    if not rows:
        return "\n".join(lines).rstrip() + "\n"
    width = max(len(r) for r in rows)
    norm = [r + [""] * (width - len(r)) for r in rows]
    header, body = norm[0], norm[1:]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    lines.append("")
    return "\n".join(lines)


def _collect_objects(root: ET.Element) -> dict[str, dict[str, str]]:
    """locator -> {IMAGE-DOWNSAMPLED: url, IMAGE-HIGH-RES: url, ...}."""
    by_ref: dict[str, dict[str, str]] = {}
    for el in root.iter():
        if _local(el.tag) != "object":
            continue
        ref = el.get("ref") or ""
        typ = el.get("type") or ""
        url = (el.text or "").strip()
        if ref and url:
            by_ref.setdefault(ref, {})[typ] = url
    return by_ref


def download_object(url: str) -> bytes | None:
    parsed = urlparse(url)
    if "elsevier.com" not in (parsed.netloc or ""):
        return None
    endpoint = parsed.path
    if "/content/object" not in endpoint:
        return None
    params = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
    resp = api_get_raw(endpoint, params=params or None, accept="*/*", timeout=60)
    if resp.status_code == 429:
        reset = resp.headers.get("X-RateLimit-Reset")
        raise QuotaExceeded("Rate limit exceeded while fetching a figure.", reset=reset)
    if resp.status_code == 200 and resp.content:
        return resp.content
    return None


def _locator(figure: ET.Element) -> str:
    for el in figure.iter():
        if _local(el.tag) == "link":
            loc = el.get("locator")
            if loc:
                return loc
    return ""


def _render_figures(
    dest: Path,
    article: ET.Element,
    objects: dict[str, dict[str, str]],
    fetch_object,
) -> list[dict]:
    floats = _child(article, "floats")
    if floats is None:
        floats = article
    figures = [c for c in floats.iter() if _local(c.tag) == "figure" and c.get("id")]
    # Prefer floats-level figures; fall back to any unique id.
    seen: set[str] = set()
    out: list[dict] = []
    fig_dir = dest / "figures"
    downloading = fetch_object is not None
    for fig in figures:
        fid = fig.get("id") or ""
        if not fid or fid in seen:
            continue
        seen.add(fid)
        label = _text(_child(fig, "label")) or fid
        caption = _text(_child(fig, "caption"))
        loc = _locator(fig)
        urls = objects.get(loc) or {}
        url = urls.get("IMAGE-DOWNSAMPLED") or urls.get("IMAGE-HIGH-RES") or ""
        image_rel = None
        blob = None
        existing = dest / "figures" / f"{fid}.jpg"
        if existing.is_file() and existing.stat().st_size > 0:
            blob = existing.read_bytes()
        elif url and downloading:
            try:
                blob = fetch_object(url)
            except QuotaExceeded:
                downloading = False
                blob = None
        if blob:
            image_rel = f"figures/{fid}.jpg"
            path = dest / image_rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            path.chmod(0o600)
        cap_rel = f"figures/{fid}.caption.md"
        cap_lines = [f"# {label}", ""]
        if caption:
            cap_lines += [caption, ""]
        if image_rel:
            cap_lines.append(f"![{label}]({Path(image_rel).name})")
            cap_lines.append("")
        _write(dest / cap_rel, "\n".join(cap_lines))
        out.append(
            {
                "id": fid,
                "label": label,
                "locator": loc,
                "file": image_rel,
                "caption": cap_rel,
            }
        )
    if not figures:
        fig_dir.mkdir(parents=True, exist_ok=True)
    return out


def _render_tables(dest: Path, article: ET.Element) -> list[dict]:
    floats = _child(article, "floats")
    if floats is None:
        floats = article
    tables = [c for c in floats.iter() if _local(c.tag) == "table" and c.get("id")]
    seen: set[str] = set()
    out: list[dict] = []
    for tbl in tables:
        tid = tbl.get("id") or ""
        if not tid or tid in seen:
            continue
        seen.add(tid)
        label = _text(_child(tbl, "label")) or tid
        rel = f"tables/{tid}.md"
        _write(dest / rel, _table_md(tbl))
        out.append({"id": tid, "label": label, "file": rel})
    return out


def materialize(
    xml: str,
    dest: Path,
    *,
    eid: str = "",
    doi: str = "",
    fetch_object=None,
) -> dict:
    """Write ``xml/article.xml`` + markdown/assets under ``dest``. Returns manifest."""
    if fetch_object is None:
        fetch_object = download_object
    dest.mkdir(parents=True, exist_ok=True)
    dest.chmod(0o700)
    source = dest / "xml" / "article.xml"
    if not source.is_file() or source.read_text(encoding="utf-8") != xml:
        _write(source, xml)

    root = _parse_xml(xml)
    article = _find_article(root)
    head = _find_head(article)
    title = ""
    if head is not None:
        title = _text(_child(head, "title"))
    title = title or _coredata_title(root)
    _write(dest / "head.md", _render_head_md(root, article))

    sections_el = _find_sections(article)
    section_nodes = _walk_sections(sections_el) if sections_el is not None else []
    (dest / "sections").mkdir(parents=True, exist_ok=True)
    _write_sections(dest, section_nodes)

    objects = _collect_objects(root)
    figures = _render_figures(dest, article, objects, fetch_object)
    tables = _render_tables(dest, article)
    (dest / "figures").mkdir(parents=True, exist_ok=True)
    (dest / "tables").mkdir(parents=True, exist_ok=True)

    manifest = {
        "eid": eid,
        "doi": doi,
        "title": title,
        "parser": BUNDLE_VERSION,
        "head": "head.md",
        "source": "xml/article.xml",
        "sections": _outline(section_nodes),
        "figures": figures,
        "tables": tables,
    }
    _write(dest / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest
