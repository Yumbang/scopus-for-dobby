"""MathML (Elsevier ``mml:math``) → LaTeX.

Covers the subset that shows up in ScienceDirect article XML: ``mi``/``mo``/
``mn``, scripts, fractions, roots, ``mtable`` (including piecewise ``cases``).
Adjacent single-letter ``mi`` nodes are joined (``f e e d`` → ``\\mathrm{feed}``)
because Elsevier often spells identifiers one character at a time.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

_GREEK = {
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\varepsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "υ": r"\upsilon",
    "φ": r"\phi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
}

_MO = {
    "×": r"\times ",
    "−": r"-",
    "–": r"-",
    "∑": r"\sum ",
    "∏": r"\prod ",
    "∣": r"\mid ",
    "〈": r"\langle ",
    "〉": r"\rangle ",
    "≤": r"\leq ",
    "≥": r"\geq ",
    "≠": r"\neq ",
    "≈": r"\approx ",
    "→": r"\rightarrow ",
    "←": r"\leftarrow ",
    "∞": r"\infty ",
    "±": r"\pm ",
    "·": r"\cdot ",
    "…": r"\ldots ",
    "¯": r"",
    "{": r"\{",
    "}": r"\}",
    "^": r"^",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _kids(el: ET.Element) -> list[ET.Element]:
    return list(el)


def mathml_to_latex(el: ET.Element | None) -> str:
    if el is None:
        return ""
    name = _local(el.tag)
    if name == "math":
        inner = _join_row(_kids(el))
        return _strip(inner)
    if name == "mrow":
        return _mrow(el)
    if name == "mi":
        return _mi(el)
    if name == "mn":
        return (el.text or "").strip()
    if name == "mo":
        return _mo(el)
    if name == "mtext":
        t = "".join(el.itertext()).strip()
        return rf"\text{{{t}}}" if t else ""
    if name == "mspace":
        return r"\,"
    if name == "msub":
        return _script(el, sub=True, sup=False)
    if name == "msup":
        return _script(el, sub=False, sup=True)
    if name == "msubsup":
        return _script(el, sub=True, sup=True)
    if name == "mfrac":
        k = _kids(el)
        num = mathml_to_latex(k[0]) if k else ""
        den = mathml_to_latex(k[1]) if len(k) > 1 else ""
        return rf"\frac{{{num}}}{{{den}}}"
    if name == "msqrt":
        return rf"\sqrt{{{_join_row(_kids(el))}}}"
    if name == "mroot":
        k = _kids(el)
        base = mathml_to_latex(k[0]) if k else ""
        idx = mathml_to_latex(k[1]) if len(k) > 1 else ""
        return rf"\sqrt[{idx}]{{{base}}}"
    if name == "mover":
        return _over_under(el, over=True)
    if name == "munder":
        return _over_under(el, over=False)
    if name == "munderover":
        k = _kids(el)
        base = mathml_to_latex(k[0]) if k else ""
        und = mathml_to_latex(k[1]) if len(k) > 1 else ""
        ov = mathml_to_latex(k[2]) if len(k) > 2 else ""
        return rf"{base}_{{{und}}}^{{{ov}}}"
    if name == "mtable":
        return _matrix(el)
    if name in {"mtr", "mtd"}:
        return _join_row(_kids(el))
    return _join_row(_kids(el)) or (el.text or "").strip()


def _strip(s: str) -> str:
    return " ".join(s.split())


def _brace(s: str) -> str:
    s = s.strip()
    if not s:
        return "{}"
    if len(s) == 1:
        return s
    return "{" + s + "}"


def _mi(el: ET.Element) -> str:
    t = (el.text or "").strip()
    if t in _GREEK:
        return _GREEK[t] + " "
    if len(t) > 1 and t.isalpha():
        return rf"\mathrm{{{t}}}"
    return t


def _mo(el: ET.Element) -> str:
    t = (el.text or "").strip()
    if t in _MO:
        return _MO[t]
    if t in "()[]|,=+/":
        return t
    return t


def _join_row(kids: list[ET.Element]) -> str:
    """Concatenate children, merging runs of single-letter ``mi``."""
    parts: list[str] = []
    letters: list[str] = []

    def flush() -> None:
        if not letters:
            return
        s = "".join(letters)
        letters.clear()
        if len(s) == 1:
            parts.append(_GREEK.get(s, s))
            if s in _GREEK:
                parts.append(" ")
        else:
            parts.append(rf"\mathrm{{{s}}}")

    for c in kids:
        name = _local(c.tag)
        raw = (c.text or "").strip()
        if name == "mi" and len(raw) == 1 and raw.isalpha() and not list(c):
            letters.append(raw)
            continue
        flush()
        parts.append(mathml_to_latex(c))
    flush()
    return "".join(parts)


def _collect_tables(el: ET.Element) -> list[ET.Element]:
    found = []
    if _local(el.tag) == "mtable":
        return [el]
    for c in el:
        name = _local(c.tag)
        if name == "mtable":
            found.append(c)
        elif name in {"mrow", "mspace"}:
            found.extend(_collect_tables(c) if name == "mrow" else [])
    return found


def _starts_with_brace(el: ET.Element) -> bool:
    kids = _kids(el)
    return bool(
        kids and _local(kids[0].tag) == "mo" and (kids[0].text or "").strip() == "{"
    )


def _mrow(el: ET.Element) -> str:
    kids = _kids(el)
    # Elsevier often puts the condition table as a *sibling* of the `{ … }`
    # mrow (values inside, conditions after). Pull both into cases.
    for i, c in enumerate(kids):
        if _local(c.tag) == "mrow" and _starts_with_brace(c):
            tables = _collect_tables(c)
            for sib in kids[i + 1 :]:
                tables.extend(_collect_tables(sib))
            if tables:
                left = _join_row(kids[:i])
                return f"{left}\\begin{{cases}}{_cases(tables)}\\end{{cases}}"
    brace_i = next(
        (i for i, k in enumerate(kids) if _local(k.tag) == "mo" and (k.text or "").strip() == "{"),
        None,
    )
    tables = []
    if brace_i is not None:
        for k in kids[brace_i + 1 :]:
            tables.extend(_collect_tables(k))
    if brace_i is not None and tables:
        left = _join_row(kids[:brace_i])
        return f"{left}\\begin{{cases}}{_cases(tables)}\\end{{cases}}"
    return _join_row(kids)


def _table_rows(table: ET.Element) -> list[list[str]]:
    rows = []
    for tr in table:
        if _local(tr.tag) != "mtr":
            continue
        rows.append([mathml_to_latex(td) for td in tr if _local(td.tag) == "mtd"])
    return rows


def _cases(tables: list[ET.Element]) -> str:
    if len(tables) >= 2:
        left = _table_rows(tables[0])
        right = _table_rows(tables[1])
        n = max(len(left), len(right))
        lines = []
        for i in range(n):
            a = " ".join(left[i]) if i < len(left) else ""
            b = " ".join(right[i]) if i < len(right) else ""
            lines.append(f"{a} & {b}")
        return r" \\ ".join(lines)
    rows = _table_rows(tables[0])
    lines = []
    for row in rows:
        if len(row) >= 2:
            lines.append(f"{row[0]} & {row[1]}")
        elif row:
            lines.append(row[0])
    return r" \\ ".join(lines)


def _matrix(el: ET.Element) -> str:
    rows = _table_rows(el)
    body = r" \\ ".join(" & ".join(r) for r in rows)
    return r"\begin{matrix}" + body + r"\end{matrix}"


def _script(el: ET.Element, *, sub: bool, sup: bool) -> str:
    k = _kids(el)
    base = mathml_to_latex(k[0]) if k else ""
    i = 1
    out = _brace(base) if (sub or sup) and len(base) != 1 else base
    if sub and i < len(k):
        out += "_" + _brace(mathml_to_latex(k[i]))
        i += 1
    if sup and i < len(k):
        out += "^" + _brace(mathml_to_latex(k[i]))
    return out


def _over_under(el: ET.Element, *, over: bool) -> str:
    k = _kids(el)
    base = mathml_to_latex(k[0]) if k else ""
    acc = mathml_to_latex(k[1]) if len(k) > 1 else ""
    acc_text = "".join(k[1].itertext()).strip() if len(k) > 1 else ""
    if over and acc_text in {"¯", "¨", "^", "~", "ˆ"}:
        cmd = {"¯": r"\overline", "¨": r"\ddot", "^": r"\hat", "ˆ": r"\hat", "~": r"\tilde"}[acc_text]
        return rf"{cmd}{{{base}}}"
    if over:
        return rf"{{{base}}}^{{{acc}}}"
    return rf"{{{base}}}_{{{acc}}}"
