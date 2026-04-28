"""Phase-0 spike: FTS extension probe.

Confirms `INSTALL fts; LOAD fts;` works with the pinned Python duckdb,
PRAGMA create_fts_index works on populated and zero-row tables, and
match_bm25 returns ranked rows.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import duckdb


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="duckdb-fts-probe-"))
    db = tmp / "fts.duckdb"
    out: dict = {"duckdb_version": duckdb.__version__}
    conn = duckdb.connect(str(db))
    try:
        conn.execute("INSTALL fts")
        conn.execute("LOAD fts")
        out["install_load"] = "ok"
    except Exception as e:
        out["install_load"] = f"FAIL: {e}"
        print(json.dumps(out, indent=2))
        return 1

    conn.execute("""
        CREATE TABLE articles (
            eid VARCHAR PRIMARY KEY,
            title VARCHAR,
            abstract VARCHAR,
            keywords VARCHAR
        )
    """)

    # Subtest (i): zero-row create_fts_index — must not throw.
    try:
        conn.execute("PRAGMA create_fts_index('articles','eid','title','abstract','keywords', overwrite=1)")
        out["empty_corpus_create"] = "ok"
    except Exception as e:
        out["empty_corpus_create"] = f"FAIL: {e}"

    # Populate and re-create.
    rows = [
        ("E1", "Attention is all you need", "transformer self-attention", "transformer; attention"),
        ("E2", "BERT pre-training", "masked language model bidirectional", "bert; nlp"),
        ("E3", "ResNet deep residual", "image recognition convnet", "resnet; vision"),
    ]
    conn.executemany(
        "INSERT INTO articles VALUES (?,?,?,?)", rows
    )
    try:
        conn.execute("PRAGMA create_fts_index('articles','eid','title','abstract','keywords', overwrite=1)")
        out["populated_create"] = "ok"
    except Exception as e:
        out["populated_create"] = f"FAIL: {e}"

    try:
        # match_bm25 returns a score for each eid given a query.
        result = conn.execute(
            """SELECT eid, fts_main_articles.match_bm25(eid, ?) AS score
               FROM articles
               WHERE score IS NOT NULL
               ORDER BY score DESC""",
            ["transformer attention"],
        ).fetchall()
        out["bm25_query"] = result
    except Exception as e:
        out["bm25_query"] = f"FAIL: {e}"

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
