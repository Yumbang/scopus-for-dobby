# Troubleshooting

## How the CLI actually runs (know this before debugging)

Each command opens the DuckDB database **in-process** and exits. Nothing is
spawned, nothing keeps running afterwards.

The exception: if an HTTP daemon is already listening (someone ran
`scopus-for-dobby serve`, or the macOS GUI launched one), the CLI detects it via
`~/.scopus-for-dobby/daemon.port` and routes through it instead. That is
required, not optional — DuckDB allows a single read/write process per file, and
the daemon holds it.

The daemon *server* ships in the optional `[gui]` extra (`fastapi`, `uvicorn`).
A plain install cannot start one and rarely needs to — but it will use one
automatically if a daemon is already up (the macOS GUI starts one), because the
HTTP client is a core dependency.

State files under `~/.scopus-for-dobby/`:

| File | Purpose |
|---|---|
| `articles.duckdb` | The database |
| `config.json` | API key, tier, OpenAlex email, cached quota (chmod 600) |
| `session/` | Last search/abstract, working collection |
| `daemon.pid`, `daemon.port` | Present only while a daemon runs. Read `daemon.port` rather than assuming 8765 — see below |
| `daemon.log` | Daemon diagnostics — rotates at 2 MB, keeps 2 backups |

## Symptoms → fixes

**"The article database is locked by another process."**
Two things tried to open DuckDB read/write at once — typically a command run
while a REPL session is open, or while the GUI's daemon holds the file. Either
close the other one, or put a daemon in front so everything shares a single
connection:

```bash
scopus-for-dobby serve        # another terminal; needs the [gui] extra
```

**The daemon is not on 8765.**
That port is popular — other tools take it. With no explicit `--port`, `serve`
treats the default as a guess and moves to the next free port, announcing
`Port 8765 is busy; using 8767.` An explicit `--port` is a request and fails
loudly instead of moving. Clients read `~/.scopus-for-dobby/daemon.port`, so
they follow it either way; anything that hardcodes 8765 will not.

**`serve` says the `[gui]` extra is required.**
Expected on a default install. `uv tool install --reinstall --editable ".[gui]"`
from a repo checkout.

**A command hangs for many seconds on first use.**
DuckDB installs its FTS extension when missing — a network download. It happens
once per machine; subsequent runs are fast.

**GUI shows "daemon not running".**
Plain CLI commands do **not** start a daemon. Use the GUI's "Launch daemon"
button, or run `scopus-for-dobby serve` yourself.

**Something failed inside the daemon.**
Its diagnostics go to `~/.scopus-for-dobby/daemon.log` (the daemon writes this
itself, so it works even when the GUI discards its stdout):

```bash
curl -s "http://127.0.0.1:$(cat ~/.scopus-for-dobby/daemon.port)/health"   # alive?
tail -50 ~/.scopus-for-dobby/daemon.log
```

If a daemon is truly wedged:

```bash
kill $(cat ~/.scopus-for-dobby/daemon.pid) 2>/dev/null
rm -f ~/.scopus-for-dobby/daemon.{pid,port}
lsof -ti tcp:8765 | xargs kill 2>/dev/null   # orphan not matching the pid file
```

**`db list --query` misses matches you expected.**
By design: a plain substring (LIKE) match over title/abstract/keywords/notes/author/journal —
no stemming, no ranking. Try a shorter substring.

**HTTP 429 from Scopus.**
Weekly quota exhausted (per-endpoint limits in `search.md`). The error shows the
reset time. `auth quota` reports the cached remaining budget without spending a
call. OpenAlex work (`openalex enrich/graph`) still runs — separate, free quota.
A 429 during `fulltext` is the **Article Retrieval** bucket (**paper-fulltext** skill), not
the abstract one; remaining items in that batch are skipped.

**401/403 from Scopus.**
Key invalid or tier mismatch — `auth status` tests connectivity and shows the
tier. Institutional features need `auth upgrade --inst-token ...` and usually the
institution network/VPN. On `fulltext`, 401/403 on one paper means that item is
not entitled — the rest of the batch continues (**paper-fulltext** skill).

**`fulltext` reports `error` with "malformed XML".**
Elsevier returned a truncated or non-XML 200. Nothing was cached, the rest of
the batch ran, and re-running the command is safe. A bundle already on disk
whose XML no longer parses is discarded and refetched automatically — there is
no cache to clear by hand.

**`Binder Error: Referenced update column openalex_id not found`.**
A database that missed a schema migration. Fixed — any recent version repairs the
columns automatically on open and logs `Repaired schema drift`. Upgrade and rerun;
no data is lost.

**Wrong/corrupt data; want a clean slate.**
`rm ~/.scopus-for-dobby/articles.duckdb` — recreated on next use. Older databases
migrate in place automatically, so an upgrade never requires this.

## Rules of thumb

- Never open `articles.duckdb` with Python/duckdb directly while anything else
  might be running — DuckDB is single-writer. Use `--json` output instead
  (`library.md` has patterns).
- Daemon faults land in `daemon.log`; CLI faults print to stderr. Quote these
  when reporting bugs.
