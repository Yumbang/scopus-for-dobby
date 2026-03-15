# scopus-for-dobby

Stateful CLI for searching, collecting, and managing academic papers from the Scopus database.

## Installation

```bash
cd scopus-for-dobby/agent-harness
pip install -e .
```

For Excel export support:
```bash
pip install -e ".[export]"
```

## Quick Start

```bash
# 1. Get an API key from https://dev.elsevier.com
# 2. Configure
scopus-for-dobby auth setup --api-key YOUR_KEY

# 3. Search
scopus-for-dobby search "deep learning" --sort citedby-count

# 4. Save to local DB
scopus-for-dobby db add --from-last-search --tag ml

# 5. Export
scopus-for-dobby export --format xlsx -o papers.xlsx

# Interactive mode
scopus-for-dobby
```

## Commands

| Group | Command | Description |
|-------|---------|-------------|
| `auth` | `setup` | Configure API key (and optional institutional token) |
| `auth` | `upgrade` | Add institutional token for COMPLETE view |
| `auth` | `status` | Check API connectivity and quota |
| `search` | | Search papers (auto-wraps in TITLE-ABS-KEY) |
| `search-all` | | Paginated multi-page search |
| `abstract` | | Retrieve detailed paper metadata by DOI/EID |
| `db` | `add` | Save papers to local database |
| `db` | `list` | List/filter/search saved articles |
| `db` | `remove` | Remove articles from DB |
| `db` | `tag/untag` | Manage article tags |
| `db` | `note` | Add notes to articles |
| `db` | `stats` | Database statistics |
| `collection` | `create/delete` | Manage named collections |
| `collection` | `add/remove` | Add/remove articles from collections |
| `export` | | Export to XLSX or BibTeX |

## Access Tiers

| Tier | View | Includes |
|------|------|----------|
| Free | STANDARD | Title, first author, journal, DOI, citations, affiliations |
| Institutional | COMPLETE | Above + abstract, full author list, keywords |

## Data Storage

All data is stored in `~/.scopus-for-dobby/`:
- `config.json` — API credentials (chmod 600)
- `articles.json` — Local article database
- `history` — REPL command history
