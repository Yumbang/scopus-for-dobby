"""Corpus profiling — "what are these N papers about?" without reading N abstracts.

Pure functions over lists of article dicts as returned by
``article_db.list_articles(...)["articles"]``. No I/O, no DB access, stdlib only.

The primary signal is *not* NLP. Scopus and OpenAlex both hand us curated
vocabularies (``index_keywords``, ``subject_areas``, ``openalex_topics``), and a
frequency count over a controlled vocabulary beats stemmed title terms at a
fraction of the complexity. Free-text term counting exists here only as the
fallback for corpora that carry no vocabulary at all.

The catch is that those fields are sparse: ``openalex_topics`` is empty until
``openalex enrich`` runs, and ``index_keywords``/``subject_areas`` only arrive
with a full abstract retrieval. A profile computed over the 12% of articles that
happen to carry a field will look authoritative and be wrong, so :func:`coverage`
is a first-class result that callers are expected to display, not an afterthought.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations

# Controlled vocabularies, in the order ``auto`` prefers them when coverage ties.
# OpenAlex topics are the most human-legible; subject areas are the coarsest.
# Author keywords come last: they are free text rather than a controlled
# vocabulary, so they are noisier — but they are frequently the *only* field
# populated, and excluding them once left an 84%-covered field unreachable
# while `auto` reported that it had found nothing.
VOCAB_FIELDS = ("openalex_topics", "index_keywords", "subject_areas", "keywords")

# Everything worth reporting a denominator for, vocabulary or not.
COVERAGE_FIELDS = VOCAB_FIELDS + ("abstract", "title")

# Keys a vocabulary entry may hide its label under. ``subject_areas`` arrives as
# ``{"name", "code", "abbrev"}`` dicts while the other two are plain strings;
# ``$`` is the raw Scopus JSON convention, in case unnormalized data leaks in.
_LABEL_KEYS = ("name", "label", "display_name", "term", "$")

# Author keywords (``keywords``) are one VARCHAR, pipe-separated by Scopus.
_FREETEXT_SPLIT = re.compile(r"\s*[|;]\s*")

_TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")

# Bounded on both sides so "20199" is treated as junk rather than silently
# yielding 2019 — a wrong year is worse than a missing one.
_YEAR = re.compile(r"\b(\d{4})\b")

# Small, deliberately generic English list — plus the terms that dominate any
# academic title set without saying anything about the subject.
STOPWORDS = frozenset({
    # Function words.
    "a", "an", "the", "and", "or", "but", "nor", "for", "so", "yet", "of", "in",
    "on", "at", "to", "from", "by", "with", "without", "within", "into", "onto",
    "over", "under", "between", "among", "during", "after", "before", "above",
    "below", "across", "through", "as", "if", "then", "else", "via", "per",
    "vs", "versus", "etc", "de", "la", "el",
    # Auxiliaries.
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does",
    "did", "doing", "have", "has", "had", "having", "can", "will", "should",
    # Determiners and pronouns.
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "there", "here", "which", "who", "whom", "whose", "what", "when", "where",
    "why", "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "no", "not", "only", "own", "same", "than", "too", "very",
    "just", "now", "we", "our", "us", "you", "your", "he", "she", "his", "her",
    # Academic boilerplate — frequent in every corpus, informative in none.
    "study", "studies", "results", "result", "using", "use", "used", "based",
    "novel", "approach", "approaches", "analysis", "analyses", "paper",
    "papers", "research", "investigation", "investigations", "method",
    "methods", "new", "towards", "toward", "review", "overview", "effect",
    "effects", "case", "cases", "data", "evaluation", "application",
    "applications", "development", "system", "systems", "model", "models",
})


# ── Label extraction ─────────────────────────────────────────────────────────

def _as_label(value) -> str:
    """Coerce one vocabulary entry to a display string, or '' if it has none."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        for key in _LABEL_KEYS:
            label = value.get(key)
            if isinstance(label, str) and label.strip():
                return label.strip()
    return ""


def _raw_field(article: Mapping, field: str):
    """Read a field, parsing the JSON-string form the DB sometimes hands back.

    ``_row_to_dict`` normally decodes JSON columns, but articles also arrive
    straight from the HTTP daemon, from fixtures, and from callers who built
    them by hand — so both the decoded list and the raw string must work.
    """
    value = article.get(field)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text[0] in "[{":
            try:
                return json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return text
        return text
    return value


def labels(article: Mapping, field: str) -> list[str]:
    """Labels an article carries for ``field``, de-duplicated case-insensitively.

    Duplicates within a single article are dropped so that "share of articles"
    stays a share of articles rather than of mentions.
    """
    raw = _raw_field(article, field)
    if raw is None:
        return []

    if isinstance(raw, str):
        candidates: Iterable = _FREETEXT_SPLIT.split(raw)
    elif isinstance(raw, Mapping):
        candidates = [raw]
    elif isinstance(raw, Sequence):
        candidates = raw
    else:
        return []

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        label = _as_label(candidate)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            out.append(label)
    return out


def _count_labels(articles: Sequence[Mapping], field: str) -> tuple[Counter, dict[str, str], int]:
    """Document frequency per label, its display form, and articles carrying the field.

    Counting is case-insensitive (Scopus is inconsistent about capitalization);
    the first spelling encountered wins as the display form.
    """
    counts: Counter = Counter()
    display: dict[str, str] = {}
    with_field = 0
    for article in articles:
        found = labels(article, field)
        if not found:
            continue
        with_field += 1
        for label in found:
            key = label.casefold()
            display.setdefault(key, label)
            counts[key] += 1
    return counts, display, with_field


def _ranked(counts: Counter, display: Mapping[str, str], denom: int, top: int) -> list[dict]:
    # Ties break alphabetically so output is stable across runs and dict orders.
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], display[kv[0]].casefold()))
    if top and top > 0:
        ordered = ordered[:top]
    return [
        {
            "label": display[key],
            "count": count,
            "share": round(count / denom, 4) if denom else 0.0,
        }
        for key, count in ordered
    ]


# ── Public API ───────────────────────────────────────────────────────────────

def vocabulary_profile(
    articles: Sequence[Mapping],
    *,
    field: str = "openalex_topics",
    top: int = 20,
) -> dict:
    """Frequency profile over one controlled-vocabulary field.

    ``share`` is relative to the articles that actually *carry* the field, not
    to the whole corpus — pair it with ``coverage`` (also returned) before
    reading anything into it.
    """
    articles = list(articles or [])
    counts, display, with_field = _count_labels(articles, field)
    total = len(articles)
    return {
        "field": field,
        "total": total,
        "with_field": with_field,
        "coverage": round(with_field / total, 4) if total else 0.0,
        "distinct": len(counts),
        "labels": _ranked(counts, display, with_field, top),
    }


def coverage(articles: Sequence[Mapping], fields: Sequence[str] = COVERAGE_FIELDS) -> dict:
    """How many articles carry each field — the denominator for everything else.

    A field counts as present when it yields at least one label (vocabularies)
    or any non-blank text (``title``, ``abstract``, ``keywords``).
    """
    articles = list(articles or [])
    total = len(articles)
    result = {}
    for field in fields:
        present = sum(1 for a in articles if labels(a, field))
        result[field] = {
            "count": present,
            "share": round(present / total, 4) if total else 0.0,
        }
    return {"total": total, "fields": result}


def best_field(articles: Sequence[Mapping], fields: Sequence[str] = VOCAB_FIELDS) -> dict:
    """Pick the richest vocabulary available, reporting how thin the winner is.

    Returns ``{"field": name|None, "coverage": float, "candidates": {...}}``.
    ``field`` is ``None`` when no vocabulary is present at all, which is the
    caller's cue to fall back to :func:`term_frequency`.
    """
    cov = coverage(articles, fields)["fields"]
    # ``fields`` order is the tie-break: index() keeps the preferred one first.
    ranked = sorted(cov.items(), key=lambda kv: (-kv[1]["count"], list(fields).index(kv[0])))
    winner, stats_ = ranked[0] if ranked else (None, {"count": 0, "share": 0.0})
    if not stats_["count"]:
        return {"field": None, "coverage": 0.0, "candidates": cov}
    return {"field": winner, "coverage": stats_["share"], "candidates": cov}


def distinctive_terms(
    groups: Mapping[str, Sequence[Mapping]] | Sequence[tuple[str, Sequence[Mapping]]],
    *,
    field: str | None = "openalex_topics",
    top: int = 10,
    min_count: int = 1,
    text_fields: Sequence[str] = ("title",),
    min_length: int = 3,
    stopwords: Iterable[str] | None = None,
    ngram: int = 1,
) -> dict:
    """What makes each group *different*, not merely what is frequent in it.

    Scores each term by in-group prevalence times the log ratio of in-group to
    out-of-group prevalence (add-half smoothing, so a term absent outside the
    group does not divide by zero). A term carried by every article everywhere
    scores ~0 no matter how common; a term concentrated in one group ranks high
    even at modest counts. Weighting by prevalence keeps one-off terms — which
    have the most extreme ratios — from taking over the list.

    Set ``field=None`` to score free-text terms from ``text_fields`` instead of
    a controlled vocabulary.
    """
    items = list(groups.items()) if isinstance(groups, Mapping) else list(groups or [])
    items = [(name, list(members or [])) for name, members in items]
    total = sum(len(members) for _, members in items)

    stops = _resolve_stopwords(stopwords)

    def _terms(article: Mapping) -> list[str]:
        if field is None:
            return _article_terms(article, text_fields, min_length, stops, ngram)
        return labels(article, field)

    per_group: list[tuple[str, list[Mapping], Counter]] = []
    display: dict[str, str] = {}
    overall: Counter = Counter()
    for name, members in items:
        counts: Counter = Counter()
        for article in members:
            for label in _terms(article):
                term = label.casefold()
                display.setdefault(term, label)
                counts[term] += 1
        per_group.append((name, members, counts))
        overall.update(counts)

    out = []
    for name, members, counts in per_group:
        size = len(members)
        rest = total - size
        scored = []
        for term, count in counts.items():
            if count < min_count:
                continue
            p_in = (count + 0.5) / (size + 1)
            p_out = (overall[term] - count + 0.5) / (rest + 1)
            scored.append({
                "term": display.get(term, term),
                "count": count,
                "share": round(count / size, 4) if size else 0.0,
                "outside_share": round((overall[term] - count) / rest, 4) if rest else 0.0,
                "score": round(p_in * math.log(p_in / p_out), 4),
            })
        scored.sort(key=lambda d: (-d["score"], -d["count"], d["term"].casefold()))
        out.append({
            "group": name,
            "articles": size,
            "terms": scored[:top] if top and top > 0 else scored,
        })
    return {"field": field, "total": total, "groups": out}


def _resolve_stopwords(stopwords: Iterable[str] | None) -> frozenset[str]:
    if stopwords is None:
        return STOPWORDS
    return frozenset(w.casefold() for w in stopwords)


def _article_terms(
    article: Mapping,
    fields: Sequence[str],
    min_length: int,
    stops: frozenset[str],
    ngram: int,
) -> list[str]:
    """Tokens (or bigrams) from an article's free text, filtered and de-duplicated."""
    out: list[str] = []
    seen: set[str] = set()
    for field in fields:
        raw = _raw_field(article, field)
        if raw is None:
            continue
        if isinstance(raw, str):
            text = raw
        elif isinstance(raw, Sequence):
            text = " ".join(_as_label(v) for v in raw)
        else:
            continue
        tokens = _TOKEN.findall(text.lower())

        def _ok(token: str) -> bool:
            return len(token) >= min_length and token not in stops and not token.isdigit()

        if ngram <= 1:
            grams = (t for t in tokens if _ok(t))
        else:
            # Bigrams come from the *raw* token stream, then reject any pair
            # containing a stopword — otherwise "effects of climate" collapses
            # into the phantom bigram "effects climate".
            grams = (
                " ".join(tokens[i:i + ngram])
                for i in range(len(tokens) - ngram + 1)
                if all(_ok(t) for t in tokens[i:i + ngram])
            )
        for gram in grams:
            if gram not in seen:
                seen.add(gram)
                out.append(gram)
    return out


def term_frequency(
    articles: Sequence[Mapping],
    *,
    fields: Sequence[str] = ("title",),
    top: int = 20,
    min_length: int = 3,
    stopwords: Iterable[str] | None = None,
    ngram: int = 1,
) -> dict:
    """Free-text term counts — the fallback when no controlled vocabulary exists.

    Counts are *document* frequencies: an article that repeats a word in title
    and abstract still counts once, so ``share`` means the same thing here as in
    :func:`vocabulary_profile`.
    """
    articles = list(articles or [])
    stops = _resolve_stopwords(stopwords)
    counts: Counter = Counter()
    with_text = 0
    for article in articles:
        terms = _article_terms(article, fields, min_length, stops, ngram)
        if terms:
            with_text += 1
        counts.update(terms)
    total = len(articles)
    display = {term: term for term in counts}
    return {
        "fields": list(fields),
        "ngram": ngram,
        "total": total,
        "with_text": with_text,
        "distinct": len(counts),
        "terms": [
            {"term": row["label"], "count": row["count"], "share": row["share"]}
            for row in _ranked(counts, display, with_text, top)
        ],
    }


def co_occurrence(
    articles: Sequence[Mapping],
    *,
    field: str = "openalex_topics",
    min_count: int = 2,
    top: int = 20,
) -> dict:
    """Label pairs sharing an article — the standard bibliometric keyword map.

    Pairs are unordered; ``a``/``b`` are ordered case-insensitively so a pair is
    counted once regardless of the order the labels appear on the article.
    """
    articles = list(articles or [])
    pairs: Counter = Counter()
    singles: Counter = Counter()
    display: dict[str, str] = {}
    for article in articles:
        found = labels(article, field)
        keys = []
        for label in found:
            key = label.casefold()
            display.setdefault(key, label)
            singles[key] += 1
            keys.append(key)
        for a, b in combinations(sorted(set(keys)), 2):
            pairs[(a, b)] += 1

    rows = [
        {
            "a": display[a],
            "b": display[b],
            "count": count,
            # Jaccard separates "co-occurs because both are everywhere" from a
            # genuinely tight pairing.
            "jaccard": round(count / (singles[a] + singles[b] - count), 4),
        }
        for (a, b), count in pairs.items()
        if count >= min_count
    ]
    rows.sort(key=lambda r: (-r["count"], -r["jaccard"], r["a"].casefold(), r["b"].casefold()))
    return {
        "field": field,
        "total": len(articles),
        "distinct_pairs": len(pairs),
        "pairs": rows[:top] if top and top > 0 else rows,
    }


def year_distribution(articles: Sequence[Mapping]) -> dict:
    """Publication years parsed defensively out of ``cover_date``.

    ``cover_date`` is a VARCHAR that may be empty, a bare year, ``2019-03`` or
    outright junk, so anything that does not contain a plausible 4-digit year is
    counted as missing rather than guessed at. The median is a *low* median so
    the answer is always a real year, never 2019.5.
    """
    articles = list(articles or [])
    years: list[int] = []
    missing = 0
    for article in articles:
        value = article.get("cover_date")
        year = None
        if value is not None:
            match = _YEAR.search(str(value))
            if match:
                candidate = int(match.group(1))
                if 1500 <= candidate <= 2200:
                    year = candidate
        if year is None:
            missing += 1
        else:
            years.append(year)

    counts = Counter(years)
    return {
        "total": len(articles),
        "with_year": len(years),
        "missing": missing,
        "years": {year: counts[year] for year in sorted(counts)},
        "median": statistics.median_low(years) if years else None,
        "earliest": min(years) if years else None,
        "latest": max(years) if years else None,
    }
