# Deep Interview Spec: GUI Implementation (macOS / Swift)

## Metadata
- Rounds: 8
- Final Ambiguity: ~13%
- Type: brownfield
- Threshold: 0.20
- Status: PASSED

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|---|---|---|---|
| Goal | 0.90 | 0.35 | 0.315 |
| Constraints | 0.85 | 0.25 | 0.2125 |
| Success Criteria | 0.85 | 0.25 | 0.2125 |
| Context | 0.85 | 0.15 | 0.1275 |
| **Ambiguity** | | | **~13%** |

## Goal

Build a native macOS (Swift/SwiftUI) GUI on top of the existing scopus-for-dobby Python core. The GUI is a **single-user, personal tool** — the same person who runs Claude Code sessions to ingest papers also uses the GUI to browse, curate, and lightly edit the resulting database. The GUI is the primary management surface for the article database, replacing the CLI for routine human-driven tasks (the CLI remains the agent/automation surface).

The architecture is **split read/write**: Swift reads DuckDB directly for performance; writes are routed through `scopus-for-dobby <cmd> --json` subprocesses so business logic lives in `core/` exactly once.

## Constraints

- **Platform**: macOS 14+ only. SwiftUI as the UI framework. Official `duckdb-swift` SwiftPM package as the DB binding.
- **Single user, no distribution**: not shipping to others; no MAS / notarization / sandbox-entitlement concerns for v1. App reads/writes `~/.scopus-for-dobby/` directly.
- **Concurrent DuckDB access is a load-bearing assumption that has NOT been validated**. Phase-0 spike required (see §Prerequisite Spikes) before committing to the direct-reads architecture.
- **Writer profile**: bursty writes from interactive Claude Code sessions running scopus-for-dobby (one-shot subcommands and the long-lived REPL). Not a steady firehose.
- **Scale**: design for headroom — assume Medium baseline (10k–50k articles) using DB-backed paging and DuckDB FTS, with room to swap to virtualized rendering (NSTableView + diffable data source) if the corpus grows beyond that. Do not pre-build for 100k+.
- **Live filter must not subprocess per keystroke** — local search/filter goes direct via DuckDB FTS; the CLI is reserved for Scopus API searches and bulk imports.

## Non-Goals (v1)

- Cross-platform GUI (Linux/Windows). macOS-only is deliberate.
- Long-running GUI daemon or server. The DuckDB file + events table is the entire IPC.
- Hard-deleting articles from the GUI. Defers to CLI.
- PDF attachment management, BibTeX/RIS import, advanced query builder, citation export dialogs.
- Distribution / signing / notarization / sandbox.
- Polished UX. v1 is a "firm platform" the user dogfoods to discover what's worth polishing.

## Acceptance Criteria

### Python core (prerequisite)
- [ ] `events` table created in `core/article_db.py` with schema: `(id BIGINT PK, ts TIMESTAMP, kind VARCHAR, entity_type VARCHAR, entity_id VARCHAR, payload JSON)`.
- [ ] Every mutating function in `article_db.py` (`add_entries`, `remove_entries`, `tag_articles`, `untag_articles`, `set_note`, `create_collection`, `delete_collection`, `add_to_collection`, `remove_from_collection`, `set_author_note`, plus the new `merge_collections`) inserts an event row in the same transaction as the mutation.
- [ ] New `merge_collections(src: str, dst: str) -> dict` function that moves all articles from `src` to `dst` (set union, no duplicates), deletes `src`, and emits a `collection.merged` event.
- [ ] DuckDB FTS index on articles (title + abstract + keywords) created and refreshed on `add_entries`. A `search_articles_fts(query: str, limit: int) -> list[dict]` function exists in `core/`.
- [ ] Unit tests cover: events emitted on every mutation; `merge_collections` correctness (union, no dup, src removed); FTS index returns expected hits.

### CLI
- [ ] `--json` flag (or `--format json`) on every command the GUI will call: at minimum `search`, `add`, `collection {create,delete,merge,add,remove,list}`, `tag`, `untag`, `note`, `article {get,list}`, `export`. JSON to stdout; human progress/errors to stderr; exit codes preserved.
- [ ] Existing human-formatted output remains the default when `--json` is absent.

### Swift GUI (v1)
- [ ] App opens `~/.scopus-for-dobby/articles.duckdb` in **read-only** mode at launch and renders three panes (collections sidebar / article list / detail).
- [ ] Article list supports sort and filter on visible columns; live filter uses direct FTS (no subprocess hop).
- [ ] Multi-select works on both panes with macOS conventions: Cmd+click toggles individual, Shift+click extends a contiguous range.
- [ ] **Article-level edits in v1**: add/remove articles to/from collection (single + bulk via selection); edit notes per article in the detail pane; mass tag-apply / tag-remove on a multi-selection.
- [ ] **Collection-level edits in v1**: create, rename, merge two collections (calls `collection merge --json`).
- [ ] All mutations are routed through `scopus-for-dobby ... --json` subprocesses; the Swift app holds **no direct write connection** to DuckDB.
- [ ] Real-time sync: a `DispatchSource` file-watch on `articles.duckdb` triggers a tail query on the `events` table (`WHERE id > last_seen_id`); resulting deltas update visible views and produce subtle UI feedback (e.g., row insertion animations) when the agent writes.
- [ ] Hand-mirrored Swift structs (`Article.swift`, `Collection.swift`, `Event.swift`) match the DuckDB schema. CI test parses `CREATE TABLE` statements and diffs against a checked-in fingerprint to catch drift.

## Prerequisite Spikes

1. **DuckDB multi-process MVCC validation**. Two-process test: Python writer running `add_entries` in a loop on `articles.duckdb`; Swift process holding a `read-only` connection and querying concurrently. Confirm: no corruption; reads see committed snapshots; no deadlock; survives REPL-style long-held write connections too. **If it fails**, fall back plan: CLI exports a periodic read-only snapshot (`articles-snapshot.duckdb`) that Swift opens, and the events table drives snapshot refreshes. Decide before any Swift-side investment beyond the spike.

## Assumptions Exposed & Resolved

| Assumption (from doc) | Challenge | Resolution |
|---|---|---|
| "DuckDB supports multi-reader/single-writer" | Has it been tested across processes with a Swift binding? | No. Becomes an explicit Phase-0 spike with a defined fallback. |
| "The agent" writes in the background | What agent? | Claude Code sessions running scopus-for-dobby. Bursty/interactive, not steady. |
| "Real-time updates" matter | Why? Editing or watching? | Both: the user wants to watch ingestion and curate after. Events table earns its keep. |
| Search bar wired to `core/search.py` via CLI (step 6) | Subprocess per keystroke is too slow | Local filter goes direct via DuckDB FTS; CLI search reserved for Scopus-API calls. Adds FTS index as a prerequisite. |
| Light editing scope | What specifically? | Concrete list: collections (add/remove/merge), notes, mass tag-apply, sort/filter, multi-select. Delete defers to CLI. |
| GUI scale targets | What size library? | Unknown today; design for Medium headroom (10k–50k) with DB-paging + FTS. |

## Technical Context (Existing Code)

`scopus_for_dobby/core/article_db.py` already provides list-accepting bulk APIs that map cleanly onto the GUI's selection-driven editing model:

- `tag_articles(eids, tags)` / `untag_articles(eids, tags)` — supports mass tag editing as-is.
- `add_to_collection(name, eids)` / `remove_from_collection(name, eids)` — supports bulk collection moves as-is.
- `set_note(eid, note)`, `get_article`, `list_articles`, `list_collections`, `create_collection`, `delete_collection` — all present.

**Required additions to core**: `merge_collections`, FTS index + search function, `events` table + per-mutation event emission. Required additions to CLI: `--json` flag on the relevant subcommands, plus a `collection merge` subcommand wrapping `merge_collections`.

## Revised Build Order

Replaces the doc's §"Build order". Steps 1–4 are pure Python/CLI work, ship value to the existing CLI/REPL, and stand on their own if the Swift project never starts.

0. **Phase-0 spike**: DuckDB multi-process MVCC validation (see §Prerequisite Spikes). Gate decision on direct-reads architecture.
1. **Restructure**: `cli.py` → `cli/` subpackage; split `pyproject.toml` extras into `[cli]`, `[gui-support]`, `[export]`, `[dev]`.
2. **`events` table** + emission from every mutation in `article_db.py`. Includes `merge_collections`. Backfill with unit tests.
3. **DuckDB FTS** index on articles + `search_articles_fts` function in core.
4. **`--json` output mode** on the CLI commands the GUI will call. Add `collection merge` subcommand.
5. **Swift skeleton**: `gui-macos/` Xcode project. Open DuckDB read-only, render three-pane Zotero layout, file-watch + events-table tail. Read-only viewer that updates live as Claude Code writes.
6. **Swift write path**: shell out to `scopus-for-dobby ... --json` for collection ops, notes, mass tag-edit. Multi-select with Cmd/Shift conventions on both panes.
7. **Swift live filter**: direct FTS query bound to a search field in the article list.
8. **Schema fingerprint CI test** to catch drift between core schema and Swift structs.

## Ontology

| Entity | Type | Fields | Relationships |
|---|---|---|---|
| Article | core domain | eid, title, abstract, authors, keywords, note | belongs to many Collections; has many Tags; has one or more Authors |
| Collection | core domain | name, created_at | has many Articles |
| Tag | supporting | name | applied to many Articles |
| Author | supporting | auid, name, profile, note | wrote many Articles |
| Event | infrastructure (NEW) | id, ts, kind, entity_type, entity_id, payload | references any of the above |
| Agent (= Claude Code session) | external | n/a (process) | writes Articles/Collections/Tags via CLI |

Stable across rounds 5–8. No churn after the editing scope was concretized in Round 6.

## Open Questions Deferred Past v1

- Hard-delete articles from GUI (currently CLI-only).
- Tag rename / tag merge.
- Author-level views and editing in the GUI.
- Export dialogs (BibTeX/RIS/XLSX) wired to GUI.
- PDF attachments, full-text storage.
- Whether to ever distribute (would require: signing, notarization, sandbox entitlements for `~/.scopus-for-dobby/`, multi-library support).
