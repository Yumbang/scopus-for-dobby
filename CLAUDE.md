# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Always use `uv` for Python tooling (never pip, python -m pip, or virtualenv directly).

```bash
# Install the CLI as a uv tool (makes `scopus-for-dobby` available on PATH)
uv tool install --reinstall --editable ".[export]"

# Dev environment (for running tests and linting)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev,export]"

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
uv tool install --reinstall --editable ".[export]"
```

## Security

API credentials live in `~/.scopus-for-dobby/config.json` (chmod 600), never in the project directory. Never log or commit API keys. Ruff's `S` (bandit) rules are enabled.

## Architecture

Stateful Click CLI for the Elsevier Scopus API. Runs as direct subcommands or interactive REPL (default). All API calls go through `utils/api_client.py` (`api_get()`), which handles auth headers and per-endpoint rate limiting. Local storage uses DuckDB (`core/article_db.py`) with articles, authors, and collections tables linked via an `article_authors` junction table. Authors are auto-extracted on every `add_entries()` call. Session state (last search/abstract) persists to disk so results survive across CLI invocations. All user data lives under `~/.scopus-for-dobby/`.
