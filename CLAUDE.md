# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Always use `uv` for Python tooling (never pip, python -m pip, or virtualenv directly).

```bash
# Install the CLI as a uv tool (makes `scopus-for-dobby` available on PATH)
uv tool install --reinstall --editable .
# ...add the optional daemon (macOS GUI / multi-process access):
uv tool install --reinstall --editable ".[gui]"

# Dev environment (for running tests and linting)
# `.python-version` pins 3.14, so bare `uv venv` picks it up — don't pass --python.
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"  # [dev] bundles cli + export deps for tests

# Lint and format (always use ruff, never pylint/flake8/black/isort)
ruff check .
ruff format --check .
ruff check --fix .        # auto-fix lint issues
ruff format .             # auto-format

# Tests
pytest
pytest tests/test_core.py::TestArticleDB::test_add_entries
```

After code changes, always reinstall the CLI tool before testing:
```bash
uv tool install --reinstall --editable .
```

Extras: `gui` is the only meaningful one (the HTTP daemon — `fastapi`, `uvicorn`, `httpx`). `cli` and `export` are empty backwards-compat aliases; their contents are core dependencies. Never reintroduce a dep the CLI needs at import time as an extra.

## Python version

The project default is **3.14**, pinned in `.python-version` — that is what `uv venv` and `uv run` select. `requires-python` stays at `>=3.10`, which is a supported floor rather than a target: CI runs the suite on both ends. `[tool.ruff] target-version` tracks the **floor** (`py310`) so pyupgrade never rewrites code into syntax 3.10 cannot parse; raise the two together or not at all.

## Security

API credentials live in `~/.scopus-for-dobby/config.json` (chmod 600), never in the project directory. Never log or commit API keys. Ruff's `S` (bandit) rules are enabled.

## Architecture

Stateful Click CLI for the Elsevier Scopus API. Runs as direct subcommands or interactive REPL (default). All API calls go through `utils/api_client.py` (`api_get()`), which handles auth headers and per-endpoint rate limiting. Local storage uses DuckDB (`core/article_db.py`) with articles, authors, and collections tables linked via an `article_authors` junction table. Authors are auto-extracted on every `add_entries()` call. Session state (last search/abstract) persists to disk so results survive across CLI invocations. All user data lives under `~/.scopus-for-dobby/`.

### DB access path

Subcommands never import `core/article_db` directly — they go through `cli/_client.py`, which picks one backend per process:

- **in-process** (default) — `core/article_db` opened directly. No daemon, no HTTP.
- **daemon** (`cli/_http.py`) — chosen only when `~/.scopus-for-dobby/daemon.{pid,port}` point at a live process, because DuckDB allows a single read/write process per file and the daemon holds it.

The daemon stack (`fastapi`, `uvicorn`, `httpx`) lives in the optional `[gui]` extra. This amends ADR-7, which had every CLI invocation lazy-spawn a daemon. Any function reachable via `db_mod.<name>` must be listed in `_client._API` and implemented by **both** backends.
