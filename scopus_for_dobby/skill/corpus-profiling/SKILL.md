---
name: corpus-profiling
description: "Statistically characterise a LARGE set of saved papers — many dozens or more — that is too big to read, using scopus-for-dobby's `profile` command. TWO CONDITIONS MUST BOTH HOLD, CHECK THEM FIRST: (1) the set is large, roughly 30+ papers — below that use `db list` and read the titles, which is faster and better, and a frequency table over a dozen papers is meaningless; (2) the question is about the subject matter of the set AS A WHOLE, not about the individual papers. Only then does this apply: 'what are these 500 papers about', 'what themes are in this collection', 'what is this search actually covering', 'which keywords dominate', 'summarise the topics of these hundreds of papers', 'has the focus shifted over time'. Do NOT use this to list, show, count, filter, sort, tag or export papers, however phrased — that is `db list` and the scopus-for-dobby skill. Do NOT use it for citation structure, gaps, seminal works or research fronts — that is the citation-analysis skill. Do NOT use it to read any single paper's body — that is the paper-fulltext skill. When in doubt, or when the user seems to want to see the papers themselves, do not use this skill."
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
| `--field auto\|topics\|index-keywords\|author-keywords\|subjects` | Which vocabulary. `auto` picks the best-covered and says which it chose. `keywords` is accepted but ambiguous — the database has both Scopus-indexed and author-supplied keyword fields, so prefer the explicit names |
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
| `index_keywords` | Scopus curated indexing terms | `abstract --view FULL` (rarely present from search alone) |
| `subject_areas` | Scopus classification | search/abstract retrieval |
| `keywords` | Author free-text (`--field author-keywords`) | varies — often the only populated field |
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
