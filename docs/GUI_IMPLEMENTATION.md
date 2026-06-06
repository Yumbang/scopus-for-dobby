# GUI Implementation Guide

> **⚠ SUPERSEDED (2026-04-29).** The split-read/CLI-write architecture below is **not viable**: DuckDB 1.5.0 enforces an exclusive OS file lock per process, so Swift cannot open the file read-only while Python holds RW. See `spikes/duckdb_mvcc/REPORT.md` for the spike result and `.omc/plans/gui-implementation-plan.md` for the adopted replacement (**Plan C — HTTP daemon**: `scopus-for-dobby serve`, FastAPI process owns the only DuckDB connection, GUI calls HTTP + SSE).
>
> This document is kept for historical context only. Do not implement against it.

A native macOS (Swift/SwiftUI) GUI on top of the existing Python core. The CLI remains the agent-facing interface; the GUI is the human-facing one. Both share `scopus_for_dobby/core/` as the single source of truth for data and behavior.

## Goals

- A Zotero/EndNote-style three-pane app: collections/tags/authors → article list → detail view.
- Real-time updates as the agent collects and modifies the database in the background.
- No duplication of business logic between CLI and GUI.

## Architecture: split read and write paths

The GUI **reads DuckDB directly** and **writes through the CLI**. This is asymmetric on purpose.

```
┌──────────────┐   reads (DuckDB file, read-only)   ┌──────────────────┐
│  Swift GUI   │ ──────────────────────────────────► articles.duckdb  │
│              │                                     │                  │
│              │   writes (subprocess: CLI --json)   │                  │
│              │ ──► scopus-for-dobby ──► core/ ────►                   │
└──────────────┘                                     └──────────────────┘
       ▲                                                      │
       │ file-watch + events-table tail                       │
       └──────────────────────────────────────────────────────┘
                         (agent writes here too,
                          via the same CLI surface)
```

### Why direct reads

DuckDB supports multiple concurrent readers alongside a single writer. The Swift app can hold a read-only connection and query the same file the agent is writing to without coordination. This buys us:

- **Native list performance.** No subprocess hop on every scroll, sort, or filter.
- **Real-time without a server.** A file-watcher plus an events-table tail is enough; no IPC layer to design or maintain.
- **The GUI stays "just a viewer"** of the same source of truth the agent sees. There is no GUI-only state to drift.

### Why writes go through the CLI

If the GUI wrote directly, every mutation would need to be implemented twice — once in Python `core/`, once in Swift. Routing writes through `scopus-for-dobby <cmd> --json` means:

- One implementation of every mutation, in `core/`.
- The agent and the GUI exercise identical code paths. No "works in CLI, broken in GUI" class of bug.
- Schema migrations only happen in one language.

The cost is ~50–200 ms per write (subprocess startup). For a human-driven app this is invisible; for the agent's bulk inserts, the CLI is in-process anyway.

## Real-time sync mechanism

Two layers, used together:

1. **File-watch on `articles.duckdb`** via `DispatchSource.makeFileSystemObjectSource`. Coarse signal: "something changed, re-query visible views." Native, no polling.

2. **`events` table tail.** A new append-only table in `core/article_db.py`:

   ```sql
   CREATE TABLE events (
     id BIGINT PRIMARY KEY,
     ts TIMESTAMP,
     kind VARCHAR,           -- 'article.added', 'collection.created', 'tag.applied', ...
     entity_type VARCHAR,    -- 'article', 'collection', 'author', 'tag'
     entity_id VARCHAR,
     payload JSON
   );
   ```

   Every write path in `article_db.py` inserts a row. The GUI tracks `last_seen_id` and queries `WHERE id > last_seen_id` on each file-watch tick. This gives the GUI **what changed**, not just **that something changed** — enough to drive precise SwiftUI animations ("3 new articles appeared in collection X") and toast notifications.

The events table is also useful to the CLI/REPL itself, so it isn't GUI-only infrastructure.

## CLI changes required

The CLI currently formats output for humans. The GUI needs machine-readable output:

- Add `--json` (or `--format json`) to every command the GUI will call: `search`, `add`, `collection`, `tag`, `author`, `export`.
- JSON output goes to stdout; human-readable progress/errors go to stderr.
- Exit codes already convey success/failure; preserve that.

This is also a quality improvement for agent use of the CLI — agents currently have to parse human-formatted text.

## Schema contract between Python and Swift

There is no codegen. The schema surface is small enough that hand-mirrored Swift structs (`Article.swift`, `Collection.swift`, `Event.swift`) are cheaper than a code generator and its build step.

**Rule:** any change to a column in `core/article_db.py` lands in the same PR as the matching Swift struct change. CI can enforce this with a simple test that parses the `CREATE TABLE` statements and diffs against a checked-in schema fingerprint, if drift becomes a problem.

## Repository layout

The GUI lives in this repo, not a separate one. The core is small (~2k lines) and the two interfaces will iterate together on schema and behavior.

```
scopus-for-dobby/
  scopus_for_dobby/
    core/          # pure library — already has no UI imports
    cli/           # current cli.py + repl_skin.py move here
    # gui/ is NOT here — Swift lives separately
  gui-macos/       # Swift package / Xcode project
  docs/
    GUI_IMPLEMENTATION.md
```

The Swift app is a sibling directory (`gui-macos/`) rather than a Python subpackage because it has its own toolchain (Xcode, SwiftPM) and its own release artifact (`.app` bundle).

## Build order

These are prerequisites in the order they unblock each other. None of them require Swift work to begin.

1. **Restructure: `cli.py` → `cli/` subpackage; split `pyproject.toml` extras into `[cli]`, `[gui-support]`, `[export]`, `[dev]`.**
   Mechanical move. Lets the core be installed without Click for headless/agent contexts and makes the GUI-vs-CLI boundary explicit in the package layout.

2. **`events` table + writes from every mutation in `article_db.py`.**
   Load-bearing for the GUI's real-time feel. Self-contained Python work; ships value to the CLI/REPL too (activity log).

3. **`--json` output mode on CLI commands the GUI will call.**
   Pure additive change. Existing human output stays the default.

4. **Swift app skeleton: open DuckDB read-only, render articles table, file-watch + events tail.**
   First end-to-end vertical slice. No write path yet — read-only viewer that updates live as the agent works.

5. **Write path: Swift shells out to `scopus-for-dobby --json` for tag/collection/note edits.**
   Adds human editing on top of the read-only viewer.

6. **Polish: search bar wired to `core/search.py` via CLI, export dialog, keyboard nav, etc.**

Steps 1–3 are pure Python and can land independently of any GUI decision. If the Swift project never happens, none of those changes are wasted — the events table and `--json` mode both stand on their own.

## Non-goals

- Cross-platform GUI. macOS-only is a deliberate choice; revisit only if there is real demand.
- A long-running GUI daemon or server. The file + events table is the protocol.
- GUI-side write logic. If the GUI ever needs a mutation the CLI doesn't expose, add it to the CLI first.
