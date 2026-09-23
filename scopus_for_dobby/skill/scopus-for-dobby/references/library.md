# The Local Library — DB, Tags, Collections, Projects, Authors, Export

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
db list --project thesis --query lidar   # union of a project's collections
db list --query "transformer" -n 10    # title/abstract/keywords/notes/author/journal
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
db stats                                       # counts (incl. projects), tag/year distribution, DB size
```

`db tag/untag/remove` also accept `--eids-from-stdin` and `--eids-from-file FILE` for bulk operations from scripts. Watch the asymmetry: `db note` and `db info` take an EID argument **only** (no `--indices`) — resolve an index to its EID first, e.g. `--json db list | jq -r '.articles[2].eid'`.

**Your own notes are searchable.** `db list -q` and the FTS search both match `notes`, so a note is a way to make a paper findable by a word that appears nowhere in it. Both search paths cover the same columns — title, abstract, keywords, notes, first author, journal — so a query means the same thing whether or not DuckDB's FTS extension loaded; only the ordering differs (FTS ranks by relevance, the fallback by citations). An existing database picks up note indexing on its next `db add`, or immediately via a rebuild.

`db info <EID>` additionally reports `collections` — which collections hold that article — and `projects`, derived from those collections. Both are on the single-article record only, not on `db list` rows.

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

## Projects

A project groups **collections**, never articles directly — folder semantics, one level, no nesting. A collection belongs to at most one project; `project add` moves it out of any other (the output says `moved from X`). Deleting, removing from, or renaming a project never touches collections or articles — they are kept, just ungrouped.

```bash
project list                                  # projects, member collections, distinct paper
                                              # count; "Ungrouped: N collections"
project create thesis                         # empty project (names: non-empty, no '/')
project add thesis ch1-refs ch2-refs          # creates thesis if missing
project add thesis --match 'thesis-*' --dry-run   # bulk sort by glob; preview only
project add thesis --match 'thesis-*'
project remove thesis ch2-refs                # ungroup (also -m GLOB); collection kept
project rename thesis dissertation
project delete dissertation --confirm         # collections kept, now ungrouped
collection create lidar-refs -p thesis        # new collection straight into a project
```

- `project add` is all-or-nothing: a missing collection (`Collection(s) not found: X`) or a `--match` that matches nothing is an error and nothing changes. Quote the glob so the shell does not expand it. Always `--dry-run` a bulk sort first.
- `-p/--project NAME` selects the deduplicated union of a project's collections on `db list`, `export`, `profile`, `fulltext`, and `openalex enrich/graph/analyze`. It excludes `-c` (`Pass either --project or --collection, not both.`) and ANDs with `-t`/`-q`. An unknown project is an error (`Project not found: X`), not an empty result.
- There is no working project: `-p` is always explicit. `search`/`search-all` have no `-p` — save into a collection with `-c`, then `project add` that collection.
- `collection list` shows `[project]` after grouped collections; `collection rename` keeps the project, and `collection merge` into an existing collection keeps the destination's project.

`--json project list` shape: `{"projects": {name: {"created", "collections": [...], "collection_count", "article_count"}}}` — `article_count` is distinct papers across the project. `--json collection list` entries carry `"project": name` or `null`; ungrouped collections are found there, not in `project list` JSON.

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
export --format ris --project thesis       # every collection in the project
export --from-last-search --format ris     # export search results directly
```

- Omit `-o` → auto-generated timestamped filename.
- XLSX is tier-aware: abstract/author columns appear only when the data exists.
- Keywords are normalized per format: one `KW` line each in RIS, comma-joined in BibTeX, `"; "`-joined in the XLSX cell.
- With a working collection set and no `--collection`/`--from-last-search`, export defaults to the working collection; a `--tag` filter applies *on top of* it, not instead of it. An explicit `--project` bypasses the working collection (it excludes `--collection`).
- `--from-last-search` exports the raw last-search results and ignores `--collection`, `--tag`, and the working collection. To export a filtered subset, save to the DB first, then export by `--collection`/`--tag`.
- A database export reads at most 100,000 matching rows (the same ceiling as `profile`, `fulltext`, and `openalex`). Past that, the file is still written and the command says `Exported N of M matching (K total in DB)` — the same shape as `db list`, with the verb the action actually performed.
- `--json export` prints one object. Success keys: `exported`, `format`, `output`, `tier` (xlsx only), and for a database export `total_matching` and `total_in_db`. `truncated` appears only when the ceiling cut the file short. An empty library is `{"exported": 0, "format": "...", "output": null, "reason": "no articles"}`; an empty `--from-last-search` uses `"reason": "no search results"`.

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
