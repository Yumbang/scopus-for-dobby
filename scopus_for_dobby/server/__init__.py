"""HTTP daemon for scopus-for-dobby (Plan C architecture).

The daemon owns the only DuckDB connection in the system. CLI invocations
detect a running daemon (via PID/port file) and route mutations through
HTTP. The macOS GUI also queries the daemon (read endpoints + SSE event
stream) instead of opening DuckDB directly, since DuckDB enforces an
exclusive file lock per process.

See spikes/duckdb_mvcc/REPORT.md for why direct cross-process reads were
rejected.
"""

from .app import build_app

__all__ = ["build_app"]
