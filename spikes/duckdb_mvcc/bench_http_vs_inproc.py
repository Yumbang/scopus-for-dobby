"""Benchmark in-process DuckDB vs HTTP daemon (Plan C overhead).

Runs identical workloads two ways:
  1. In-process: call core functions directly.
  2. HTTP: same calls via the FastAPI app (loopback through TestClient,
     which has the same overhead profile as 127.0.0.1 uvicorn for our
     payload sizes — no socket/serialize differences worth measuring).

Reports min/median/p95/max latency over N iterations for:
  - GET /articles?limit=50
  - GET /articles/{eid}
  - GET /search/fts?query=...
  - GET /events?since=0&limit=200

Run:
    uv run --extra dev --extra gui-support python spikes/duckdb_mvcc/bench_http_vs_inproc.py
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path


def _entry(i: int) -> dict:
    titles = [
        "Attention is all you need",
        "BERT pre-training of deep transformers",
        "ResNet for image recognition",
        "GAN generative adversarial networks",
        "Transformer architecture for sequence modeling",
    ]
    return {
        "eid": f"BENCH-{i:06d}",
        "title": f"{titles[i % len(titles)]} — paper {i}",
        "first_author": "Doe, J.",
        "all_authors": [{"auid": f"A{i % 100}", "name": "Doe, J."}],
        "abstract": f"Abstract {i} discussing attention mechanisms and benchmark results.",
        "keywords": "transformer; attention; benchmark",
        "journal": "Bench J.",
        "cited_by": i % 500,
    }


def percentile(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def time_it(fn, iters: int) -> dict:
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "min_ms": round(min(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "max_ms": round(max(samples), 3),
        "n": iters,
    }


def main() -> int:
    n_articles = 2000
    iters = 100

    tmp = Path(tempfile.mkdtemp(prefix="bench-"))
    db = tmp / "articles.duckdb"

    from scopus_for_dobby.core import article_db as adb

    adb.DB_PATH = db
    adb.close_cached_connections()

    print(f"[bench] seeding {n_articles} articles…", file=sys.stderr)
    batch = [_entry(i) for i in range(n_articles)]
    # Insert in chunks to keep memory sane and rebuild FTS once at the end.
    chunk = 1000
    for i in range(0, n_articles, chunk):
        adb.add_entries(batch[i : i + chunk], defer_fts_rebuild=True)
    adb.rebuild_fts()
    print("[bench] seeded.", file=sys.stderr)

    # ── In-process callers ───────────────────────────────────────────────────
    def inproc_list():
        adb.list_articles(limit=50)

    def inproc_get():
        adb.get_article("BENCH-000042")

    def inproc_fts():
        adb.search_articles_fts("attention transformer", limit=50)

    def inproc_events():
        conn = adb._get_conn()
        conn.execute(
            "SELECT id, ts, kind, entity_type, entity_id, payload "
            "FROM events ORDER BY id ASC LIMIT 200"
        ).fetchall()

    # ── HTTP callers (FastAPI TestClient → real ASGI stack) ──────────────────
    from fastapi.testclient import TestClient

    from scopus_for_dobby.server import build_app

    client = TestClient(build_app())

    def http_list():
        client.get("/articles?limit=50")

    def http_get():
        client.get("/articles/BENCH-000042")

    def http_fts():
        client.get("/search/fts?query=attention+transformer&limit=50")

    def http_events():
        client.get("/events?since=0&limit=200")

    workloads = [
        ("list_articles(limit=50)", inproc_list, http_list),
        ("get_article(eid)", inproc_get, http_get),
        ("search_fts('attention transformer', 50)", inproc_fts, http_fts),
        ("events since=0 limit=200", inproc_events, http_events),
    ]

    # Warm-up.
    for _, ip, h in workloads:
        for _ in range(10):
            ip()
            h()

    results = []
    for name, ip, h in workloads:
        r_ip = time_it(ip, iters)
        r_h = time_it(h, iters)
        results.append({"workload": name, "inproc": r_ip, "http": r_h,
                        "median_overhead_ms": round(r_h["median_ms"] - r_ip["median_ms"], 3)})

    print(json.dumps({
        "n_articles": n_articles,
        "iters_per_workload": iters,
        "duckdb_version": __import__("duckdb").__version__,
        "results": results,
    }, indent=2))

    client.close()
    adb.close_cached_connections()
    return 0


if __name__ == "__main__":
    sys.exit(main())
