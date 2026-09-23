# Research Strategy: Direct vs. Delegated

Before running Scopus searches, assess the task scope. The concern is context-window efficiency: raw search results are verbose, and in broad research most of them get filtered out anyway. Subagents can absorb that cost and return only what matters — the database is the shared workspace that makes this safe.

## Direct mode (handle in main context)

Use when the research is focused and results are manageable:

- Single search with ≤ 25 expected results
- Quick lookups: a specific DOI, a known paper, an author profile
- Queries on already-saved articles (`db list`, `db info`, `author info`)
- Simple single-topic searches

## Delegated mode (use subagents)

Use when the research is broad, multi-step, or involves screening large result sets:

- `search-all` expecting 50+ results
- Multiple searches across different subtopics or fields
- Recursive research: extract keywords from initial results → search again
- Screening tasks: read abstracts, judge relevance, select a subset
- Any task shaped like "search, read, filter, then search again"

Check the API budget first — `auth quota` is free — and split it across subagents when it's tight. Translate the user's target paper count into per-subagent `--max` values, over-fetching ~1.5× since screening discards. Overlapping subtopics are safe: re-saving an EID updates one row and tags accumulate (see `library.md`), so the union stays de-duplicated.

## How delegated mode works

1. **Main agent creates the collection** and assigns the overall task:

   ```bash
   collection create ro-plant-research
   ```

2. **Main agent spawns subagents**, each with one search subtopic. Tell each subagent:
   - The collection to save into
   - The tag to apply (provenance — the main agent filters by it later)
   - The screening criteria
   - To return a narrative synthesis, NOT raw results

   Example subagent prompt:

   ```
   Search Scopus for articles on RO membrane biofouling at full-scale plants
   published 2018-2026. Use the scopus-for-dobby CLI:

   1. Run: search-all "TITLE-ABS-KEY(reverse osmosis AND biofouling AND full-scale)"
      --year 2018-2026 --max 100 --collection ro-plant-research --tag ro-biofouling
   2. Read through the saved abstracts and screen for papers that report
      measured biofouling rates or cleaning frequency from real plants
   3. Return a narrative synthesis:
      - How many total results vs. how many are relevant
      - Key themes and findings across the relevant papers
      - The most important 3-5 papers (with EID so I can query them)
      - Any new keywords or author names worth following up on

   Do NOT return the full list of results. Only the synthesis.
   ```

3. **Subagent does the heavy work**: searches, saves with tags, reads abstracts, screens, returns a concise report. The verbose data stays in the subagent's context and the DB.

4. **Main agent synthesizes** across reports, holding only compact summaries:
   - `db list --collection ro-plant-research --tag ro-biofouling` to drill into a subtopic
   - `db info <EID>` for any paper a subagent highlighted
   - `db stats` for the tag distribution (= coverage overview)
   - Spawn follow-up subagents for recursive searches
   - `openalex enrich --collection ro-plant-research` then `openalex graph` to map the field
   - `export --collection ro-plant-research` when done

## Tags as provenance

Tags make this work without messy sub-collections:

- Each subagent tags its results with its subtopic (`ro-biofouling`, `ro-energy`, `ro-brine`)
- All results share one collection
- The main agent navigates by tag: `db list --tag ro-biofouling`
- `db stats` shows the tag distribution — a quick map of what's been searched
- Tags flow through to `export`, so the user can export by subtopic
- When research spans several collections (e.g. one per round), group them with `project add` and pass `-p PROJ` wherever the steps above use `--collection` — it selects their deduplicated union

## Recursive search pattern

When a subagent's report surfaces new keywords or authors, spawn follow-ups without re-reading the original results:

```
Subagent 1 report: "...Kim et al. (EID: 2-s2.0-851234) developed a novel
antiscalant protocol. Keywords worth exploring: 'membrane autopsy',
'accelerated aging test'..."

→ Main agent spawns Subagent 2:
  "Search 'membrane autopsy AND reverse osmosis' and AU-ID(55666793600)
   recent work. Save to collection ro-plant-research, tag ro-autopsy.
   Screen for ..."
```

The citation graph offers a second expansion axis that costs no Scopus quota: `openalex graph --collection X -d cited-by` surfaces newer papers citing your seeds — feed the interesting ones back through `abstract <doi>`.

`fulltext` is for the **body**, not for screening. If a chosen paper's methods, quote, figure, or claim is needed, load the **paper-fulltext** skill — it carries the ask-first rules and the quota model. Then open `manifest.json` and the section markdown, not `xml/article.xml`. A large approved collection belongs in a subagent; the main context keeps the JSON summary.

The main agent's context only ever holds synthesis reports, never the hundreds of raw results that produced them.
