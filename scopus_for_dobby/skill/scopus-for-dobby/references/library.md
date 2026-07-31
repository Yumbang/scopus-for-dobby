# The Local Library — DB, Tags, Collections, Authors, Export

## Adding Articles

Search results auto-save. Manual control:

```bash
db add --from-last-search                  # all results from last search
db add --indices 1,3,5                     # specific items by index
db add --from-last-abstract                # last retrieved abstract
db add --from-last-search --tag survey --collection thesis
```

If a working collection is set (see below) and no `--collection` is given, `db add` adds into it and prints `Using working collection 'X'`.

Saves are idempotent by EID: re-saving an existing article updates the row in place (never duplicates) and **tags accumulate** — a paper found by several searches or subagents carries the union of their tags on one row.

## Listing & Filtering

```bash
db list                                # all articles, newest-added first
db list --tag survey --sort cited      # filter by tag, sort by citations
db list --collection thesis-refs
db list --query "transformer" -n 10    # text search in title/author/journal/abstract
```

Sort: `added` (default), `cited`, `date`, `title`. The default page size is 50 — pass `-n 1000` (or higher) when you need a whole collection, or the result silently truncates. The list result becomes the "current results" — indices in subsequent commands refer to it.

## Tags, Notes, Details, Removal

```bash
db tag --indices 1,2,3 survey important        # tag by index (multiple tags OK)
db tag --eid 2-s2.0-8501234 ml deep-learning   # tag by EID
db untag --indices 1,2 survey
db note 2-s2.0-85012345678 "Good methodology section"
db info 2-s2.0-85012345678                     # full saved record
db remove --indices 1,3 --confirm              # --confirm skips the y/n prompt
db stats                                       # counts, tag/year distribution, DB size
```

`db tag/untag/remove` also accept `--eids-from-stdin` and `--eids-from-file FILE` for bulk operations from scripts. Watch the asymmetry: `db note` and `db info` take an EID argument **only** (no `--indices`) — resolve an index to its EID first, e.g. `--json db list | jq -r '.articles[2].eid'`.

## Collections

Collections group articles without touching tags or the main DB. Deleting a collection keeps the articles.

```bash
collection list
collection create thesis-refs
collection add thesis-refs --indices 1,3,5     # or --eid 2-s2.0-...
collection remove thesis-refs --indices 2
collection merge old-name target-name          # set union, then deletes old-name
collection rename old-name new-name
collection delete thesis-refs --confirm
```

### Working Collection

A git-checkout-style default that persists across CLI invocations:

```bash
collection set thesis-refs    # db add & export now default into thesis-refs
collection current            # show it
collection unset              # clear (or: collection set --clear)
```

An explicit `--collection` flag always overrides it. The REPL prompt displays the active working collection. Set it at the start of a research session so every save lands in the right place; unset it when done so later work doesn't silently leak into the old collection.

## Authors

Authors are **auto-extracted** every time articles are saved; a junction table tracks author position, first-author, and corresponding-author flags. The corresponding-author flag is only populated by `abstract --view FULL` (search results never carry it — see `search.md`).

```bash
author list                          # sorted by paper count
author list --query "Kim" --sort name
author info 55666793600              # details + their saved articles + co-authors
author coauthors 55666793600         # co-author network from the local DB
author fetch 55666793600             # Scopus Author API: h-index, ORCID, doc count,
                                     # citation count, subject areas, affiliation
author note 55666793600 "Potential collaborator"
```

## Export

```bash
export --format xlsx -o papers.xlsx        # Excel: styled headers, filters
export --format bibtex -o refs.bib
export --format ris -o refs.ris            # EndNote / Zotero / Mendeley
export --format xlsx --collection thesis-refs
export --format bibtex --tag survey
export --from-last-search --format ris     # export search results directly
```

- Omit `-o` → auto-generated timestamped filename.
- XLSX is tier-aware: abstract/author columns appear only when the data exists.
- Keywords are normalized per format: one `KW` line each in RIS, comma-joined in BibTeX, `"; "`-joined in the XLSX cell.
- With a working collection set and no `--collection`/`--from-last-search`, export defaults to the working collection; a `--tag` filter applies *on top of* it, not instead of it.
- `--from-last-search` exports the raw last-search results and ignores `--collection`, `--tag`, and the working collection. To export a filtered subset, save to the DB first, then export by `--collection`/`--tag`.

## Scripting with --json

`--json` (global flag, before the subcommand) emits machine-readable output and strips internal `_`-prefixed keys. This is the supported way to feed other tools — never read `articles.duckdb` directly while anything else might have it open (DuckDB is single-writer; see `troubleshooting.md`).

```bash
# EIDs of a collection → bulk operation
scopus-for-dobby --json db list --collection thesis -n 1000 | jq -r '.articles[].eid'

# Tag everything matching a text query
scopus-for-dobby --json db list --query "biofouling" -n 500 \
  | jq -r '.articles[].eid' \
  | scopus-for-dobby db tag --eids-from-stdin biofouling

# Quota check before a batch job
scopus-for-dobby --json auth quota
```

`db list` JSON shape: `{"articles": [...], "total_matching": N, "total_in_db": M}`. Each article object carries the DB columns as flat keys: `eid`, `doi`, `title`, `first_author`, `journal`, `cover_date`, `cited_by`, `abstract`, `keywords`, plus the OpenAlex fields once enriched — `oa_status`, `oa_url`, `openalex_cited_by`, `openalex_topics`. Internal keys (`_tags`, `_notes`, `_added_at`) are stripped from `--json` output — filter by tag with `db list --tag X`, not in jq.

```bash
# Free-to-read list (titles + links) after `openalex enrich`
scopus-for-dobby --json db list --collection thesis-refs -n 1000 \
  | jq -r '.articles[] | select(.oa_url != null and .oa_url != "") | "\(.title)\t\(.oa_url)"'
```

## Full Reset

Delete the database file — it is recreated (current schema) on next use:

```bash
rm ~/.scopus-for-dobby/articles.duckdb
```
