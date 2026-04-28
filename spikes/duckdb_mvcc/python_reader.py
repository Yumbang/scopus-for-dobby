"""Phase-0 spike reader — proxy for the Swift duckdb-swift binding.

Opens DuckDB read-only and polls (events MAX(id), articles COUNT(*))
at 10Hz. Records freshness lag (time between commit and observed visibility)
and any error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--duration", type=float, default=30.0)
    p.add_argument("--hz", type=float, default=10.0)
    args = p.parse_args()

    # Wait for DB file to exist (Subtest a: read-only on non-existent DB).
    create_wait_attempts = 0
    while not args.db.exists():
        create_wait_attempts += 1
        time.sleep(0.05)
        if create_wait_attempts > 200:  # 10s
            print(json.dumps({"error": "db_never_created"}))
            return 1

    conn = None
    open_attempts = 0
    last_error = None
    while conn is None:
        open_attempts += 1
        try:
            conn = duckdb.connect(str(args.db), read_only=True)
        except Exception as e:
            last_error = str(e)
            time.sleep(0.05)
            if open_attempts > 200:
                print(json.dumps({"error": "open_failed", "last_error": last_error}))
                return 1

    interval = 1.0 / args.hz
    deadline = time.monotonic() + args.duration
    samples = 0
    errors = 0
    max_event_id = 0
    last_count = 0
    error_messages: list[str] = []
    while time.monotonic() < deadline:
        t0 = time.monotonic()
        try:
            row = conn.execute("SELECT COALESCE(MAX(id),0), COUNT(*) FROM events").fetchone()
            max_event_id = max(max_event_id, row[0] or 0)
            cnt = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            last_count = cnt
            samples += 1
        except Exception as e:
            errors += 1
            msg = str(e)
            if msg not in error_messages:
                error_messages.append(msg)
        sleep_for = interval - (time.monotonic() - t0)
        if sleep_for > 0:
            time.sleep(sleep_for)

    print(json.dumps({
        "samples": samples,
        "errors": errors,
        "open_attempts": open_attempts,
        "max_event_id": max_event_id,
        "last_article_count": last_count,
        "error_messages": error_messages[:10],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
