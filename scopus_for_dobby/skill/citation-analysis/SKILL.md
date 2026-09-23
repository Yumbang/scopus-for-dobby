---
name: citation-analysis
description: "Analyze citation networks around a set of papers with scopus-for-dobby's `openalex analyze` and `openalex graph --depth`: find which highly-cited papers a search missed, split results into research themes inferred from citation links (co-citation and bibliographic-coupling clusters), identify the foundational works a corpus rests on, and spot off-topic results. Use this whenever the user asks what their search results mean or whether they are complete — 'what am I missing', 'find seminal papers', 'is my literature review complete', 'group these papers by topic', 'which papers are most important here', 'build a citation network/graph', 'co-citation', 'bibliographic coupling', 'research fronts', 'Gephi'. Also use before trusting a literature search, since citation structure reveals gaps a keyword query cannot. Not for running the searches themselves or managing the library — that is the scopus-for-dobby skill. Not for the text of any individual paper (its methods, a quote, a figure) — that is the paper-fulltext skill. Not for a frequency profile of topics or keywords over a large saved set — that is the corpus-profiling skill; use this one only when the answer comes from how the papers cite each other, not from counting labels."
---

# Citation analysis — reading a graph, not drawing one

The goal is to answer three questions about a set of papers:

1. **What did this search actually find?** — themes, coverage, off-topic hits
2. **What did it miss?** — highly-cited work the corpus cites but does not contain
3. **What should be read next?** — ranked, with reasons

A picture is optional output. Lead with findings and recommendations; export a
graph file only if the user asks for one or wants to explore in Gephi.

## Reference files

| File | Read when |
|---|---|
| `references/interpretation.md` | **Read before reporting anything.** What each output means, which metrics this graph shape supports, and the ones that produce confident nonsense |
| `references/depth-and-cost.md` | Choosing `--depth`, tuning the relevance gate, estimating API cost before a big run |
| `references/workflows.md` | End-to-end recipes: triaging a search, gap-driven expansion, theme mapping, Gephi hand-off |

## The one thing to know first

The graph is **not** a general citation network. It is grown outward from your
papers, so its shape is a product of how far you expanded:

- **Depth 1 is a star.** Edges run only seed→reference and citer→seed; there
  are none among non-seed nodes. Every path is at most 2 hops.
- Therefore `pagerank`, `betweenness`, and `closeness` on a depth-1 graph
  measure the *shape of the crawl*, not the literature. Do not report them.
  `openalex analyze` refuses them and says why.
- **Node roles matter.** `seed` (your papers) and `expanded` nodes have
  complete reference lists. `frontier` nodes were never expanded — their edges
  are truncated by where you stopped, so they must not enter structural
  measures. They are still valid for ranking by `cited_by_count`, which comes
  from OpenAlex and is complete regardless.

What *is* valid: **bibliographic coupling** (papers sharing references →
research fronts), **co-citation** (references cited together → the
intellectual base), and **gap papers** (`seed_reached_by` × `cited_by_count`).

**`reached_by` is not "how many of my papers cite this".** It counts every
expanding node pointing at a work — the signal the relevance gate needs, but at
depth ≥2 it includes expanded nodes and overstates corpus interest badly (on a
real 273-seed corpus EPR showed `reached_by` 148 against 38 actual seed
citations). Use **`seed_reached_by`**, which is what the human output prints as
"N of your papers".

## Commands

```bash
# The main one — build and interpret in a single step
scopus-for-dobby openalex analyze --collection review

# Deeper: only nodes several of your papers cite get expanded
scopus-for-dobby openalex analyze --collection review --depth 2 --communities

# What would depth 3 cost? Builds depth 1, then projects
scopus-for-dobby openalex analyze --collection review --depth 3 --dry-run

# Re-analyze an existing export without spending API calls
scopus-for-dobby --json openalex analyze --from-file map.json

# Export for Gephi/networkx (analysis is a separate step)
scopus-for-dobby openalex graph --collection review --depth 2 -o map.graphml
```

Seeds come from `--collection`, `--tag`, or positional EIDs — any batch of
saved papers — or from a whole project's collections at once with `-p/--project`
(deduplicated; excludes `--collection`). Projects are managed with `project ...`
(scopus-for-dobby skill). Seeds need DOIs; those without one are reported, not fatal.

`openalex enrich` is **not** a prerequisite. `analyze` matches seeds to OpenAlex
by DOI itself. Enriching first is still worth it for open-access links and topic
labels, but do not treat it as a required step in this workflow.

| Option | Meaning |
|---|---|
| `--depth 1..3` | Expansion levels. Default 1 — deeper costs real budget, see `depth-and-cost.md` |
| `--direction` | `references` (default, batched — cheap) / `cited-by` (**one request per seed**) / `both`. The dominant cost lever |
| `--min-reached N` | Expand a node only if N papers you hold point at it (default 2) |
| `--max-nodes N` | Expansion budget beyond your seeds. Defaults to `max(5000, 25 x seeds)`, so it scales with the corpus. Checked *between* levels — a level never half-runs — and truncation reports which level it stopped before |
| `--node-fields authorships` | Put author names on nodes. Opt-in; needed for any person-level question ("does this corpus still cite Bohr"), which the graph otherwise cannot answer |
| `--deep-direction` | Direction past level 1 — `references` by default, because citers cost one request *per node* |
| `--per-seed-limit N` | Cap references/citers taken per node (default 200). A budget lever on large corpora |
| `--from-file PATH` | Analyse an earlier export — **no API calls**. Cannot report seed-match or DOI coverage, which the export does not carry |
| `--dry-run` | Build depth 1, then project what going deeper costs. Not free: depth 1 is the expensive level |
| `--top N` | Rows per section |
| `--communities` | Cluster into themes; needs the optional `[analysis]` extra |
| `--json` | Full structured report. **Global flag — it goes before the subcommand**: `scopus-for-dobby --json openalex analyze …` |

`analyze` and `graph` share defaults, so the same flags produce the same graph.

## Reporting to the user

Lead with what is actionable:

1. **Coverage first** — how many seeds matched OpenAlex, how many lacked DOIs,
   whether the graph was truncated. If coverage is poor, say so *before* the
   findings; everything downstream inherits it.
2. **Gap papers** — the highest-value output. Give title, year, citation count,
   and `seed_reached_by`, which the output renders as "3 of your papers" —
   meaning three of *their own* papers cite it and they do not have it. Never
   quote `reached_by` as that figure.
3. **Themes** — what the query actually covers, with representative papers.
4. **Foundations** — most co-cited works.
5. **Outliers** — seeds sharing no references with the rest; usually off-topic
   search hits worth pruning.

Then recommend a concrete next step: add specific papers, run a follow-up
search for an under-covered theme, or prune off-topic seeds.

Never present a metric the graph cannot support. If the user asks for "the most
central paper" on a depth-1 graph, explain that its shape cannot answer that,
and offer coupling/co-citation or `--depth 2` instead. Never report a
truncated graph as if it were complete.

For building the corpus in the first place — searching Scopus, collections,
tags, enrichment, export — use the `scopus-for-dobby` skill.
