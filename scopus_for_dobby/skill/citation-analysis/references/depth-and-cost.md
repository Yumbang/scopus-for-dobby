# Depth, the relevance gate, and what it costs

## How expansion works

```
depth 0   your seeds (--collection / --project / --tag / EIDs)
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
| **1** (default) | "What did my search miss?", coverage checks, quick triage | Fast and cheap — the right default. A star, so no centrality and no meaningful communities |
| **2** | Themes, research fronts, a real coupling network | The usual choice for a literature review. Structure becomes meaningful |
| **3** | Tracing lineage back to foundational work | Rarely worth the budget. Only with a tight, well-overlapped corpus — and check `--dry-run` first, since on the anonymous budget this can exceed a whole day |

Raise `--min-reached` to 3–4 for large seed sets (50+ papers) — with more
seeds, corroboration is easier to reach, so the bar should rise with it. Lower
it to 1 only for very small corpora, and expect noise.

## Cost

**The budget is far smaller than it used to be, and this matters more than any
other tuning here.** OpenAlex bills ~$0.0001 per request against a daily
allowance:

| Caller | Daily budget | ≈ requests/day |
|---|---|---|
| Anonymous | ~$0.10, **shared per IP** | ~1,000 |
| Free API key | ~$1.00, per account | ~10,000 |

Set a key first (`openalex key <KEY>`, free at
https://openalex.org/settings/api). Everything below assumes you have one; on
the anonymous budget a single depth-2 build can consume the entire day.

- **References** are fetched 50 works per request — cheap.
- **Citers cost one paginated request per node.** This is the dominant cost:
  `-d both` on 273 seeds spends 273 requests at level 1 alone, before a single
  reference is resolved. `--direction` therefore defaults to `references`, and
  `--deep-direction` does too.
- Measured: a depth-2 graph over 273 seeds with `-d both` cost roughly **650
  requests** — about two thirds of an anonymous day's budget, or 6% of a keyed
  one.
- Exceeding the budget returns 429 with a `Retry-After` measured in *hours*
  (observed: 17h, resetting midnight UTC). There is no client-side recovery;
  the CLI reports the reset time so you do not sit polling.

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
| `--max-nodes` | `max(5000, 25 x seeds)` | Expansion budget beyond your seeds |
| `--per-seed-limit` | 200 | Caps references/citers taken per node |
| `--deep-direction` | references | Direction past level 1 |
| `--node-fields` | *(none)* | `authorships` puts author names on nodes |

### How the budget behaves — worth understanding

Depth-1 size is roughly **19-50 x the seed count** (works carry that many
references), so a corpus of 273 seeds reaches ~5,000 nodes before a single
expansion level finishes. That is why the default scales with the corpus rather
than sitting at a fixed number.

The budget is checked **between levels, never inside one**. A level either runs
completely or does not start. This matters more than it sounds: expanding only
part of a level would leave the unexpanded papers marked as though their
reference lists were complete, and every downstream measure — coupling,
co-citation, outliers — would quietly compute over papers whose references were
never fetched, in seed order rather than at random.

Level 1 always completes, whatever the budget. The cap governs expansion
*beyond* your corpus; the seeds are the input you chose.

When it does stop, `truncated: true` and `stopped_before_level: N` say exactly
where. Report that as "not expanded past depth N-1" — the levels that ran are
complete and unbiased. Prefer a tighter seed set or a higher `--min-reached`
over simply raising `--max-nodes`.

### Scaling by corpus size

| Seeds | Depth-1 nodes (approx) | Suggested `--min-reached` |
|---|---|---|
| 5 | ~200 | 2 |
| 20 | ~700 | 2 |
| 100 | ~2,000 | 2-3 |
| 270 | ~5,000 | 3 |
| 500+ | ~10,000+ | 3-4, and consider `-d references` |

With more seeds, corroboration is easier to reach, so the gate should rise with
the corpus — otherwise depth 2 expands far more than you want.

`--dry-run` itself builds depth 1, so it is not free: on 273 seeds that is
~5,000 nodes and a few hundred requests. It is still the right move before
committing to depth 2-3, but budget for it rather than treating it as a preview.

## Reusing a graph

Building is the expensive part; analysis is free. Export once, analyse many
times:

```bash
scopus-for-dobby openalex graph --collection review --depth 2 -o map.json
scopus-for-dobby openalex analyze --from-file map.json --communities
scopus-for-dobby --json openalex analyze --from-file map.json --top 50
```

`--from-file` makes **no API calls**. GraphML and JSON can both be read back;
the CSV export is write-only (it is two files, shaped for Gephi import).
