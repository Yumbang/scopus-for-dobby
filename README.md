# scopus-for-dobby

Stateful CLI for searching, collecting, and managing academic papers from the Scopus database.

## Installation

```bash
uv tool install -e ".[export]"
```

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
| `export` | | Export to XLSX or BibTeX |
| `serve` | | Run the local HTTP daemon (for the macOS GUI / multi-process access) |

### `serve` — HTTP daemon

`scopus-for-dobby serve` starts a FastAPI process bound to `127.0.0.1:8765` (default) that owns the only DuckDB connection. While the daemon is running, the CLI refuses mutating subcommands so the file lock is never contended. Stop it by killing the PID at `~/.scopus-for-dobby/daemon.pid`. Install with `uv pip install -e '.[gui-support]'`. Endpoints (auto-docs at `/docs`): `/articles`, `/collections`, `/search/fts`, `/events`, `/events/stream` (SSE), `/health`, `/stats`.

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
