# GUI Implementation Plan — `scopus-for-dobby`

> Source spec: `.omc/specs/deep-interview-gui-implementation.md`
> Status: **CONSENSUS-APPROVED**, then **PIVOTED TO PLAN C** after Phase-0 spike FAIL.
> Changes from Architect (8) and Critic (2) folded in below as Step 1.5 and amendments to Steps 0, 2, 3, 4, 5, 6, 7, plus ADR-0.

> **2026-04-29 second pivot — daemon-only protocol (Option C).**
> User-driven decision after reviewing the dual-mode (Plan C as originally written) cost: two code paths per mutation (in-proc + HTTP), a guard that surprises users, and an event log split between "daemon up" and "daemon down" worlds. Replaced with **lazy-spawn unified daemon**: CLI is a pure HTTP client; on first invocation it forks `scopus-for-dobby serve` if no live daemon exists and waits on `/health`; daemon self-shuts after idle timeout. Trade-off accepted: one cold-call pays ~300–500 ms uvicorn boot (paid once per agent session, amortized over many calls). See ADR-7 below. Step 4.6 reshaped accordingly: CLI guard is removed, every CLI subcommand routes through a `cli/_client.py` facade matching the `core.article_db` surface.
>
> **2026-04-29 architecture pivot — see `spikes/duckdb_mvcc/REPORT.md`.**
> Phase-0 spike confirmed DuckDB 1.5.0 enforces an exclusive file lock per process. ADR-1's "Swift opens DuckDB read-only while CLI/REPL holds RW" is **not viable**. Adopted **Plan C** (HTTP daemon `scopus-for-dobby serve`) as the replacement architecture. The daemon owns the only DuckDB connection; CLI and (future) Swift GUI both attach via 127.0.0.1.
>
> **Status of steps under Plan C:**
> - Step 0 (spike): COMPLETE → FAIL → pivot.
> - Step 1, 1.5, 2, 3, 4, 8: SHIPPED. Architecture-independent; no rework.
> - **NEW Step 4.5 (Plan C daemon):** SHIPPED. `scopus_for_dobby/server/` + `scopus-for-dobby serve` CLI command + 6 endpoint tests passing.
> - **NEW Step 4.6 (CLI client-side dispatch):** PENDING. CLI auto-detects daemon via PID file (`~/.scopus-for-dobby/daemon.{pid,port}`) and proxies mutations through HTTP when alive; falls back to direct DuckDB when daemon is down.
> - Step 5 (Swift skeleton): PENDING. Now bound to HTTP endpoints + SSE event stream instead of `duckdb-swift`.
> - Step 6 (Swift write path): PENDING. POSTs against the daemon (no subprocess hop).
> - Step 7 (Swift live FTS): PENDING. `GET /search/fts?query=...` — already implemented daemon-side.
>
> Daemon endpoints (live): `/health`, `/stats`, `/articles[/{eid}]`, `/articles/tag|untag`, `/articles/{eid}/note`, `/collections[/{name}/articles]`, `/collections/merge|rename`, `/authors[/{auid}/note]`, `/search/fts`, `/search/like`, `/fts/rebuild`, `/events?since=`, `/events/stream` (SSE).

## RALPLAN-DR Summary

### Principles (non-negotiable)
1. **`core/` stays UI-free.** No Click, no SwiftUI assumptions, no subprocess shelling out from `core/`. Every business rule lives here, callable from CLI and tests alike.
2. **GUI holds zero business logic.** Swift reads DuckDB read-only and shells out to `scopus-for-dobby ... --json` for every mutation. No SQL writes from Swift.
3. **Schema and Swift structs are co-versioned.** Any DDL change in `core/article_db.py` lands in the same PR as the Swift struct update; the schema-fingerprint test is the tripwire.
4. **No subprocess in the keystroke path.** Live filter, sort, paging, tail-of-events all go through the Swift DuckDB binding. CLI is for Scopus API calls and bulk imports only.
5. **Events are emitted in the same transaction as the mutation.** No "fire and forget" event log; an event row that exists implies the mutation committed.
6. **Phase-0 spike gates everything Swift.** No Xcode work begins until DuckDB cross-process MVCC is empirically validated against the actual `duckdb` Python build and `duckdb-swift` binding.

### Decision Drivers (top 3)
1. **DuckDB cross-process MVCC is unverified** — direct Swift reads vs Python writers under bursty agent load. Failure here cascades into a snapshot-file fallback that reshapes the entire sync model.
2. **Single-user, iterative dogfood.** No multi-user concurrency, no MAS, no deployment. Optimize for "platform the user can extend" over polish.
3. **Scale headroom without premature optimization.** Design for 10k–50k articles with DB-paging + FTS; explicitly defer virtualized rendering and 100k+ tuning.

### Viable Options (riskiest decision points)

**Decision A — Cross-process read path:**
- *(a) Direct DuckDB read-only connection from Swift* — pros: real-time, no copy, single source of truth; cons: depends on DuckDB MVCC semantics holding across processes for the official `duckdb-swift` build; risk of stale reads, lock contention, or file-format skew if Python `duckdb` and Swift `duckdb-swift` versions drift.
- *(b) Snapshot-file fallback (`articles-snapshot.duckdb`)* — pros: total isolation, no concurrency unknowns; cons: stale by design, requires CLI snapshot job, doubles disk usage, and breaks the "events table is the entire IPC" goal.
- **Choice: (a), gated by Phase-0 spike.** (b) stays as documented fallback with a clear trigger condition (any corruption, deadlock, or "database is locked" failure under the spike workload).

**Decision B — Local search backend:**
- *(a) DuckDB FTS extension (`fts` via `INSTALL fts; LOAD fts;`)* — pros: official, BM25 scoring, integrates with main table via PRAGMA; cons: extension must be available in `duckdb-swift`'s shipped binary; index rebuilds are coarse-grained.
- *(b) Trigram-style `LIKE '%q%'` over a normalized text column* — pros: zero extension dependency, works today; cons: O(n) scan, won't hold at 50k.
- *(c) Hand-rolled token table (`tokens(eid, token)` + GIN-style index)* — pros: full control; cons: reinvents FTS, higher maintenance.
- **Choice: (a) primary, (b) as fallback if `duckdb-swift` lacks the FTS extension.** Validate extension availability as part of Phase-0 spike. (c) rejected — too much maintenance for a personal tool.

---

## ADRs

### ADR-1: Split read/write architecture (direct reads + CLI writes)
- **Decision:** Swift opens `~/.scopus-for-dobby/articles.duckdb` read-only; all mutations route through `scopus-for-dobby <cmd> --json` subprocess.
- **Drivers:** Business logic must live in `core/` exactly once; live filter/sort/paging cannot pay subprocess latency; agent (Claude Code) and GUI must coexist as concurrent writers/readers without a daemon.
- **Alternatives:** Embed Python in Swift (rejected — ships a Python runtime, defeats native-app simplicity); long-running daemon with Unix socket (rejected — extra moving part for a single-user tool); pure-CLI-shell GUI (rejected — keystroke latency).
- **Why:** The DuckDB file plus `events` table is already a proven IPC primitive; one writer-path keeps invariants centralized.
- **Consequences:** GUI is read-only when CLI is broken/uninstalled (acceptable — same machine). Every new mutation needs a CLI surface. Schema drift between Python and Swift becomes a real risk → mitigated by ADR-5.
- **Follow-ups:** Confirm `duckdb-swift` honors read-only opens cleanly while another process holds RW.

### ADR-2: `events` table as IPC and audit log
- **Decision:** New `events` table written transactionally with every mutation. GUI tails it on file-watch wakeups via `WHERE id > last_seen_id`.
- **Drivers:** Need real-time UI without polling the full table; single-user means no need for a broker.
- **Alternatives:** Trigger-based notify (DuckDB has no LISTEN/NOTIFY); polling full table diff (wasteful at 10k+); OS-level distributed notification (overkill).
- **Why:** Same-transaction insert guarantees event ↔ mutation atomicity; auto-incrementing `id` gives a monotonic cursor.
- **Consequences:** Every mutation function gains 1–2 lines for event emission. A new mutation with no event silently breaks GUI sync — covered by unit test in §AC.
- **Follow-ups:** Decide retention policy (probably "never prune in v1"); revisit if table grows past ~1M rows.

### ADR-3: DuckDB FTS for local search
- **Decision:** Use DuckDB's `fts` extension on `articles(title, abstract, keywords)`; expose `search_articles_fts(query, limit)` in core.
- **Drivers:** No subprocess per keystroke; ranked retrieval beats `LIKE`; corpus headroom to 50k.
- **Alternatives:** See Viable Options B.
- **Why:** Official extension, ranked output, refreshable.
- **Consequences:** FTS index must be rebuilt on `add_entries` (incremental updates aren't supported by `fts_main_*` PRAGMA — full rebuild on each ingest is the documented path). Adds latency to bulk ingests; acceptable for bursty writes.
- **Follow-ups:** Phase-0 spike must confirm `duckdb-swift` ships the `fts` extension or can install it at runtime; otherwise fall back to `LIKE` for v1.

### ADR-4: `cli/` subpackage restructure
- **Decision:** Move `scopus_for_dobby/cli.py` → `scopus_for_dobby/cli/__init__.py` with command-group modules (`auth.py`, `search.py`, `db.py`, `collection.py`, `author.py`, `export.py`, `repl.py`).
- **Drivers:** Current `cli.py` is large; adding `--json` to ~12 subcommands and a `collection merge` subcommand pushes it past comfortable maintenance.
- **Alternatives:** Keep monolithic file (rejected).
- **Why:** Clean separation per command group; entry point `scopus_for_dobby.cli:main` stays valid.
- **Consequences:** Imports change in `pyproject.toml` script and any tests; REPL must still re-enter the click group.
- **Follow-ups:** None — public CLI surface unchanged.

### ADR-5: Hand-mirrored Swift structs + schema-fingerprint test
- **Decision:** `Article.swift`, `Collection.swift`, `Event.swift` mirror the DuckDB schema. A pytest reads `_get_conn()`'s `CREATE TABLE` strings, hashes them, and compares to a checked-in fingerprint file.
- **Drivers:** Drift between Python schema and Swift decoders is silent corruption.
- **Alternatives:** Codegen Swift from a JSON schema (overkill); runtime introspection at GUI launch (deferred error, not pre-flight).
- **Why:** Cheap, deterministic, fits the "one schema-fingerprint test" budget.
- **Consequences:** Schema change = update Swift struct + bump fingerprint in same commit.
- **Follow-ups:** None.

### ADR-6: `merge_collections` semantics
- **Decision:** `merge_collections(src, dst)` performs `INSERT OR IGNORE INTO collection_articles SELECT dst, eid FROM collection_articles WHERE collection_name = src`, then deletes `src`'s rows and the `src` collection itself, all in one transaction; emits a `collection.merged` event.
- **Drivers:** GUI needs an atomic "merge" affordance; partial failures must not orphan rows.
- **Alternatives:** Swift-side multi-step orchestration (rejected — not atomic across subprocess boundaries).
- **Why:** Set-union with no duplicates matches user intent; single transaction ensures no half-merged state.
- **Consequences:** If `dst` doesn't exist, auto-create. If `src == dst`, no-op with a warning.
- **Follow-ups:** None.

### ADR-7: Lazy-spawn unified daemon (supersedes ADR-1's split read/write)
- **Decision:** The HTTP daemon is the only process that ever opens DuckDB. Every CLI subcommand (except `serve` itself) is a thin HTTP client. On invocation, the CLI checks `~/.scopus-for-dobby/daemon.{pid,port}`; if no live daemon, it forks `scopus-for-dobby serve --background` as a detached process and waits up to ~2 s on `GET /health` before issuing its real request. Daemon self-shuts after a configurable idle timeout (default 600 s).
- **Drivers:**
  1. DuckDB 1.5.0 holds an exclusive file lock per process (Phase-0 spike); only single-owner architectures are viable.
  2. Two code paths per mutation (in-proc vs HTTP) doubles maintenance and splits the events-table audit log.
  3. The current daemon-guard refuses CLI commands when the daemon is up, which is a footgun for users who don't read the error.
  4. GUI work is upcoming and must call HTTP anyway — having the CLI exercise the same protocol first hardens it.
- **Alternatives:**
  - *Always-on daemon (launchd/login item):* uniform but adds OS-specific install friction and a permanently-running process for an idle machine.
  - *Dual-mode + guard (original Plan C):* what we had until 2026-04-29; rejected for the reasons above.
- **Why:** One protocol, one code path, complete event log, no install ritual, no guard. The cold-start cost (~300–500 ms uvicorn boot) amortizes over an agent session because most CLI use is bursty.
- **Consequences:**
  - Every CLI subcommand routes through `cli/_client.py`, a facade that mirrors the public `core.article_db` surface but issues HTTP requests.
  - `cli/_daemon.py` owns lazy-spawn: PID-file probe, lockfile to defeat fork races, double-fork to detach, `/health` poll with timeout.
  - Server gains an idle-shutdown timer (resets on every request).
  - `serve` gains `--background` for the spawn path (runs without a foreground TTY, redirects logs to `~/.scopus-for-dobby/daemon.log`).
  - The `repl` subcommand no longer holds a DuckDB connection; every interactive op is an HTTP call. Latency is fine because the user types between calls.
  - The daemon-guard tests are replaced by lazy-spawn tests.
  - Failure mode: if `serve --background` crashes during boot, the CLI surfaces the daemon log path so the user can diagnose.
- **Follow-ups:** Decide idle-shutdown default (600 s placeholder). Decide whether `scopus-for-dobby serve` (foreground, explicit) should be merged with `serve --background` or stay distinct. Consider a `scopus-for-dobby daemon stop` convenience command.

---

## Implementation Plan

### Step 0 — Phase-0 Spike: DuckDB cross-process MVCC validation
- **Files:** `spikes/duckdb_mvcc/python_writer.py`, `spikes/duckdb_mvcc/swift_reader/` (throwaway Xcode project), `spikes/duckdb_mvcc/REPORT.md`.
- **What:** Python loop calling `add_entries` on synthetic entries at ~5/sec for 60s; Swift process holding read-only connection running `SELECT COUNT(*)` and `SELECT MAX(id) FROM events` at 10Hz. Also test: long-held Python REPL write connection (open `_get_conn()` and idle 5 min) while Swift reads. Record: corruption, deadlocks, error messages, snapshot freshness lag, FTS extension availability.
- **Testable outcome:** REPORT.md with PASS/FAIL on each subtest. PASS = no errors, reads see committed state within ≤1s of commit, FTS extension loads in `duckdb-swift`.
- **Dependencies:** None.
- **Gate:** If FAIL → switch to snapshot-file fallback. If PASS → continue.

### Step 1 — Restructure `cli.py` → `cli/` and split `pyproject.toml` extras
- **Files:** `scopus_for_dobby/cli/__init__.py`, `cli/auth.py`, `cli/search.py`, `cli/db.py`, `cli/collection.py`, `cli/author.py`, `cli/export.py`, `cli/_output.py`, `pyproject.toml`.
- **What:** Each module exposes a `register(cli)` function. `pyproject.toml` extras: `[cli]`, `[gui-support]`, `[export]`, `[dev]`. Entry point `scopus-for-dobby = "scopus_for_dobby.cli:main"` still resolves.
- **Testable outcome:** `scopus-for-dobby --help` lists every existing subcommand; `pytest` passes; REPL still works.
- **Dependencies:** None.

### Step 2 — `events` table + per-mutation emission + `merge_collections` + `rename_collection`
- **Files:** `scopus_for_dobby/core/article_db.py`, `tests/test_events.py`, `tests/test_merge_collections.py`, `tests/test_rename_collection.py`.
- **What:**
  - DDL in `_get_conn()`:
    ```
    CREATE SEQUENCE IF NOT EXISTS events_id_seq;
    CREATE TABLE IF NOT EXISTS events (
        id BIGINT PRIMARY KEY DEFAULT nextval('events_id_seq'),
        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        kind VARCHAR,
        entity_type VARCHAR,
        entity_id VARCHAR,
        payload JSON
    );
    ```
  - Helper `_emit_event(conn, kind, entity_type, entity_id, payload)` called inside the same transaction as each mutation.
  - Add `merge_collections(src, dst) -> {"merged_from": src, "merged_to": dst, "moved": n}`.
  - Add `rename_collection(old, new) -> dict` (preserves `created_at`).
  - Mutations to instrument: `add_entries`, `remove_entries`, `tag_articles`/`untag_articles`, `set_note`, `create_collection`/`delete_collection`/`merge_collections`/`rename_collection`, `add_to_collection`/`remove_from_collection`, `set_author_note`, `fetch_author_profile`.
- **Testable outcome:** Every mutation function emits ≥1 event row. `merge_collections` test: union semantics, src deleted, idempotent on overlap. `rename_collection` test: created_at preserved, articles still attached.
- **Dependencies:** Step 1.

### Step 3 — DuckDB FTS index + `search_articles_fts`
- **Files:** `scopus_for_dobby/core/article_db.py`, `tests/test_fts.py`.
- **What:**
  - In `_get_conn()`: `INSTALL fts; LOAD fts;` (idempotent).
  - `PRAGMA create_fts_index('articles', 'eid', 'title', 'abstract', 'keywords', overwrite=1)` on first creation; refresh on `add_entries` completion.
  - New `search_articles_fts(query, limit=50) -> {"articles": [...], "total": n}` using `fts_main_articles.match_bm25`.
  - Optional `defer_fts_rebuild=True` kwarg + `rebuild_fts()` for bulk imports.
- **Testable outcome:** Insert articles with distinct titles; `search_articles_fts("transformer")` returns expected ranked subset.
- **Dependencies:** Step 2.

### Step 4 — `--json` output mode + `collection merge`/`collection rename` subcommands
- **Files:** `scopus_for_dobby/cli/_output.py`, `cli/db.py`, `cli/collection.py`, `cli/search.py`, `cli/__init__.py`, `tests/test_cli_json.py`.
- **What:**
  - Each command emits a single JSON object/array on stdout when `--json` is set. Progress/skin output to stderr only. Errors → `{"error": str, "type": "..."}`. Add `collection merge SRC DST` and `collection rename OLD NEW`.
- **Testable outcome:** `scopus-for-dobby --json db list | jq .` works for each command; default human output unchanged when flag absent.
- **Dependencies:** Step 1, Step 2.

### Step 5 — Swift skeleton: read-only viewer with file-watch + events tail
- **Files:** `gui-macos/scopus-for-dobby.xcodeproj/`, `gui-macos/Sources/App.swift`, `Sources/Models/{Article,Collection,Event}.swift`, `Sources/DB/{DuckDBClient,EventTailer,FileWatcher}.swift`, `Sources/Views/{ContentView,CollectionsSidebar,ArticleListView,ArticleDetailView}.swift`.
- **What:** SwiftPM dep on `duckdb-swift`. macOS 14 deployment target. `DuckDBClient.openReadOnly` opens the DB file. `FileWatcher` via `DispatchSource.makeFileSystemObjectSource(.write)` debounced ~150ms. `EventTailer.fetchSince(lastSeenId)` queries `events`. Three-pane `NavigationSplitView`. Article list paged via LIMIT/OFFSET, sortable on title/cited/added/date. **No mutations in this step.**
- **Testable outcome:** Launch app, view collections, select one, see articles. Run `scopus-for-dobby db tag --eid X foo` from terminal; observe row update in GUI within ~1s.
- **Dependencies:** Step 0 PASS, Step 2.

### Step 6 — Swift write path via subprocess + multi-select editing
- **Files:** `gui-macos/Sources/CLI/CLIRunner.swift`, `Sources/Commands/{Tag,Collection,Note}Command.swift`, `Sources/Views/Editing/{TagEditor,NoteEditor,CollectionMergeSheet}.swift`.
- **What:** `CLIRunner.run(args:)` spawns `scopus-for-dobby --json …`, parses JSON, surfaces stderr on error. Resolves binary via `which scopus-for-dobby` at startup. SwiftUI `List` with `selection: Set<EID>` for Cmd/Shift selection. Operations wired: tag apply/remove (mass), add/remove from collection (mass), note edit, create collection, merge collections, rename collection. Post-call: signal `EventTailer` for immediate refresh.
- **Testable outcome:** Multi-select 3 articles, apply tag — event log shows `article.tagged`, list refreshes, tag visible.
- **Dependencies:** Step 4, Step 5.

### Step 7 — Swift live filter via direct FTS
- **Files:** `gui-macos/Sources/DB/SearchClient.swift`, `Sources/Views/SearchField.swift`, integration in `ArticleListView.swift`.
- **What:** `SearchClient.fts(query, limit)` runs BM25 query against read-only connection. Search field debounced ~150ms. Result EIDs intersected with current collection filter. Fallback (if Step 0 found FTS unavailable): `LIKE LOWER(title || ' ' || abstract)` query.
- **Testable outcome:** Type "transformer"; list narrows in <200ms with no subprocess invocation.
- **Dependencies:** Step 3, Step 5.

### Step 8 — Schema fingerprint CI test
- **Files:** `tests/test_schema_fingerprint.py`, `tests/fixtures/schema_fingerprint.txt`, `gui-macos/Sources/Models/SchemaVersion.swift`.
- **What:** Test connects to a fresh DB, reads `CREATE TABLE` strings, normalizes whitespace, hashes, compares to fingerprint file. Failure message points to where Swift structs live and how to refresh the fingerprint with `pytest --update`.
- **Testable outcome:** Adding a column to `articles` without updating the fingerprint fails with helpful message.
- **Dependencies:** Step 2.

---

## Acceptance Criteria Mapping

| Criterion (from spec) | Delivered by Step |
|---|---|
| `events` table with specified schema | Step 2 |
| Every mutating function emits an event in same txn | Step 2 |
| `merge_collections(src, dst)` set-union semantics | Step 2 |
| `rename_collection` (closing the AC gap) | Step 2 |
| FTS index + `search_articles_fts` | Step 3 |
| Unit tests: events on every mutation, merge correctness, FTS hits | Steps 2 & 3 |
| `--json` on relevant commands | Step 4 |
| Default human output preserved | Step 4 |
| App opens DuckDB read-only, three-pane layout | Step 5 |
| Article list sort + filter; live filter via FTS | Steps 5 + 7 |
| Multi-select Cmd/Shift conventions | Step 6 |
| Article edits: collection add/remove (single+bulk), notes, mass tag | Step 6 |
| Collection edits: create, rename, merge | Step 6 |
| All mutations via subprocess; no Swift write connection | Step 6 |
| File-watch + events tail with row animations | Steps 5 + 6 |
| Hand-mirrored Swift structs + fingerprint test | Steps 5 + 8 |
| Phase-0 MVCC spike with fallback decision | Step 0 |

---

## Risks & Mitigations

1. **Phase-0 spike fails / FTS extension unavailable in `duckdb-swift`.** Snapshot-file read fallback; `LIKE` search fallback. Decision recorded in spike REPORT.md before any Step 5+ work.
2. **FTS index rebuild on every `add_entries` slows bulk imports.** `defer_fts_rebuild=True` kwarg + `rebuild_fts()` core fn called once at end of bulk operations.
3. **Schema drift between Python and Swift slips past developer.** Step 8 fingerprint test runs in `pytest`; failure message is actionable.
4. **Long-held REPL write connection blocks Swift readers.** Phase-0 spike explicitly tests this. If problematic, refactor `_get_conn()` to a context manager and ensure REPL doesn't hold idle connections.
5. **Subprocess latency for bulk multi-select edits (e.g., tag 200 articles).** CLI accepts list-form `--eid` flags; one subprocess call handles N EIDs. Soft cap ~1000 EIDs per call (argv length); chunk above that.

---

## Out of Scope (Reaffirmed)
- Cross-platform GUI (Linux/Windows).
- Long-running GUI daemon or DB server (retained as **Plan C** pivot — see Risks).
- Hard-deleting articles from the GUI.
- PDF attachments, BibTeX/RIS import, advanced query builder, citation export dialogs.
- Distribution / signing / notarization / sandbox.
- Polished UX — v1 is a firm dogfood platform.
- Tag rename / tag merge.
- Author-level views and editing in the GUI.
- Multi-library support.

---

# Consensus Amendments (Architect + Critic)

The base plan above stands. The following amendments are mandatory and supersede the corresponding sections.

## New: Step 1.5 — Refactor `_get_conn()` lifecycle (BLOCKS Step 0)
- **Files:** `scopus_for_dobby/core/article_db.py`, `tests/test_conn_lifecycle.py`.
- **What:**
  - Split into `_open_conn(read_only=False)` (cheap; no DDL) and `_ensure_schema(conn)` (DDL; runs once per process behind a module-level guard, e.g., a `_schema_initialized: bool` flag).
  - Public functions reuse a process-local cached connection rather than opening/closing on every call.
  - Add `_txn(conn)` context manager that wraps `BEGIN ... COMMIT` (rollback on exception) so every mutation + its event emission is atomic.
  - Update REPL to ensure no idle write connection is held between commands.
- **Testable outcome:** Connect storm test (50 connects/sec) passes without "database is locked"; DDL runs exactly once per process; rollback on raised exception leaves no orphaned mutation OR event row.
- **Why mandatory:** Step 0's spike must test the *real* connection pattern. Without this refactor, the spike validates a pattern the code doesn't use.

## Amend Step 0 — Spike subtests expanded
Add to subtests:
- (a) Swift opens read-only on a non-existent DB file → fails cleanly, retried after Python creates it.
- (b) Python writer opens/closes ≥20×/sec while Swift holds read-only — measure error rate; gate criterion: <0.1% errors.
- (c) DDL-on-concurrent-connect: Swift read-only opens *before* Python creates schema → confirm `duckdb-swift` returns a clear error (or empty result) rather than corrupting state.
- (d) Long-held Python REPL idle write connection (5 min) while Swift reads — confirm reads return current data.
- (e) APFS file-watch granularity: confirm `DispatchSource(.write)` fires reliably on DuckDB WAL flushes (not just metadata).
- (f) FTS extension: `INSTALL fts; LOAD fts;` from `duckdb-swift`; record version + binary path in REPORT.md.
- (g) Co-pin DuckDB versions: record `duckdb` Python version and `duckdb-swift` version; confirm file-format compatibility.
- (h) Sequence visibility: write `INSERT INTO events ...` from Python; read `MAX(id)` from Swift within 1s.
- (i) FTS-on-empty-corpus: `PRAGMA create_fts_index` against zero-row table — does it throw?
- **Gate:** All subtests PASS, error rate <0.1% in (b), freshness ≤1s, FTS available. Otherwise → Plan B (snapshot file) or Plan C (HTTP daemon).

## Amend Step 2 — Explicit transaction boundaries
- Every mutation function body wrapped in `with _txn(conn):` (from Step 1.5). `_emit_event` called inside the same `with` block.
- Add test: simulate raise between mutation and `_emit_event` → assert no orphaned mutation row AND no orphaned event row.
- Add `rename_collection(old: str, new: str) -> dict` — preserves `created_at`, cascades to `collection_articles.collection_name`, emits `collection.renamed`.

## Amend Step 3 — Pin FTS rebuild semantics + add CLI batch primitive
- `defer_fts_rebuild=True` is **single-call only** (not a persistent sentinel). Caller must call `rebuild_fts()` explicitly.
- Null-guard `PRAGMA create_fts_index` against zero-row table.
- **New deliverable in Step 4:** CLI batch primitive `scopus-for-dobby search QUERY --add-to COLL --pages N` that owns the whole multi-page Scopus ingest in a single process and rebuilds FTS exactly once at the end.

## Amend Step 4 — Enumerate `--json` surface + stdin EID input
- `--json` enumerated explicitly: `search`, `db add`, `db list`, `db tag`, `db untag`, `db note`, `db info`, `collection list/create/delete/rename/merge/add/remove`, `tag list`, `author list/get/note`, `export`, `abstract`. (Matches spec verbatim.)
- Every command accepting `--eid` ALSO accepts `--eids-from-stdin` (newline-delimited) and `--eids-from-file PATH`. Drop the argv-chunking risk; large lists pipe via stdin.

## Amend Step 5 — `EventTailer` replay-window cap + cold-start
- On first launch (no persisted `last_seen_id`): `last_seen_id = MAX(id) FROM events`. Do a full collection/article query. No row-insertion animations.
- On subsequent wake: if `MAX(id) - last_seen_id > 200`, do a cold refresh + show a single toast "N changes since last open." Do NOT animate per-row.
- Otherwise, fetch deltas via `WHERE id > last_seen_id` and apply with row-insertion animations.

## Amend Step 6 — `CLIRunner` binary discovery
- Resolve `scopus-for-dobby` binary path at startup with this precedence:
  1. `SCOPUS_FOR_DOBBY_BIN` env var (explicit override).
  2. `~/.local/bin/scopus-for-dobby` (uv tool install default).
  3. `which scopus-for-dobby` via a login shell (`/bin/zsh -l -c 'which scopus-for-dobby'`) to capture user PATH when launched from Finder.
  4. User-visible error with remediation if none resolve.
- Document this in `gui-macos/README.md` so the user knows the override exists.

## Amend Step 7 — No search logic in Swift
- Remove the in-Swift `LIKE` fallback. Instead:
  - `core/article_db.py` exposes `search_articles_like(query, limit) -> list[dict]` symmetric with `search_articles_fts`.
  - At GUI startup, probe FTS availability once; bind `SearchClient` to the available core function (read-only SQL through duckdb-swift either way).
- Preserves Principle 2 (no business logic in Swift).

## Amend Risks — Add Plan C
- **Plan C — Embedded HTTP daemon (`scopus-for-dobby serve`).** Trigger conditions: Step 0 spike fails AND Plan B (snapshot file) is unacceptable for real-time fidelity. A FastAPI process bound to `127.0.0.1`, owning the only DuckDB connection, exposing `GET /articles`, `POST /tag`, `GET /events?since=`, `GET /events/stream` (SSE). CLI subcommands attach to the daemon when running. Strictly larger scope than Plan B; do not adopt unless Plan B is also blocked.

## Amend Hidden Assumptions (now tracked)
1. Co-pin `duckdb` (Python, in `pyproject.toml`) and `duckdb-swift` (SwiftPM, in `Package.swift`). Bump together. Record both versions in spike REPORT.md.
2. Finder-launched `.app` PATH is fixed by Step 6's binary discovery override.
3. Sandbox is explicitly disabled in v1 — `~/.scopus-for-dobby/` resolves identically from Swift `FileManager.default.homeDirectoryForCurrentUser` and Python `Path.home()`. Locked in via ADR-1.
4. GUI-vs-REPL writer concurrency: if both try to write, DuckDB serializes via file lock; user-visible behavior on collision is "second writer waits." Documented but not specially handled in v1 (single-user, low collision likelihood).

---

## ADR-0: GUI Implementation — Consensus Decision (Canonical)

**Decision**
Build a native macOS SwiftUI GUI on top of `scopus-for-dobby`'s existing Python core using a split read/write architecture: Swift opens DuckDB read-only via `duckdb-swift`; all mutations route through `scopus-for-dobby <cmd> --json` subprocesses. A new `events` table provides cross-process IPC; DuckDB FTS provides keystroke-latency local search.

**Drivers**
1. Business logic must live in `core/` exactly once (callable from CLI, GUI, tests).
2. Live filter / sort / paging cannot pay subprocess latency per keystroke.
3. Claude Code agent sessions and the GUI must coexist as concurrent writer/reader without a long-running daemon.
4. Single-user, no distribution — optimize for "firm dogfood platform," not polish.
5. Scale headroom to 10k–50k articles; defer 100k+ tuning.

**Alternatives Considered**
- *Embed Python runtime in Swift app* — rejected; defeats native simplicity, ships a runtime.
- *Long-running daemon over Unix socket* — rejected for v1; extra moving part. Retained as **Plan C** (`scopus-for-dobby serve` HTTP daemon) if Phase-0 spike fails AND snapshot fallback is unacceptable.
- *Snapshot-file fallback (`articles-snapshot.duckdb`)* — retained as **Plan B** documented fallback, gated on Phase-0 outcome.
- *Pure CLI-shell GUI (subprocess per query)* — rejected; keystroke latency.
- *Trigram `LIKE` search over normalized column* — retained as Step 7 fallback if `duckdb-swift` lacks the FTS extension; exposed via `core.search_articles_like()` so Swift holds no search logic (Principle 2).
- *Hand-rolled token table* — rejected; reinvents FTS for a personal tool.
- *Codegen Swift from JSON schema* — rejected; overkill vs. fingerprint-test tripwire.

**Why Chosen**
The DuckDB file plus `events` table is already a proven IPC primitive within the project, and the read/write split keeps every invariant in one place (`core/`). Direct reads are the only option that meets the "no subprocess per keystroke" constraint without standing up a daemon. Phase-0 spike de-risks the one architectural unknown (cross-process MVCC) before any Swift investment, with two fallback plans (snapshot file, embedded HTTP daemon) of increasing weight.

**Consequences**
- GUI is read-only when CLI is broken/uninstalled. Acceptable on a single machine.
- Every new mutation requires a CLI surface (`--json`) — enforced by Principle 2.
- Schema drift between Python DDL and Swift structs becomes a real risk → mitigated by ADR-5's fingerprint test.
- FTS index rebuilds on every `add_entries` add latency to bulk ingests → mitigated by `defer_fts_rebuild` kwarg + a CLI batch primitive (`scopus-for-dobby search ... --add-to COLL --pages N`) that owns the whole ingest and rebuilds FTS once.
- `_get_conn()` must be refactored (Step 1.5) to separate schema creation from connection acquisition and expose a `_txn()` context manager so per-mutation transactions are explicit.
- `duckdb` Python and `duckdb-swift` versions must be co-pinned to prevent file-format skew.

**Follow-ups** (all folded into amendments above)
1. Step 0 spike subtests expanded with concrete error-rate gates.
2. Step 1.5 added: refactor `_get_conn()` lifecycle, add `_txn()` context manager.
3. Step 2: explicit `with _txn(conn):` wrap; kill-between-mutation-and-event test.
4. Step 3: pin `defer_fts_rebuild` semantics; null-guard zero-row FTS create.
5. Step 4: enumerate `--json` command list verbatim; add `--eids-from-stdin`/`-from-file`; add CLI batch primitive `search ... --add-to COLL --pages N`.
6. Step 5: `EventTailer` replay-window cap (200 events) with cold-refresh-with-toast; cold-start `last_seen_id = MAX(id)`.
7. Step 6: `CLIRunner` binary discovery (env override → `~/.local/bin` → login-shell `which`).
8. Step 7: in-Swift `LIKE` fallback removed; `core/` exposes `search_articles_like()`.
9. Risks: Plan C (HTTP daemon) documented as second-tier pivot.
10. Co-pin `duckdb` (Python) and `duckdb-swift` (SwiftPM) versions; record both in spike REPORT.md.
