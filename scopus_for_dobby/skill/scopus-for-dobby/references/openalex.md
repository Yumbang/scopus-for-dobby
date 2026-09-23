# OpenAlex — Open Access Links & Citation Graphs

OpenAlex (https://openalex.org) is free to use and independent of the Scopus quota, but it is **not unmetered**. It bills a daily budget at roughly **$0.0001 per request**:

| Caller | Daily budget | ≈ requests/day |
|---|---|---|
| Anonymous (no key) | ~$0.10, **shared per IP address** | ~1,000 |
| With a free API key | ~$1.00, billed to your account | ~10,000 |

**Set an API key.** It is free, takes a minute, and is the difference between
~1,000 and ~10,000 requests a day — and it moves you off a bucket shared with
every other program on the machine. Without one, an unrelated script can
exhaust your allowance and this CLI becomes collateral damage.

## Setup (do this once)

```bash
openalex key YOUR_KEY               # free at https://openalex.org/settings/api
openalex key                        # show whether one is set (never prints it)
openalex email you@university.edu   # polite pool: politeness, NOT extra budget
```

Both are stored in `~/.scopus-for-dobby/config.json` (chmod 600).

The polite-pool email affects queueing, **not** your allowance — a rate-limited
IP returns 429 identically with and without it. Only a key changes the budget.

## Enrichment

Matches saved articles to OpenAlex **by DOI** and writes back onto the article rows:

```bash
openalex enrich                       # whole DB; skips already-enriched articles
openalex enrich --collection thesis   # scope by collection
openalex enrich --project thesis      # ...or by every collection in a project
openalex enrich --tag ml --force      # --force re-enriches even if already done
openalex enrich -n 50                 # cap the batch
```

Fields written: `openalex_id`, `oa_status` (gold / green / hybrid / bronze / closed), `oa_url` (best link — a direct PDF when available, otherwise the landing page), `openalex_cited_by` (OpenAlex citation count, often fresher than Scopus), `openalex_topics` (up to 5 labels), `openalex_enriched_at`.

Articles without a DOI are skipped and counted in the summary; DOIs unknown to OpenAlex are reported as `not_in_openalex`. Requests are batched 50 DOIs per call, so even large libraries enrich in a handful of requests.

Coverage and re-runs:

- Auto-saved Scopus results normally include a DOI; items without one (some conference papers, reports) drop out of both enrichment and graph seeds — check the skipped counts in the summary before trusting coverage.
- A plain re-run retries DOIs that previously weren't found (they still have no `openalex_id`); `--force` is only needed to refresh already-enriched articles.
- The stored fields cannot distinguish a direct PDF from a landing page — `oa_url` holds whichever was best. Treat `oa_status` in {gold, green, hybrid, bronze} as "free to read", with the caveat that some links open a page rather than a file.

For one paper, `db info <EID>` shows the OA link. For a whole collection, build the free-to-read list with `--json` (per-article key list in `library.md`):

```bash
scopus-for-dobby --json db list --collection thesis-refs -n 1000 \
  | jq -r '.articles[] | select(.oa_url != null and .oa_url != "") | "\(.title)\t\(.oa_url)"'
```

## Citation Graphs

Builds a graph around seed articles and writes it to a **file** — graphs are never stored in the database.

```bash
openalex graph --collection thesis -o thesis.graphml      # seed = a collection
openalex graph --project thesis -o thesis.graphml         # seed = a project's collections
openalex graph --tag survey -d references -o refs.json    # seed = a tag
openalex graph 2-s2.0-85012345678 -d cited-by -f csv -o cites.csv   # seed = EIDs
```

- **Directions** (`-d`, default `references`): `references` = what the seeds cite (backward, batched 50/request — cheap); `cited-by` = what cites the seeds (forward; Scopus charges extra for this, OpenAlex does not — but it costs **one request per seed**); `both` = each of the above. The default is `references` because on 273 seeds `both` spends 273 requests before resolving a single reference.
- **Semantics**: directed edge A → B means "A cites B". Seed nodes carry `is_seed=true`; node attributes: `label` (title), `year`, `doi`, `cited_by_count`.
- **`--per-seed-limit N`** (default 200) caps references/citers fetched per seed. The default suits small seed sets; for 100+ seeds lower it (30–50) and/or use `-d references`, otherwise the graph file grows too large to open comfortably in Gephi.
- `--project` takes the deduplicated union of the project's collections and excludes `--collection`; an unknown project is an error, not an empty seed set.
- Seeds need DOIs; seeds without one (or unknown to OpenAlex) are reported, not fatal.

### Formats (`-f`, or inferred from the `-o` extension)

| Format | Output | Open with |
|---|---|---|
| `graphml` | single `.graphml` | Gephi, Cytoscape, networkx (`nx.read_graphml`) |
| `csv` | `<stem>_nodes.csv` + `<stem>_edges.csv` | Gephi import, pandas, spreadsheets |
| `json` | node-link JSON | `networkx.node_link_graph(json.load(f), edges="edges")` |

### Depth and analysis

`--depth 1..3` expands further than the seeds' immediate neighbours. Past level
1 only **corroborated** nodes expand — those at least `--min-reached` (default
2) of your papers point at — which is what keeps depth affordable and on-topic.
Nodes carry `role` (`seed` / `expanded` / `frontier`), `depth`, `reached_by`,
and `seed_reached_by` (how many of *your* papers cite it — the one to report).

To *interpret* a graph rather than export it, use `openalex analyze` — coverage,
papers your corpus cites but lacks, themes, and foundational works:

```bash
scopus-for-dobby openalex analyze --collection review --depth 2
scopus-for-dobby openalex analyze --project review   # seeds = a project's collections
```

**For anything beyond building the file — which metrics this graph shape can
support, how to read the output, how deep to go — use the `citation-analysis`
skill.** It matters: a depth-1 graph is a star, so centrality measures on it
describe the crawl rather than the literature.

## Literature-Mapping Workflow

```bash
collection create review
search-all "TITLE-ABS-KEY(...)" --max 100 --collection review   # collect candidates
openalex enrich --collection review               # OA links + fresh citation counts
openalex graph --collection review -o map.graphml # graph needs explicit --collection/
                                                  # --project/--tag/EIDs — no working-
                                                  # collection or project default,
                                                  # unlike db add/export
```

Pass `--collection` explicitly on the search too: `search`/`search-all` do **not** honor the working collection — without `-c`, results land in the DB but in no collection, and the enrich/graph steps would operate on an empty set. There is no `search -p`; to grow a project, search into a new collection and `project add` it — then `--project` covers it in every step above.

Open `map.graphml` in Gephi: cluster layout reveals research themes; high in-degree non-seed nodes are **key papers the collection cites but doesn't contain** — prime candidates for the next `abstract`/`search` round. To **read** a chosen paper's methods or claims, that is the **paper-fulltext** skill (it decides when to ask first). That closes the loop: graph → spot gaps → fetch metadata → (if needed) body → re-graph.
