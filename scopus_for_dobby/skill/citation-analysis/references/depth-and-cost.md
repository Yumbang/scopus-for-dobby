# Depth, the relevance gate, and what it costs

## How expansion works

```
depth 0   your seeds (--collection / --tag / EIDs)
depth 1   every seed expanded: references + citers    (--direction)
depth 2   expand a node only if reached_by >= --min-reached
depth 3   same gate again
          hard stop at --max-nodes
```

`reached_by` counts **distinct papers already in the graph that point at a
node**. It is the relevance signal: a work five of your papers cite is on your
topic; one that a single paper cites once may be incidental.

Without that gate, depth is unusable. OpenAlex works carry ~35–50 references
each, so 20 seeds give roughly:

| Depth | Ungated | Gated (`--min-reached 2`) |
|---|---|---|
| 1 | ~700 nodes | ~700 nodes (no gate at level 1) |
| 2 | ~15,000–25,000 | typically a few hundred |
| 3 | millions | typically low thousands |

Real measurement from a 5-seed collection: **211 nodes at depth 1, of which
only 3 cleared a gate of 2.** Depth 2 came to 1,200 nodes — bounded, and every
added node was corroborated by at least two papers.

The gate, not the depth number, decides how far this actually goes. Asking for
`--depth 3` on a corpus with little overlap may add nothing, which is correct
behaviour, not a bug.

## Choosing a depth

| Depth | Use for | Notes |
|---|---|---|
| **1** (default) | "What did my search miss?", coverage checks, quick triage | Fast, cheap. A star — no centrality, no meaningful communities |
| **2** | Themes, research fronts, a real coupling network | The usual choice for a literature review. Structure becomes meaningful |
| **3** | Tracing lineage back to foundational work | Only worth it with a tight, well-overlapped corpus; otherwise the gate stops it early anyway |

Raise `--min-reached` to 3–4 for large seed sets (50+ papers) — with more
seeds, corroboration is easier to reach, so the bar should rise with it. Lower
it to 1 only for very small corpora, and expect noise.

## Cost

- **References** are fetched 50 works per request — cheap.
- **Citers** cost **one paginated request per node**. That is why
  `--deep-direction` defaults to `references`: at depth 3 with citers enabled,
  a thousand expanded nodes means a thousand requests.
- OpenAlex allows 100k requests/day and ~10/s; the client throttles itself.
  Set a polite-pool email once (`openalex email you@uni.edu`) for better
  service.

Estimate before committing to a big run:

```bash
scopus-for-dobby openalex analyze --collection review --depth 3 --dry-run
```

It builds depth 1 (needed anyway, and cheap), then reports how many nodes clear
the gate for the next level — **exactly** for the level immediately after the
current one, and as a projection beyond that, labelled as such.

## Budget controls

| Option | Default | Effect |
|---|---|---|
| `--min-reached` | 2 | The relevance gate. The main lever |
| `--max-nodes` | 5000 | Hard stop; sets `truncated: true` |
| `--per-seed-limit` | 200 | Caps references/citers taken per node |
| `--deep-direction` | references | Direction past level 1 |

Truncation is always reported. If `truncated` is true, tell the user the
findings are partial and suggest either a tighter seed set or a higher
`--min-reached` rather than simply raising `--max-nodes`.

## Reusing a graph

Building is the expensive part; analysis is free. Export once, analyse many
times:

```bash
scopus-for-dobby openalex graph --collection review --depth 2 -o map.json
scopus-for-dobby openalex analyze --from-file map.json --communities
scopus-for-dobby openalex analyze --from-file map.json --top 50 --json
```

`--from-file` makes **no API calls**. GraphML and JSON can both be read back;
the CSV export is write-only (it is two files, shaped for Gephi import).
