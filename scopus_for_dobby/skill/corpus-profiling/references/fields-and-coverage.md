# Fields, coverage, and what the numbers actually mean

## Where each vocabulary comes from

| Field | Shape | Filled by | Typical coverage |
|---|---|---|---|
| `openalex_topics` | JSON array, ≤5 labels | `openalex enrich` (free, keyless) | 0% until enriched, then high for papers with DOIs |
| `index_keywords` | JSON array | Scopus, on `abstract --view FULL` | Low unless abstracts were fetched |
| `subject_areas` | JSON array | Scopus, journal-level classification | Moderate |
| `keywords` | free text, `;`/`\|` separated | author-supplied | Erratic |
| `title` | string | always | 100% |

`--field auto` ranks by coverage and reports its choice. If it picks
`subject_areas` over `openalex_topics`, that is usually a sign the corpus has
not been enriched — say so and offer `openalex enrich`.

## Coverage arithmetic

Two denominators exist and confusing them misleads badly:

- **coverage** = articles carrying the field ÷ all articles
- **share** = articles with a label ÷ articles *carrying the field*

So `Ecology 100%` on 6-of-300 coverage means six papers, all tagged Ecology —
2% of the corpus. Corpus-wide share is `share × coverage`. The command prints
coverage immediately above each table for exactly this reason; do not quote a
share without it.

Under 50% coverage `profile` warns. Under ~30% the profile is not worth
presenting as a characterisation at all — enrich, or switch to `--terms`.

## Term frequency, when there is no vocabulary

`--terms` counts title words and bigrams, with a stopword list covering both
ordinary English and academic filler ("study", "results", "novel", "approach").
Two deliberate behaviours:

- **Counts are document frequencies.** A word repeated in one paper counts once,
  so `share` means the same thing in every table.
- **Bigrams reject pairs containing a stopword** rather than bridging over
  removed words, so "canopy of biomass" does not become the phantom phrase
  "canopy biomass".

Title terms are noisier than curated labels and reflect phrasing rather than
subject. Prefer a vocabulary when one is available; when falling back, say that
is what you did.

## Distinctive terms vs frequent terms

`distinctive_terms` in `core/text_analysis.py` answers "what makes group A
different from group B", not "what is common in A" — a term appearing in every
paper of both groups scores near zero. Frequency alone would surface exactly the
terms that distinguish nothing.

It is not currently wired to a CLI flag; use it through `--json` output or
call it directly if comparing groups.

## Co-occurrence

`--co-occurrence` reports label pairs appearing on the same paper. This is the
standard bibliometric keyword map (what VOSviewer draws), and it answers a
different question from frequency: not "what is here" but "what goes together".
Frequent labels that never co-occur usually mean the set contains two distinct
literatures — worth reporting, and a hint the query was ambiguous.

## Year distribution

Parsed from `cover_date`, defensively — malformed dates are counted as missing
rather than silently yielding a wrong year. Useful for "is this a current
literature or a historical one", and for spotting a corpus accidentally skewed
by a date filter.
