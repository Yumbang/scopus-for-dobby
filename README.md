# scopus-for-dobby

Stateful CLI for searching, collecting, and managing academic papers from the Scopus database.

## Installation

Runs on Python 3.10+; the project's default interpreter is **3.14** (pinned in
`.python-version`).

```bash
# CLI, REPL, and exports — this is all you need day to day
uv tool install --editable .

# Optional: add the HTTP daemon (needed by the macOS GUI, or to run
# several clients against the database at once)
uv tool install --editable ".[gui]"
```

`gui` is the only extra that changes what you get: it pulls in `fastapi`,
`uvicorn`, and `httpx`. Without it the CLI talks to DuckDB in-process — fewer
dependencies, faster startup, no background process left running. See
[Daemon](#serve--http-daemon) below.

> The old `[cli]` and `[export]` extras are now empty aliases — their contents
> are core dependencies — so existing `".[cli,export]"` install lines keep working.

## Quick Start

```bash
# 1. Get an API key from https://dev.elsevier.com
# 2. Configure
scopus-for-dobby auth setup --api-key YOUR_KEY

# 3. Search (results auto-save to local DB)
scopus-for-dobby search "deep learning" --sort citedby-count

# 4. Export
scopus-for-dobby export --format xlsx -o papers.xlsx

# Interactive mode
scopus-for-dobby
```

## Use with an AI agent

The CLI ships **agent skills** — the Scopus query syntax, the stateful library
model, OpenAlex enrichment, the failure modes, and how to read a citation graph
— so an agent drives it correctly instead of guessing at flags. Install them
with the CLI itself:

```bash
# 1. The CLI (the binary dependency)
uv tool install --editable .

# 2. The skills, for whichever agent you use
scopus-for-dobby skill install                    # Claude Code, all projects
scopus-for-dobby skill install claude --project   # just this repo
scopus-for-dobby skill install agents --project   # Codex, Cursor, Zed, Aider…
scopus-for-dobby skill install --skill citation-analysis   # just one
```

| Skill | Teaches |
|---|---|
| `scopus-for-dobby` | Driving the CLI: query syntax, the stateful library model, collections, enrichment, export |
| `citation-analysis` | Reading a citation graph: what a search found, what it missed, what to read next |
| `corpus-profiling` | Characterising a set too large to read: topic/keyword profiles and their coverage caveats |

```bash
scopus-for-dobby skill list         # every skill, target, and install path
scopus-for-dobby skill status       # installed? current, or stale since an upgrade?
scopus-for-dobby skill uninstall --skill citation-analysis
scopus-for-dobby skill install --dry-run
```

`skill status` is worth running after any upgrade: an installed copy does not
update itself, and a skill describing behaviour the CLI no longer has is worse
than none, because the agent follows it confidently.

| Target | Global | Project |
|--------|--------|---------|
| `claude` | `~/.claude/skills/scopus-for-dobby/` | `./.claude/skills/scopus-for-dobby/` |
| `agents` | `~/.agents/skills/scopus-for-dobby/` | `./.agents/skills/scopus-for-dobby/` + `AGENTS.md` |

Claude Code discovers skills on its own, so the `claude` target writes **only**
the skill directory — no `CLAUDE.md` edit. The `agents` target adds a short
pointer section to `AGENTS.md`, because those agents have no skill discovery and
would otherwise never find the directory; decline it with `--no-agents-md`. The
section sits between HTML markers, so re-running refreshes it in place and never
disturbs the rest of the file.

Because the skill is packaged with the code, upgrading the CLI and re-running
`skill install` keeps the two in step — they can't drift.

## Commands

| Group | Command | Description |
|-------|---------|-------------|
| `auth` | `setup` | Configure API key (and optional institutional token) |
| `auth` | `upgrade` / `downgrade` | Add or remove institutional token |
| `auth` | `status` | Check API connectivity and quota |
| `search` | | Search papers (auto-wraps in TITLE-ABS-KEY) |
| `search-all` | | Paginated multi-page search |
| `abstract` | | Retrieve detailed paper metadata by DOI/EID |
| `db` | `add` | Save papers to local database |
| `db` | `list` | List/filter/search saved articles |
| `db` | `remove` | Remove articles from DB |
| `db` | `tag` / `untag` | Manage article tags |
| `db` | `note` | Add notes to articles |
| `db` | `info` / `stats` | Article details and database statistics |
| `author` | `list` | List authors (auto-populated from articles) |
| `author` | `info` | Author details, articles, and co-authors |
| `author` | `fetch` | Fetch full author profile from Scopus API |
| `author` | `coauthors` / `note` | Co-author network and notes |
| `collection` | `create` / `delete` | Manage named collections |
| `collection` | `add` / `remove` | Add/remove articles from collections |
| `openalex` | `enrich` | Add open-access links, OA status, and OpenAlex citation counts (free, keyless) |
| `openalex` | `graph` | Build citation graphs (`--depth 1..3`) → GraphML / Gephi CSV / node-link JSON |
| `openalex` | `analyze` | Interpret a graph: gaps, themes, foundations, off-topic seeds (see below) |
| `profile` | | What a set of papers is *about* — topic/keyword profile with coverage |
| `export` | | Export to XLSX, BibTeX, or RIS |
| `skill` | `install` / `uninstall` / `status` / `list` / `path` | Manage the bundled agent skills (see [Use with an AI agent](#use-with-an-ai-agent)) |
| `serve` | | Run the local HTTP daemon (for the macOS GUI / multi-process access) |

### `openalex analyze` — what your search found, and missed

```bash
scopus-for-dobby openalex analyze --collection review              # depth 1
scopus-for-dobby openalex analyze --collection review --depth 2 --communities
scopus-for-dobby openalex analyze --collection review --depth 3 --dry-run
scopus-for-dobby --json openalex analyze --from-file map.json      # no API calls
```

Reports, in order of usefulness: **coverage**, **gap papers** (highly cited
work your corpus repeatedly cites but does not contain), **themes**,
**foundations** (most co-cited works), and **outlier seeds** (likely off-topic
results). Nothing is written to the database.

`--depth 2..3` expands past the seeds' immediate neighbours. Beyond level 1
only *corroborated* nodes expand — those at least `--min-reached` (default 2)
of your own papers point at — which keeps the graph on-topic and affordable:
works carry ~19–50 references each, so ungated expansion reaches millions of
nodes by depth 3. Every node carries `role` (`seed` / `expanded` / `frontier`),
`depth`, `reached_by`, and `seed_reached_by`.

Two numbers that look alike and are not: `reached_by` counts every expanding
node pointing at a work (the relevance gate's signal), while `seed_reached_by`
counts only *your* papers. At depth ≥2 they diverge sharply — on a real corpus
one work showed 148 against 38 — so gap papers rank on the latter, and the
output prints it as "N of your papers".

The node budget (`--max-nodes`, default `max(5000, 25 × seeds)`) is checked
**between levels**, never inside one, so a level either runs completely or does
not start. That keeps `role` honest: a half-expanded level would leave papers
marked as though their reference lists were complete.

That role matters for honesty: a depth-1 graph is a *star* (edges only
seed→reference and citer→seed), so PageRank and betweenness on it describe the
crawl rather than the literature. `analyze` refuses those measures and says
why, reporting bibliographic coupling and co-citation instead.

`--communities` needs the optional `analysis` extra:
`uv tool install --editable ".[analysis]"`.

### `serve` — HTTP daemon

Optional. Requires the `gui` extra: `uv pip install -e '.[gui]'`.

DuckDB permits only one read/write process per file, so how the CLI reaches the
database depends on whether a daemon is up:

| Situation | What the CLI does |
|-----------|-------------------|
| No daemon running (default) | Opens DuckDB in-process. Nothing is spawned or left behind. |
| Daemon running | Detects it via `~/.scopus-for-dobby/daemon.port` and goes over HTTP, so the GUI and CLI share one connection. |

`scopus-for-dobby serve` starts a FastAPI process on `127.0.0.1:8765` (default)
that owns the only DuckDB connection. Start it when you want the macOS GUI, or
two clients at once (e.g. an agent session alongside an open REPL) — without it,
a second concurrent process hits DuckDB's file lock. Stop it by killing the PID
at `~/.scopus-for-dobby/daemon.pid`. The macOS GUI launches it on its own.
Endpoints (auto-docs at `/docs`): `/articles`, `/collections`, `/search/fts`,
`/events`, `/events/stream` (SSE), `/health`, `/stats`.

## Access Tiers

| Tier | View | Includes |
|------|------|----------|
| Free | STANDARD | Title, first author, journal, DOI, citations, affiliations |
| Institutional | COMPLETE | Above + abstract, full author list, keywords |

## Data Storage

All data is stored in `~/.scopus-for-dobby/`:
- `config.json` — API credentials (chmod 600)
- `articles.duckdb` — Local article database
- `session/` — Last search/abstract results
- `history` — REPL command history
