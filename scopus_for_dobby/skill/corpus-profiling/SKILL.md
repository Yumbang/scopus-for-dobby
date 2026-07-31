---
name: corpus-profiling
description: "Summarise what a LARGE set of saved papers is ABOUT, using scopus-for-dobby's `profile` command — controlled-vocabulary topic/keyword frequency, distinctive terms, keyword co-occurrence, and year distribution. Use ONLY when the user asks a question about the *subject matter of a set as a whole* that cannot be answered by looking at the papers: 'what are these 500 papers about', 'what themes are in this collection', 'what is this search actually covering', 'summarise the topics', 'which keywords dominate', 'has the focus shifted over time'. Do NOT use this to list, show, count, filter, sort, tag or export papers — `db list` already does that and reading its output is the correct answer for small sets. Do NOT use it for citation structure, gaps, or seminal works — that is the citation-analysis skill. If fewer than ~30 papers are involved, or the user wants to see the papers themselves rather than a characterisation of the set, do not use this skill."
---

# Corpus profiling — what is this set of papers about?

One job: characterise a set too large to read. Nothing here retrieves,
lists or manages papers.

## Do not reach for this skill by default

The failure mode this skill must avoid is firing when someone simply wants to
see their papers. Before using it, check all three:

1. **Is the question about the set, not the papers?** "What are these about" —
   yes. "Show me these" / "which ones are open access" / "how many are from
   2024" — no, that is `db list`.
2. **Is the set big enough that reading is impractical?** Under ~30 papers,
   `db list` and reading the titles is faster, more accurate, and gives the user
   something they can act on. A frequency table over 12 papers is theatre.
3. **Is it about subject matter, not citations?** Gaps, seminal works, research
   fronts and "what did my search miss" are `citation-analysis`.

If any answer is no, use the plain command and read the output.

## The command

```bash
scopus-for-dobby profile --collection review          # topic/keyword profile
scopus-for-dobby profile --tag survey --top 30
scopus-for-dobby profile -c review --terms            # title terms + bigrams
scopus-for-dobby profile -c review --co-occurrence    # which labels co-occur
scopus-for-dobby --json profile -c review             # structured (global --json)
```

| Option | Meaning |
|---|---|
| `--field topics\|keywords\|subjects\|auto` | Which vocabulary. `auto` picks the best-covered and says which it chose |
| `--top N` | Rows per table |
| `--terms` | Title-word and bigram frequency — the fallback when no vocabulary is present |
| `--co-occurrence` | Label pairs appearing on the same paper |

Seeds come from `--collection`, `--tag`, or positional EIDs, like the rest of
the CLI.

## Coverage is the whole story — read it first

The strength here is that the database already holds **controlled
vocabularies**, so no stemming, stopword tuning or topic modelling is involved:

| Field | Source | Populated by |
|---|---|---|
| `openalex_topics` | OpenAlex topic labels (≤5/paper) | `openalex enrich` |
| `index_keywords` | Scopus curated indexing terms | search/abstract retrieval |
| `subject_areas` | Scopus classification | search/abstract retrieval |
| `keywords` | Author free-text | varies |
| `title` | always present | always |

**But coverage is often low, and that changes what the numbers mean.** On a real
16,500-article library the vocabularies covered 2-4% of articles while titles
covered 100%. A topic table over 4% coverage describes 4% of the corpus, not the
corpus. `profile` prints coverage above every table and warns below 50%; quote
that warning to the user rather than presenting the profile bare.

Two ways to fix low coverage, in order:
1. `openalex enrich --collection X` — free, keyless, populates `openalex_topics`.
2. Fall back to `--terms` (titles are always there), and say that is what you did.

`share` is the share of **articles carrying that field**, not of the corpus.
Multiply by coverage for the corpus-wide figure.

## Reporting

1. **Coverage and denominator first.** "Of 500 papers, 480 carry OpenAlex
   topics" — or the warning if it is low.
2. **The profile** — dominant labels with counts and shares.
3. **What it implies.** A single label at 80% means the query was narrow; a flat
   distribution across unrelated labels means it was ambiguous and probably
   needs narrowing.
4. **Time**, if asked — the year distribution shows whether the set is current
   or historical.

Report distributions, not verdicts. "62% of these are membrane-separation
papers" is a finding; "this collection is about membranes" is an interpretation
the user is better placed to make.

For building or curating the set — searching, collections, tags, export — use
the `scopus-for-dobby` skill. For citation structure, gaps and seminal works,
use `citation-analysis`.
