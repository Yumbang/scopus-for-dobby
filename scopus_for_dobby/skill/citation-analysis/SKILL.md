---
name: citation-analysis
description: "Analyze citation networks around a set of papers with scopus-for-dobby's `openalex analyze` and `openalex graph --depth`: find which highly-cited papers a search missed, split results into research themes, identify the foundational works a corpus rests on, and spot off-topic results. Use this whenever the user asks what their search results mean or whether they are complete — 'what am I missing', 'find seminal papers', 'is my literature review complete', 'group these papers by topic', 'which papers are most important here', 'build a citation network/graph', 'co-citation', 'bibliographic coupling', 'research fronts', 'Gephi'. Also use before trusting a literature search, since citation structure reveals gaps a keyword query cannot. Not for running the searches themselves or managing the library — that is the scopus-for-dobby skill."
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
intellectual base), and **gap papers** (`reached_by` × `cited_by_count`).

## Commands

```bash
# The main one — build and interpret in a single step
scopus-for-dobby openalex analyze --collection review

# Deeper: only nodes several of your papers cite get expanded
scopus-for-dobby openalex analyze --collection review --depth 2 --communities

# What would depth 3 cost? Builds depth 1, then projects
scopus-for-dobby openalex analyze --collection review --depth 3 --dry-run

# Re-analyze an existing export without spending API calls
scopus-for-dobby openalex analyze --from-file map.json --json

# Export for Gephi/networkx (analysis is a separate step)
scopus-for-dobby openalex graph --collection review --depth 2 -o map.graphml
```

Seeds come from `--collection`, `--tag`, or positional EIDs — any batch of
saved papers. Seeds need DOIs; those without one are reported, not fatal.

| Option | Meaning |
|---|---|
| `--depth 1..3` | Expansion levels. Default 1. |
| `--min-reached N` | Expand a node only if N papers you hold point at it (default 2) |
| `--max-nodes N` | Hard stop (default 5000); truncation is always reported |
| `--deep-direction` | Direction past level 1 — `references` by default, because citers cost one request *per node* |
| `--top N` | Rows per section |
| `--communities` | Cluster into themes; needs the optional `[analysis]` extra |
| `--json` | Full structured report |

`analyze` and `graph` share defaults, so the same flags produce the same graph.

## Reporting to the user

Lead with what is actionable:

1. **Coverage first** — how many seeds matched OpenAlex, how many lacked DOIs,
   whether the graph was truncated. If coverage is poor, say so *before* the
   findings; everything downstream inherits it.
2. **Gap papers** — the highest-value output. Give title, year, citation count,
   and how many of their papers cite it. `[3x]` means three of their own papers
   cite it and they do not have it.
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
