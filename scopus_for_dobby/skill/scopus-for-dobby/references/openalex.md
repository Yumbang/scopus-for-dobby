# OpenAlex — Open Access Links & Citation Graphs

OpenAlex (https://openalex.org) is **free and keyless** (100k requests/day, independent of the Scopus quota). Two capabilities: enrich saved articles by DOI, and export citation graphs. Use it whenever the user wants free PDFs, citation counts without Scopus charges, or a literature map.

## Setup (optional, once)

```bash
openalex email you@university.edu   # joins the "polite pool": faster, more reliable
openalex email                      # show current setting
```

Stored in `~/.scopus-for-dobby/config.json`. Everything works without it, just on the slower common pool.

## Enrichment

Matches saved articles to OpenAlex **by DOI** and writes back onto the article rows:

```bash
openalex enrich                       # whole DB; skips already-enriched articles
openalex enrich --collection thesis   # scope by collection
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
openalex graph --tag survey -d references -o refs.json    # seed = a tag
openalex graph 2-s2.0-85012345678 -d cited-by -f csv -o cites.csv   # seed = EIDs
```

- **Directions** (`-d`): `references` = what the seeds cite (backward); `cited-by` = what cites the seeds (forward — note Scopus charges extra for this, OpenAlex gives it free); `both` (default).
- **Semantics**: directed edge A → B means "A cites B". Seed nodes carry `is_seed=true`; node attributes: `label` (title), `year`, `doi`, `cited_by_count`.
- **`--per-seed-limit N`** (default 200) caps references/citers fetched per seed. The default suits small seed sets; for 100+ seeds lower it (30–50) and/or use `-d references`, otherwise the graph file grows too large to open comfortably in Gephi.
- Seeds need DOIs; seeds without one (or unknown to OpenAlex) are reported, not fatal.

### Formats (`-f`, or inferred from the `-o` extension)

| Format | Output | Open with |
|---|---|---|
| `graphml` | single `.graphml` | Gephi, Cytoscape, networkx (`nx.read_graphml`) |
| `csv` | `<stem>_nodes.csv` + `<stem>_edges.csv` | Gephi import, pandas, spreadsheets |
| `json` | node-link JSON | `networkx.node_link_graph(json.load(f))` |

## Literature-Mapping Workflow

```bash
collection create review
search-all "TITLE-ABS-KEY(...)" --max 100 --collection review   # collect candidates
openalex enrich --collection review               # OA links + fresh citation counts
openalex graph --collection review -o map.graphml # graph needs explicit --collection/
                                                  # --tag/EIDs — no working-collection
                                                  # default, unlike db add/export
```

Pass `--collection` explicitly on the search too: `search`/`search-all` do **not** honor the working collection — without `-c`, results land in the DB but in no collection, and the enrich/graph steps would operate on an empty set.

Open `map.graphml` in Gephi: cluster layout reveals research themes; high in-degree non-seed nodes are **key papers the collection cites but doesn't contain** — prime candidates for the next `abstract`/`search` round. That closes the loop: graph → spot gaps → fetch → re-graph.
