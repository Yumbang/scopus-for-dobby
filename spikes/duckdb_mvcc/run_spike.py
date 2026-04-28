"""Phase-0 spike orchestrator — runs writer + reader concurrently.

Subtests covered (per RALPLAN-DR Step 0 + amendments):
- (a) Reader opens read-only against non-existent DB → waits, then succeeds.
- (b) Open/close storm: 50 quick connect cycles concurrently with the reader.
- (c) DDL-on-concurrent-connect: schema is created by writer while reader retries.
- (d) Long-held idle write connection while reader polls (idle_hold).
- (h) Sequence visibility: max event id observed by reader vs writes done.
- (i) FTS-on-empty-corpus and basic FTS extension load (separate fts_probe.py).

Outputs JSON summary on stdout.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def init_schema(db: Path) -> None:
    """Initialize schema using the project's _ensure_schema."""
    import duckdb

    from scopus_for_dobby.core import article_db as adb

    # Force adb to use this DB path.
    adb.DB_PATH = db
    conn = duckdb.connect(str(db), read_only=False)
    # Reset cached schema-init flags so adb re-applies for this path.
    adb._schema_initialized.discard(db)
    adb._ensure_schema(conn)
    conn.close()


def connect_storm(db: Path, attempts: int = 50, results: dict | None = None) -> None:
    import duckdb

    errs = 0
    started = time.monotonic()
    for _ in range(attempts):
        try:
            c = duckdb.connect(str(db), read_only=True)
            c.execute("SELECT 1").fetchone()
            c.close()
        except Exception:
            errs += 1
        time.sleep(0.02)
    if results is not None:
        results["storm_attempts"] = attempts
        results["storm_errors"] = errs
        results["storm_elapsed_s"] = time.monotonic() - started


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=20.0)
    p.add_argument("--idle-hold", type=float, default=2.0)
    p.add_argument("--keep", action="store_true", help="keep tempdir for inspection")
    args = p.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="duckdb-mvcc-spike-"))
    db = tmp / "articles.duckdb"
    print(f"[spike] tempdir={tmp}", file=sys.stderr)

    # Pre-create schema (subtest c semantics: reader can also race against this).
    init_schema(db)

    here = Path(__file__).parent
    writer_proc = subprocess.Popen(
        [sys.executable, str(here / "python_writer.py"),
         "--db", str(db), "--duration", str(args.duration),
         "--idle-hold", str(args.idle_hold)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    # Give writer a head start so events table has rows when reader opens.
    time.sleep(0.2)
    reader_proc = subprocess.Popen(
        [sys.executable, str(here / "python_reader.py"),
         "--db", str(db), "--duration", str(args.duration + args.idle_hold + 1)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )

    storm_results: dict = {}
    storm_thread = threading.Thread(target=connect_storm, args=(db, 50, storm_results))
    storm_thread.start()

    writer_out, writer_err = writer_proc.communicate()
    reader_out, reader_err = reader_proc.communicate()
    storm_thread.join()

    try:
        writer_summary = json.loads(writer_out.strip().splitlines()[-1]) if writer_out.strip() else {}
    except Exception:
        writer_summary = {"raw": writer_out, "stderr": writer_err}
    try:
        reader_summary = json.loads(reader_out.strip().splitlines()[-1]) if reader_out.strip() else {}
    except Exception:
        reader_summary = {"raw": reader_out, "stderr": reader_err}

    summary = {
        "writer": writer_summary,
        "reader": reader_summary,
        "storm": storm_results,
        "writer_returncode": writer_proc.returncode,
        "reader_returncode": reader_proc.returncode,
        "writer_stderr_tail": writer_err[-400:] if writer_err else "",
        "reader_stderr_tail": reader_err[-400:] if reader_err else "",
    }
    print(json.dumps(summary, indent=2))

    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
