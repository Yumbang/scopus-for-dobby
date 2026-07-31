---
name: scopus-for-dobby
description: "Reference guide for using the scopus-for-dobby CLI — a stateful tool for searching Scopus, collecting papers into a local DuckDB database, managing collections/tags/authors, enriching with OpenAlex (open-access links, citation graphs), and exporting to XLSX/BibTeX/RIS. Use this skill whenever the user asks how to use scopus-for-dobby, wants to search Scopus, manage their paper database, export references, work with authors, find open-access PDFs, build citation graphs, or anything related to their academic paper management CLI. Also trigger when the user mentions Scopus queries, OpenAlex, field codes, paper collections, citation management, or the dobby REPL."
---

# scopus-for-dobby — CLI Reference

A stateful CLI for the Elsevier Scopus API with free OpenAlex enrichment. Search academic papers, collect them into a local DuckDB database, organize with tags and collections, track authors, find open-access PDFs, export citation graphs, and produce XLSX/BibTeX/RIS bibliographies.

Architecture in one line: each command opens the local DuckDB database in-process — unless a daemon is already running (started by `serve` or the macOS GUI), in which case it goes over HTTP so both share the one connection. All user data lives under `~/.scopus-for-dobby/`.

## Reference files — read before deep work

| File | Read when |
|---|---|
| `references/search.md` | Building Scopus queries (field codes, filters), fetching abstracts, tier differences, API quota |
| `references/library.md` | Managing the local DB: tags, collections, working collection, authors, export, `--json` scripting |
| `references/openalex.md` | Open-access links, OpenAlex enrichment, citation-graph export (Gephi/networkx) |
| `references/research-strategy.md` | Any broad/multi-topic literature research — decide direct vs. subagent-delegated **before** searching |
| `references/troubleshooting.md` | CLI hangs, daemon errors, slow first run, 429s, resetting the DB |

For a quick one-off command, the map below is usually enough; for multi-step work, read the relevant reference first — the flags and stateful behaviors there change how you should sequence commands.

## Quick Start

```bash
# The CLI is a separate binary dependency — this skill drives it, it does not
# ship it. Check first; install from a repo checkout only if missing.
scopus-for-dobby --help >/dev/null 2>&1 || uv tool install --editable .
# Optional `[gui]` extra adds the HTTP daemon (macOS GUI / concurrent clients):
#   uv tool install --editable ".[gui]"

# Configure API key (free at https://dev.elsevier.com)
scopus-for-dobby auth setup --api-key YOUR_KEY
# Institutional tier (abstracts, full author lists):
scopus-for-dobby auth setup --api-key YOUR_KEY --inst-token YOUR_TOKEN

scopus-for-dobby                      # interactive REPL (default)
scopus-for-dobby search "deep learning" --limit 20   # or direct subcommands
```

## Command Map

| Command | Does |
|---|---|
| `auth setup / status / quota / upgrade / downgrade / logout` | Credentials; `quota` shows remaining API budget **without** spending a call |
| `search <query> [-n] [-s] [-y] [--subject] [-t] [-c] [--no-save]` | Scopus search, auto-saved to DB (max 25/page) |
| `search-all <query> --max N` | Paginated search (multiple API calls) |
| `abstract <DOI\|EID\|ScopusID> [--view FULL]` | Single-paper metadata, auto-saved; `FULL` adds abstract text, full author list, keywords, subject areas (institutional tier — see `references/search.md`) |
| `db add / list / info / tag / untag / note / remove / stats` | Local article database (`note`/`info` take an EID only — no `--indices`) |
| `collection list / create / add / remove / delete / merge / rename` | Group articles (tags stay independent) |
| `collection set / unset / current` | **Working collection** — becomes the default for `db add` and `export` |
| `author list / info / coauthors / fetch / note` | Author DB (auto-extracted); `fetch` pulls h-index/ORCID from Scopus |
| `export --format xlsx\|bibtex\|ris [-o] [-t] [-c] [--from-last-search]` | Bibliography export |
| `openalex enrich / graph / email` | Free keyless enrichment: OA PDF links, citation counts, topics; citation-graph files |
| `serve [--port] [--idle-timeout]` | Start the HTTP daemon (needs the `[gui]` extra). Only needed for the macOS GUI, or to run two clients at once — see `references/troubleshooting.md` |

Global flag: `--json` before the command gives machine-readable output (`scopus-for-dobby --json db stats`).

## The Stateful Model (read this — it changes command behavior)

Results persist across commands and CLI invocations, which is what makes index-based workflows possible:

1. `search "deep learning"` → results become the **last search** (and are auto-saved to the DB)
2. `db add --indices 1,3` / `db tag --indices 1,3 ml` / `collection add X --indices 1,3` → indices refer to the last search/list
3. `db list ...` → its output becomes the new "current results" for subsequent index commands
4. `collection set thesis` → the **working collection**: `db add` and `export` now default into `thesis` until `collection unset`. An explicit `--collection` always wins. The REPL prompt shows the active one.

Session state lives in `~/.scopus-for-dobby/session/`; it survives across invocations, so an index-based command can act on a search from a previous shell.

## REPL Mode

`scopus-for-dobby` with no subcommand opens a REPL — same commands without the prefix, plus history, auto-suggestions, and a quota display. Prefer direct subcommands when scripting or working as an agent; the REPL is for humans.

## Common Workflows

```bash
# Literature review end-to-end
collection create my-review
collection set my-review                      # db add & export default here now
# search/search-all do NOT use the working collection — pass -c explicitly:
search-all "TITLE-ABS-KEY(deep learning AND medical imaging)" --max 100 \
  --tag dl-imaging -c my-review
openalex enrich --collection my-review        # free OA links + citation counts by DOI
openalex graph --collection my-review -o review_map.graphml   # citation graph → Gephi
export --format xlsx -o review_papers.xlsx    # exports my-review (working collection)

# Track an author
search "AU-ID(55666793600)" --sort -pubyear
author fetch 55666793600 && author info 55666793600

# References for a manuscript
collection create ms-refs && collection set ms-refs
# ...search; results auto-save; curate with db add --indices / collection add...
export --format bibtex -o refs.bib
```

For broad research (multiple subtopics, screening 50+ results), do NOT run everything in the main context — read `references/research-strategy.md` first and delegate searches to subagents with tags as provenance. Raw search results are verbose and will flood the context window.
