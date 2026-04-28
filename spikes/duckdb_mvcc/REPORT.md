# Phase-0 Spike Report — DuckDB Cross-Process MVCC

**Date:** 2026-04-29
**DuckDB (Python):** 1.5.0
**Result:** ❌ **FAIL** — pivot to Plan B or Plan C required.

## Subtests

| ID | Subtest | Result | Evidence |
|----|---------|--------|----------|
| (a) | Reader opens read-only on non-existent DB → retry until created | N/A — blocked by (b) | reader can't open even after creation |
| (b) | Open/close storm (50 RO connects/sec) while writer active | ❌ FAIL | 50/50 errors in 1.32s |
| (c) | DDL-on-concurrent-connect (reader before schema exists) | N/A — blocked by (b) | |
| (d) | Long-held writer + idle hold while reader polls | ❌ FAIL | reader could not open during 23s test |
| (e) | APFS file-watch reliability on WAL flushes | DEFERRED | requires Swift |
| (f) | FTS extension load in `duckdb-swift` | DEFERRED | Python-side ✅ (`fts_probe.py`: install/load/bm25 all OK) |
| (g) | Co-pin file-format compat between `duckdb` Python and `duckdb-swift` | DEFERRED | requires Swift |
| (h) | Sequence visibility (RO sees writer commits ≤1s) | ❌ FAIL | RO connection rejected outright |
| (i) | FTS create on zero-row table | ✅ PASS | `fts_probe.py` empty_corpus_create=ok |
| BM25 query | match_bm25 returns ranked rows | ✅ PASS | `[("E1", 1.36)]` for "transformer attention" |
| Writer | Sustained writes + event emission | ✅ PASS | 98 writes / 20s, 0 errors |
| Connect storm | 50 RO connects against active writer | ❌ FAIL | 50/50 IO Error |

## Root cause

DuckDB 1.5.0 enforces an exclusive OS file lock when any process holds the database open read/write. A second process attempting `duckdb.connect(path, read_only=True)` is rejected with:

> `IO Error: Could not set lock on file "...articles.duckdb": Conflicting lock is held in <writer-python> (PID …)`.
> See: https://duckdb.org/docs/stable/connect/concurrency

Per the official concurrency doc, DuckDB allows **either** one writer (no other processes) **or** multiple readers (no writer). It does **not** support a writer + concurrent readers in separate processes — which is exactly what ADR-1 assumed.

## Implication for the plan

ADR-1's "Swift opens DB read-only while CLI/REPL holds RW" is not achievable with DuckDB as a file-only DB. Step 5+ (Swift skeleton, write path, live FTS) cannot proceed on the original architecture.

The plan documents two fallbacks:

- **Plan B — Snapshot file (`articles-snapshot.duckdb`)**: CLI exports a read-only snapshot periodically (e.g., on every event commit, debounced); Swift opens the snapshot. Events tail still works against snapshot. Cost: doubles disk, snapshot lag (~1–5s typical), CLI must own snapshot job.
- **Plan C — Embedded HTTP daemon (`scopus-for-dobby serve`)**: Single FastAPI process owns the only DuckDB connection; CLI subcommands attach to daemon when running; GUI uses HTTP/SSE for queries and event tail. Cost: extra running process; daemon lifecycle (autostart/recovery); larger surface.

## Recommendation

**Adopt Plan C (HTTP daemon)** as the primary architecture rather than Plan B, for these reasons:

1. **Plan B's "snapshot" still requires the CLI to detect when to refresh.** With multiple agent sessions writing concurrently, the snapshot job is itself a writer that contends for the same lock — moving the problem one layer down.
2. **Plan B cannot satisfy "no subprocess per keystroke + live FTS" cleanly.** Swift would FTS-query the *snapshot*, which is stale. With Plan C, FTS runs against live data via HTTP.
3. **The events-as-IPC primitive survives Plan C** unchanged (`GET /events?since=` + SSE). Plan B keeps it but adds snapshot-staleness as a confound.
4. **Single-user, local-only.** Plan C's daemon is `127.0.0.1`-bound; complexity is bounded.
5. **The CLI gains a useful new mode (`scopus-for-dobby serve`).** Idle daemon = direct DuckDB calls; running daemon = CLI delegates to it. This also resolves the long-standing "REPL holds idle write conn" issue.

If Plan C is rejected, Plan B is still workable but the staleness/FTS-on-snapshot trade-off should be accepted upfront.

## Decision Required

Before continuing to Step 5, confirm:

- [ ] **Plan B** (snapshot file) — accept ~1–5s staleness; FTS runs on snapshot.
- [ ] **Plan C** (HTTP daemon) — adopt `scopus-for-dobby serve`; CLI/GUI both attach when running.
- [ ] **Hybrid** — Plan C primary; Plan B as offline fallback when daemon is down.

## Plan C overhead measurement

`bench_http_vs_inproc.py` (2000 articles, 100 iters per workload, FastAPI TestClient → real ASGI stack, DuckDB 1.5.0):

| Workload | In-proc median | HTTP median | Overhead | HTTP p95 |
|---|---|---|---|---|
| `list_articles(limit=50)` | 1.15 ms | 3.00 ms | +1.85 ms | 3.39 ms |
| `get_article(eid)` | 0.23 ms | 0.93 ms | +0.70 ms | 1.12 ms |
| `search_fts('attention transformer', 50)` | 39.20 ms | 44.24 ms | +5.04 ms | 51.36 ms |
| `events since=0 limit=200` | 0.31 ms | 2.81 ms | +2.51 ms | 3.25 ms |

All HTTP medians are well under the 100 ms perceptual threshold. FTS overhead is ~13 % (the work itself dominates); fixed-cost endpoints add ~1–3 ms. Acceptable for a single-user local app.

## What still works without re-decision

The Python/CLI-side work already shipped (Steps 1, 1.5, 2, 3, 4, 8) is **architecture-independent** and stays:

- `events` table + transactional emission ✅
- `merge_collections` / `rename_collection` ✅
- DuckDB FTS index + `search_articles_fts` ✅
- `--json` CLI surface ✅
- Schema fingerprint test ✅
- `_txn()` context manager + lifecycle refactor ✅

These are reusable under any of Plan A/B/C.
