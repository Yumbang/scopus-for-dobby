# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Always use `uv` for Python tooling (never pip, python -m pip, or virtualenv directly).

```bash
# Install the CLI as a uv tool (makes `scopus-for-dobby` available on PATH).
# Use ".[gui]" if the macOS GUI is in play — its Launch button spawns this
# binary, and the daemon server it starts lives in that extra.
uv tool install --reinstall --editable ".[gui]"
# CLI only, no daemon server (a bare install can still attach to one):
uv tool install --reinstall --editable .

# Dev environment (for running tests and linting)
# `.python-version` pins 3.14, so bare `uv venv` picks it up — don't pass --python.
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"  # [dev] adds pytest/ruff + the daemon server

# Lint and format (always use ruff, never pylint/flake8/black/isort)
ruff check .
ruff format --check .
ruff check --fix .        # auto-fix lint issues
ruff format .             # auto-format

# Tests
pytest
pytest tests/test_core.py::TestArticleDB::test_add_entries
```

After code changes, always reinstall the CLI tool before testing. Keep the
extra you installed with — `--reinstall` rebuilds the environment from the
spec you give it, so dropping `[gui]` here silently uninstalls the daemon
server and the GUI's Launch button starts failing with
"Starting a daemon requires the optional [gui] extra":
```bash
uv tool install --reinstall --editable ".[gui]"
```

Extras: `gui` is the only meaningful one (the HTTP daemon *server* — `fastapi`, `uvicorn`). `cli` and `export` are empty backwards-compat aliases; their contents are core dependencies. `httpx` is core too: the server is optional, but any install may have to talk to a daemon someone else started, and starting the macOS GUI puts every CLI invocation on that machine onto the HTTP path. Never reintroduce a dep the CLI needs at import time as an extra.

## Python version

The project default is **3.14**, pinned in `.python-version` — that is what `uv venv` and `uv run` select. `requires-python` stays at `>=3.10`, which is a supported floor rather than a target: CI runs the suite on both ends. `[tool.ruff] target-version` tracks the **floor** (`py310`) so pyupgrade never rewrites code into syntax 3.10 cannot parse; raise the two together or not at all.

## Agent skills

`scopus_for_dobby/skill/<name>/` holds the agent-facing documentation, shipped as package data (`skill/*/SKILL.md`, `skill/*/references/*.md`) and installed by `scopus-for-dobby skill install`. Two registries in `core/skill.py`: `SKILLS` (what ships) and `TARGETS` (which agents, where). Adding either is one entry.

- `scopus-for-dobby` — driving the CLI
- `paper-fulltext` — reading one paper's body (methods, a quote, a figure)
- `citation-analysis` — reading a citation graph
- `corpus-profiling` — characterising a large set of papers by topic/keyword

Only the first is tool-shaped ("how do I use this CLI?"); the other three are
task-shaped and fire on a research question. A capability that answers a research
question belongs in its own skill — buried in the CLI reference, it is only
reachable by an agent that already decided to consult a manual.

Skill descriptions are a shared trigger space: each must claim its own question and explicitly disclaim the others', or the wrong one loads. `corpus-profiling` in particular must not fire when a plain `db list` is what was wanted — its description says so, and a test asserts the descriptions do not collide. `paper-fulltext` carries the same risk in the other direction: fetching a body spends metered Elsevier quota, so its description has to disclaim ordinary searching and listing, and only one skill may claim the body question at a time.

Because they ship with the code, **the skills are part of the change**: any edit to CLI behavior, install extras, or the daemon model must update the relevant `SKILL.md` and `references/` in the same commit. The out-of-repo copy this replaced drifted badly — it documented the removed lazy-spawn daemon for weeks.

`evals/` beside a skill is development material: excluded from both the wheel and the install, so editable and wheel installs produce identical agent directories.

## Citation graph analysis

`core/openalex.py` builds graphs (`build_citation_graph`, `--depth 1..3`); `core/graph_analysis.py` interprets them; `cli/openalex.py::analyze` presents them. Nothing is persisted to DuckDB — graphs live in memory and in files, so this works on any database.

`core/text_analysis.py` + `cli/profile.py` are the text-side counterpart: controlled-vocabulary profiling over `openalex_topics` / `index_keywords` / `subject_areas`, stdlib only.

Four invariants worth preserving:

- **Beyond depth 1, expansion is relevance-gated** (`min_reached`). Ungated, ~19–50 references per work means millions of nodes at depth 3.
- **The node budget is checked between levels, never inside one.** A half-expanded level leaves seeds marked `role: seed` with references never fetched, which every downstream measure then treats as complete — and the loss is in iteration order, so it is systematically biased.
- **Structural metrics may only see `seed`/`expanded` nodes.** A `frontier` node's missing edges are an artifact of where expansion stopped. A depth-1 graph is a star, so centrality on it is degenerate — `describe_topology()` refuses it and reports why rather than silently dropping the section.
- **`reached_by` is not seed citations.** It counts every expanding node; `seed_citation_counts()` derives the seed-only figure from the edge list rather than trusting a stored field, so an older export cannot silently overstate.

## Security

API credentials live in `~/.scopus-for-dobby/config.json` (chmod 600), never in the project directory. Two are stored there: the Scopus key/inst-token, and an optional OpenAlex `api_key` (`openalex key`). OpenAlex is metered per request — anonymous callers share a small budget **per IP address**, so a key is what keeps one process from exhausting another's allowance. Never log or commit API keys. Ruff's `S` (bandit) rules are enabled.

## Architecture

Stateful Click CLI for the Elsevier Scopus API. Runs as direct subcommands or interactive REPL (default). All API calls go through `utils/api_client.py` (`api_get()`), which handles auth headers and per-endpoint rate limiting. Local storage uses DuckDB (`core/article_db.py`) with articles, authors, and collections tables linked via an `article_authors` junction table. Authors are auto-extracted on every `add_entries()` call. Session state (last search/abstract) persists to disk so results survive across CLI invocations. All user data lives under `~/.scopus-for-dobby/`.

### DB access path

Subcommands never import `core/article_db` directly — they go through `cli/_client.py`, which picks one backend per process:

- **in-process** (default) — `core/article_db` opened directly. No daemon, no HTTP.
- **daemon** (`cli/_http.py`) — chosen only when `~/.scopus-for-dobby/daemon.{pid,port}` point at a live process, because DuckDB allows a single read/write process per file and the daemon holds it.

The daemon *server* (`fastapi`, `uvicorn`) lives in the optional `[gui]` extra; the client (`httpx`) is core, so a bare install can attach to a daemon it cannot itself start. This amends ADR-7, which had every CLI invocation lazy-spawn a daemon. Any function reachable via `db_mod.<name>` must be listed in `_client._API` and implemented by **both** backends.
