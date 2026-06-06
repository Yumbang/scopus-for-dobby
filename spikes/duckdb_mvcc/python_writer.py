"""Phase-0 spike writer — bursty add_entries against the spike DB.

Emulates a Claude Code REPL session: opens a long-lived RW connection and
fires synthetic articles at ~5/sec for the configured duration.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

import duckdb


def synthetic_entry(i: int) -> dict:
    return {
        "eid": f"SPIKE-{i:08d}",
        "scopus_id": str(i),
        "doi": f"10.0000/spike.{i}",
        "title": f"Spike paper {i} on transformer architectures",
        "first_author": "Doe, J.",
        "all_authors": json.dumps([{"auid": "A1", "name": "Doe, J."}]),
        "journal": "Spike Journal",
        "volume": "1",
        "issue": "1",
        "pages": "1-2",
        "cover_date": "2026-01-01",
        "cited_by": i % 100,
        "open_access": False,
        "abstract": f"Abstract {i} discussing attention mechanisms and benchmarks.",
        "keywords": "attention; transformer; benchmark",
        "issn": "0000-0000",
        "source_type": "j",
        "affiliations": json.dumps([]),
        "index_keywords": "[]",
        "subject_areas": "[]",
        "tags": "[]",
        "notes": "",
        "added_at": "2026-04-29 00:00:00",
        "updated_at": "2026-04-29 00:00:00",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--duration", type=float, default=30.0)
    p.add_argument("--rate", type=float, default=5.0, help="writes per second")
    p.add_argument("--idle-hold", type=float, default=0.0, help="hold idle write conn this long after writes")
    args = p.parse_args()

    conn = duckdb.connect(str(args.db), read_only=False)
    interval = 1.0 / args.rate
    deadline = time.monotonic() + args.duration
    i = 0
    errors = 0
    started = time.monotonic()
    while time.monotonic() < deadline:
        t0 = time.monotonic()
        try:
            entry = synthetic_entry(i)
            conn.execute("BEGIN")
            conn.execute(
                """INSERT OR REPLACE INTO articles
                   (eid, scopus_id, doi, title, first_author, all_authors, journal,
                    volume, issue, pages, cover_date, cited_by, open_access, abstract,
                    keywords, issn, source_type, affiliations, index_keywords,
                    subject_areas, tags, notes, added_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [entry[k] for k in (
                    "eid","scopus_id","doi","title","first_author","all_authors","journal",
                    "volume","issue","pages","cover_date","cited_by","open_access","abstract",
                    "keywords","issn","source_type","affiliations","index_keywords",
                    "subject_areas","tags","notes","added_at","updated_at",
                )],
            )
            conn.execute(
                "INSERT INTO events (kind, entity_type, entity_id, payload) VALUES (?,?,?,?)",
                ["article.added", "article", entry["eid"], json.dumps({"i": i})],
            )
            conn.execute("COMMIT")
            i += 1
        except Exception as e:
            errors += 1
            print(f"[writer] error: {e}", file=sys.stderr)
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
        sleep_for = interval - (time.monotonic() - t0)
        if sleep_for > 0:
            time.sleep(sleep_for)

    elapsed = time.monotonic() - started
    if args.idle_hold > 0:
        time.sleep(args.idle_hold)
    print(json.dumps({"writes": i, "errors": errors, "elapsed_s": elapsed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
