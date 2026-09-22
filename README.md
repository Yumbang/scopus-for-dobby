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

`gui` is the only extra that changes what you get: it pulls in `fastapi` and
`uvicorn`, the daemon *server*. Without it the CLI talks to DuckDB in-process —
faster startup, no background process left running — but it can still attach to
a daemon started elsewhere, because the HTTP client is a core dependency. See
[Daemon](#serve--http-daemon) below.

> The old `[cli]` and `[export]` extras are now empty aliases — their contents
> are core dependencies — so existing `".[cli,export]"` install lines keep working.

## Quick Start

```bash
# 1. Get an API key from https://dev.elsevier.com
# 2. Configure
scopus-for-dobby auth setup --api-key YOUR_KEY

# 2b. Optional but recommended — a free OpenAlex key for open-access links,
#     citation counts and graphs. Without one you share a small daily budget
#     with every other program on this machine.
#     Free at https://openalex.org/settings/api
scopus-for-dobby openalex key YOUR_OPENALEX_KEY

# 3. Search (results auto-save to local DB)
scopus-for-dobby search "deep learning" --sort citedby-count

# 4. Read a paper's body (Elsevier full text → local markdown)
scopus-for-dobby fulltext 10.1016/j.watres.2026.125855

# 5. Export
scopus-for-dobby export --format xlsx -o papers.xlsx

# Interactive mode
scopus-for-dobby
```

## Use with an AI agent

The CLI ships **agent skills** — the Scopus query syntax, the stateful library
model, OpenAlex enrichment, how to read a citation graph, when a paper's *body*
is worth fetching, and the failure modes — so an agent drives it correctly
instead of guessing at flags. Install them with the CLI itself:

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
| `paper-fulltext` | Reading one paper's body: when it is worth the quota, the markdown bundle, entitlement misses |
| `citation-analysis` | Reading a citation graph: what a search found, what it missed, what to read next |
| `corpus-profiling` | Characterising a set too large to read: topic/keyword profiles and their coverage caveats |

Only the first is a tool manual. The other three answer a *research* question, so
each gets its own entry in the agent's trigger space — a capability buried inside
the CLI reference is only found by an agent that already decided to consult one.

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
| `abstract` | | Retrieve detailed paper **metadata** by DOI/EID — not the article body |
| `fulltext` | | Fetch the Elsevier article **body** into a local markdown bundle (see below) |
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
| `openalex` | `key` / `email` | Set the free OpenAlex API key (~10x the anonymous daily budget) and polite-pool email |
| `openalex` | `enrich` | Add open-access links, OA status, and OpenAlex citation counts |
| `openalex` | `graph` | Build citation graphs (`--depth 1..3`) → GraphML / Gephi CSV / node-link JSON |
| `openalex` | `analyze` | Interpret a graph: gaps, themes, foundations, off-topic seeds (see below) |
| `profile` | | What a set of papers is *about* — topic/keyword profile with coverage |
| `export` | | Export to XLSX, BibTeX, or RIS |
| `skill` | `install` / `uninstall` / `status` / `list` / `path` | Manage the bundled agent skills (see [Use with an AI agent](#use-with-an-ai-agent)) |
| `serve` | | Run the local HTTP daemon (for the macOS GUI / multi-process access) |

### `fulltext` — the article body, not the abstract

`abstract --view FULL` gives you Scopus metadata. `fulltext` calls Elsevier
**Article Retrieval** and writes the paper itself to disk as markdown.

```bash
scopus-for-dobby fulltext 10.1016/j.watres.2026.125855   # DOI
scopus-for-dobby fulltext 2-s2.0-105035063878            # Scopus EID
scopus-for-dobby fulltext --collection thesis-refs       # a saved collection
scopus-for-dobby fulltext --indices 1,3                  # from the last search
scopus-for-dobby --json db list -c thesis-refs -n 1000 \
  | jq -r '.articles[].eid' | scopus-for-dobby fulltext --eids-from-stdin
```

Each paper becomes a directory under `~/.scopus-for-dobby/fulltext/<eid>/`:

```
manifest.json      # outline + relative paths — open this first
head.md            # title, authors, affiliations, abstract, keywords
sections/*.md      # one file per section, nested included; math as LaTeX
references.md      # bibliography, when the XML carries one
figures/<id>.jpg + <id>.caption.md
tables/<id>.md
xml/article.xml    # the original Elsevier XML
```

No separate credential and no extra: it uses the same Elsevier key as `search`,
and needs nothing beyond the core dependencies. The database only ever gets a
`fulltext_fetched_at` stamp — the body is never written into `articles.abstract`.

Fetches are **cache-first**, including for papers you never saved, and
**sequential** (Article Retrieval allows 10 req/s; concurrency only trips 429s
sooner). Failures are **per item** — a closed paper, a non-Elsevier paper, or a
malformed response is one `not_entitled` / `not_found` / `error` row, and the
rest of the batch still runs. On an entitlement miss any `oa_url` that
`openalex enrich` stored is echoed so you can try the open-access copy.

Article Retrieval draws on its own weekly budget — separate from Scopus Search
and Abstract Retrieval — so `auth quota` reports it under
`by_api.sciencedirect-article`.

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

`scopus-for-dobby serve` starts a FastAPI process on `127.0.0.1:8765` — or the
next free port, announcing the move, since that one is commonly taken; clients
read `daemon.port` —
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

`fulltext` is gated separately again: the key gets you the endpoint, but your
institution's ScienceDirect subscription decides whether a given paper returns a
body or a `not_entitled`. `auth upgrade --inst-token YOUR_TOKEN` — usually on the
institution network or VPN — is what converts most misses into fetches.

## Data Storage

All data is stored in `~/.scopus-for-dobby/`:
- `config.json` — API credentials (chmod 600)
- `articles.duckdb` — Local article database
- `fulltext/` — One directory per paper (markdown, figures, original XML), plus
  `index.json` mapping DOI → EID so a repeat fetch is a cache hit
- `session/` — Last search/abstract results
- `history` — REPL command history
