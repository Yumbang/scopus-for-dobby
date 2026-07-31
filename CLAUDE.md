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

## Agent skills

`scopus_for_dobby/skill/<name>/` holds the agent-facing documentation, shipped as package data (`skill/*/SKILL.md`, `skill/*/references/*.md`) and installed by `scopus-for-dobby skill install`. Two registries in `core/skill.py`: `SKILLS` (what ships) and `TARGETS` (which agents, where). Adding either is one entry.

- `scopus-for-dobby` — driving the CLI
- `citation-analysis` — reading a citation graph

Because they ship with the code, **the skills are part of the change**: any edit to CLI behavior, install extras, or the daemon model must update the relevant `SKILL.md` and `references/` in the same commit. The out-of-repo copy this replaced drifted badly — it documented the removed lazy-spawn daemon for weeks.

`evals/` beside a skill is development material: excluded from both the wheel and the install, so editable and wheel installs produce identical agent directories.

## Citation graph analysis

`core/openalex.py` builds graphs (`build_citation_graph`, `--depth 1..3`); `core/graph_analysis.py` interprets them; `cli/openalex.py::analyze` presents them. Nothing is persisted to DuckDB — graphs live in memory and in files, so this works on any database.

Two invariants worth preserving:

- **Beyond depth 1, expansion is relevance-gated** (`min_reached`). Ungated, ~35–50 references per work means millions of nodes at depth 3.
- **Structural metrics may only see `seed`/`expanded` nodes.** A `frontier` node's missing edges are an artifact of where expansion stopped. A depth-1 graph is a star, so centrality on it is degenerate — `describe_topology()` is what refuses it, and the refusal is reported to the user rather than silently dropped.

## Security

API credentials live in `~/.scopus-for-dobby/config.json` (chmod 600), never in the project directory. Never log or commit API keys. Ruff's `S` (bandit) rules are enabled.

## Architecture

Stateful Click CLI for the Elsevier Scopus API. Runs as direct subcommands or interactive REPL (default). All API calls go through `utils/api_client.py` (`api_get()`), which handles auth headers and per-endpoint rate limiting. Local storage uses DuckDB (`core/article_db.py`) with articles, authors, and collections tables linked via an `article_authors` junction table. Authors are auto-extracted on every `add_entries()` call. Session state (last search/abstract) persists to disk so results survive across CLI invocations. All user data lives under `~/.scopus-for-dobby/`.

### DB access path

Subcommands never import `core/article_db` directly — they go through `cli/_client.py`, which picks one backend per process:

- **in-process** (default) — `core/article_db` opened directly. No daemon, no HTTP.
- **daemon** (`cli/_http.py`) — chosen only when `~/.scopus-for-dobby/daemon.{pid,port}` point at a live process, because DuckDB allows a single read/write process per file and the daemon holds it.

The daemon stack (`fastapi`, `uvicorn`, `httpx`) lives in the optional `[gui]` extra. This amends ADR-7, which had every CLI invocation lazy-spawn a daemon. Any function reachable via `db_mod.<name>` must be listed in `_client._API` and implemented by **both** backends.
