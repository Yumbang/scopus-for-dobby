# Workflows

Each ends with something to tell the user, not a file.

## 1. Triage a search — "is this any good?"

Run immediately after a search, before the user invests in reading.

```bash
collection create review && collection set review
search-all "TITLE-ABS-KEY(...)" --max 100 -c review   # -c is required; search
                                                      # ignores the working collection
openalex analyze --collection review
```

Read in this order:

1. **Coverage** — seeds matched, seeds without DOIs. Poor coverage invalidates
   everything downstream; report it first.
2. **Outlier seeds** — if many, the query is ambiguous. Suggest narrowing it
   (add a field code, exclude a term) rather than reading 100 papers.
3. **Gap papers with high `reached_by`** — if the top gaps are obviously
   central to the topic, the query missed a core cluster. That usually means a
   vocabulary mismatch; propose search terms from the gap titles.

**Report**: "Your search returned N papers. M look off-topic. It repeatedly
cites K papers you don't have — the top ones are …, which suggests adding the
term '…' to your query."

## 2. Gap-driven expansion — the main loop

```bash
openalex analyze --collection review --top 20
# pick the gaps worth having
abstract 10.1021/es035121o          # fetches and saves
collection add review --eid 2-s2.0-...
openalex analyze --collection review # re-run; the gap list should shrink
```

Each round pulls in what the corpus keeps pointing at. Stop when the top gaps
are general references (methods handbooks, rate tables) rather than topical
work — that means the topical core is covered.

Do not add papers on the user's behalf without asking; present the candidates
with citation counts and `reached_by`, and let them choose.

## 3. Theme mapping — "what is actually in here?"

Needs depth 2 for meaningful structure, and the `[analysis]` extra.

```bash
openalex analyze --collection review --depth 2 --communities --top 15
```

For each cluster: name it from the representative titles, count how many of the
user's own papers are in it, and note whether its gap papers outnumber them.

**Report**: "Your 60 papers fall into 3 groups: (a) … (28 papers, well
covered), (b) … (19), (c) … (6 papers but 14 highly-cited gaps — likely
under-covered; consider a dedicated search)."

That last observation — a cluster where gaps outnumber holdings — is usually
the most valuable thing in the whole analysis.

## 4. Foundations — "what should I read first?"

```bash
openalex analyze --collection review --depth 2 --top 20
```

Use the co-citation section: works repeatedly cited *together* are the shared
base. Combined with publication year, they give a reading order — foundations
first, then the recent fronts from the coupling clusters.

Useful for onboarding, literature-review introductions, and checking whether a
canonical work has been missed.

## 5. Hand off to Gephi

Only when the user wants to explore visually. Analysis first, picture second.

```bash
openalex graph --collection review --depth 2 -o map.graphml
```

In Gephi: layout with ForceAtlas2, size nodes by `cited_by_count`, colour by
`role` (or `depth`), filter `reached_by >= 2` to strip one-off references.

For networkx — pass `edges="edges"` explicitly, which works on every version:

```python
import json, networkx as nx
G = nx.node_link_graph(json.load(open("map.json")), edges="edges")
seeds = [n for n, d in G.nodes(data=True) if d.get("role") == "seed"]
```

The export keys its edge list `edges`. networkx 3.6 made that the default, so
the bare `node_link_graph(data)` call works there; 3.4/3.5 still default to the
older `links` and need the keyword. Passing it explicitly is correct on all of
them. (`nx.read_graphml` has no such wrinkle.)

Anything structural you compute there is subject to the same caveats — see
`interpretation.md`. In particular, do not run centrality over a graph that
includes `frontier` nodes and present it as a property of the field.

## 6. Compare two collections

```bash
scopus-for-dobby --json openalex analyze --collection method-a > a.json
scopus-for-dobby --json openalex analyze --collection method-b > b.json
```

Compare the `co_citation` sections: shared foundations mean the two literatures
are connected; disjoint bases mean genuinely separate communities, which is
itself a finding worth reporting.
