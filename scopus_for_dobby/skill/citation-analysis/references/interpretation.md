# Interpretation — what each output means, and what not to claim

## Metric validity by graph shape

| Analysis | Depth 1 | Depth ≥2 | Why |
|---|---|---|---|
| **Gap papers** | ✅ | ✅ strongest | Uses `seed_reached_by` (how many of *your* papers cite it) × `cited_by_count` (an OpenAlex attribute, complete regardless of expansion) |
| **Bibliographic coupling** | ✅ seeds only | ✅ seeds + expanded | Needs complete reference lists, which only `seed`/`expanded` nodes have |
| **Co-citation** | ✅ ≥2 seeds | ✅ richer | Same requirement, viewed from the cited side |
| **Communities on a projection** | ⚠️ thin | ✅ | Projections have real structure; the raw graph does not |
| **In-degree of a frontier node** | ⚠️ misreads | ⚠️ misreads | Not a citation count. At depth 1 it equals `seed_reached_by`; deeper it also counts expanded nodes |
| **`reached_by` read as corpus interest** | ✅ equals seed count | ❌ overstates | Includes expanded nodes at depth ≥2 — 148 vs 38 on a real corpus. Report `seed_reached_by` |
| **PageRank / betweenness / closeness** | ❌ | ⚠️ still biased | Depth 1 is a star (all paths ≤ 2 hops); deeper graphs still have a truncated frontier |
| **Communities on the raw graph** | ❌ | ❌ | A star has no community structure — the algorithm will invent groupings |

`openalex analyze` reports `topology.supports` and a `reasons` string for
anything it refuses. Quote the reason to the user rather than silently
omitting the section.

## Node roles

| Role | Meaning | Safe for structural metrics? |
|---|---|---|
| `seed` | One of the user's papers (depth 0) | Yes |
| `expanded` | Cleared the relevance gate and was fetched | Yes |
| `frontier` | Appeared as an endpoint, never expanded | **No** — edges truncated by where expansion stopped |

A frontier node with zero out-edges has not "cited nothing"; we simply never
asked. Treating that as data is the most common way to produce a wrong answer
here.

## Reading each section

### Gap papers — the headline

Ranked by `seed_reached_by` first, then `cited_by_count`. That ordering is
deliberate: a paper five of the user's own papers cite matters more to *them*
than a more famous one cited by only one.

- `[3 of your papers] … — 3095 citations` = three of their own papers cite it;
  the wider literature cites it 3095 times; **they do not have it**.
- A high citation count with `[1 of your papers]` is often a general reference
  (a methods handbook, a rate-constant table) rather than a topical gap. Say so
  instead of recommending it blindly.
- Unresolved stubs (works OpenAlex has deleted or merged) are filtered out —
  they cannot be looked up, so they are not recommendations.

**Recommend action**: fetch them with `abstract <DOI>` and add to the
collection, then re-run the analysis and watch the gap list shrink.

### Themes (communities)

Clusters over the **coupling projection** — papers grouped because they cite
the same work, not because a topic model said so. Interpret a cluster as "these
papers address a common problem", and use the representative titles to name it.

Two useful readings:
- A cluster with many of the user's papers = well covered.
- A cluster that is mostly gap papers = a subtopic their query underserves →
  suggest a follow-up search using terms from those titles.

Modularity is reported; below ~0.3 the split is weak, so hedge accordingly.

### Co-citation — the intellectual base

Pairs of works the corpus repeatedly cites *together*. These are the shared
foundations of the field as seen from this corpus. Useful for orienting a
newcomer, and for spotting a canon the user has not read.

Requires ≥2 seeds that actually share references. **Zero results is a real
finding** — "your papers share no references" means the search returned
topically unrelated work. Report it that way; it is not a failure.

### Reference age

Printed as `median <year>, N% from 2015+, N% pre-1940`. Measured over
**seed → reference** edges only, so a work ten of your papers cite counts ten
times — the question is what the corpus *reaches for*, not what happens to sit
in the graph.

The standard bibliometric read: a recent median means a fast-moving front; a
long pre-1940 tail means the field still argues with its founding literature.
On a 2025-26 quantum-foundations corpus this came out at median 2014, 46% from
2015 on, 2.2% pre-1940 — a modern-citing literature with a thin historical tail.

Quote it as a description of *their* corpus, not of the field.

### Coupling — research fronts

Pairs of the user's own papers linked by shared references. High overlap means
two papers are working the same problem, whatever their titles suggest. This is
the projection themes are computed from, so read it alongside them: a theme is
a cluster in exactly this network.

### Outlier seeds

Seeds sharing no references with any other seed. Usually keyword collisions
(a query term with a second meaning). Recommend reviewing and pruning; do not
delete anything on the user's behalf.

### Coverage

Read first, report first. Three separate things can shrink the corpus, and only
the first two were ever obvious:

- **Seeds without DOIs** never enter the graph at all.
- **Seeds not found in OpenAlex** are missing from the analysis entirely.
- **`seeds_without_references`** — matched by OpenAlex, but with no reference
  list. They inflate every seed total while contributing to no reference-based
  measure. On a real corpus this was 47 of 273, silently changing the
  denominator of coupling, co-citation and gap papers from 273 to 226. It is
  also the honest explanation for most "outlier seeds": `analyze` tags those
  `no_reference_data` rather than implying they are off-topic.

If any of the three is large relative to the corpus, every downstream finding is
partial — say so *before* presenting results, not after.

`truncated: true` means the node budget stopped expansion. Levels are atomic, so
whatever levels ran are complete and unbiased; the graph simply was not expanded
further, and `stopped_before_level` says where. Report it as "not expanded past
depth N", not as a broken result — but never present it as a full survey either.

## Honest phrasing

| Claim | Say instead |
|---|---|
| "The most influential paper is X" | "X is cited by N of your papers and has M citations overall" |
| "The field splits into 3 clusters" | "Your 40 papers split into 3 groups by shared references" |
| "This is a complete map" | "This covers what your N seeds cite, expanded M level(s)" |
| "X is central to the field" | (avoid — this graph cannot support centrality) |

The corpus is a sample of the user's making. Every finding is a statement about
*their* search results, not about the field.

## `--json` key names

The report is not flat, and coverage is not where you would guess:

| What you want | Where it is |
|---|---|
| seeds, nodes, edges, depth, truncation | `stats` |
| seeds with no reference list | `stats.seeds_without_references` (and `seeds_with_references`, the real denominator) |
| seeds OpenAlex could not match | `stats.unmatched_seeds` — **`null` means not recorded**, which is what a `--from-file` graph reports. It is not zero |
| seeds lacking a DOI | top-level `seeds_without_doi` (also unavailable from a file) |
| what the graph can support | `topology.supports` + `topology.reasons` |
| gap ranking figure | `gap_papers[].seed_reached_by` — **not** `reached_by` |
| cluster contents | `themes[].top_shared_references`, `themes[].members` (bounded by `--top`) |

A graph loaded with `--from-file` cannot report seed-match or DOI coverage: the
export does not carry it. The tool says so rather than emitting `0`.
