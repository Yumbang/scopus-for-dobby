"""Output formatting and error handling for CLI commands."""

import json
import sys

import click

from ._state import state


def output(data, message: str = ""):
    """Print output in JSON or human-readable format."""
    if state.json_output:
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if not k.startswith("_")}
        click.echo(json.dumps(data, indent=2, default=str))
    else:
        if message:
            click.echo(message)
        if isinstance(data, dict):
            _print_dict(data)
        elif isinstance(data, list):
            _print_list(data)
        else:
            click.echo(str(data))


def _print_dict(d: dict, indent: int = 0):
    prefix = "  " * indent
    for k, v in d.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict):
            click.echo(f"{prefix}{k}:")
            _print_dict(v, indent + 1)
        elif isinstance(v, list):
            click.echo(f"{prefix}{k}:")
            _print_list(v, indent + 1)
        else:
            click.echo(f"{prefix}{k}: {v}")


def _print_list(items: list, indent: int = 0):
    prefix = "  " * indent
    for i, item in enumerate(items):
        if isinstance(item, dict):
            click.echo(f"{prefix}[{i}]")
            _print_dict(item, indent + 1)
        else:
            click.echo(f"{prefix}- {item}")


def _friendly(e: Exception) -> str:
    """Translate low-level failures into something the user can act on.

    The common one is DuckDB's exclusive file lock: only one process may hold
    the database read/write. The CLI runs in-process by default, so a second
    concurrent invocation — or one racing an open REPL session — hits this.
    The fix is to put a daemon in front of the file so every client shares it.
    """
    msg = str(e)
    if "Could not set lock" in msg or "lock on file" in msg:
        return (
            "The article database is locked by another process — DuckDB allows "
            "only one writer at a time.\n"
            "This happens when a REPL session, another command, or the macOS GUI "
            "already holds it.\n"
            "To let several clients share the database, start the daemon and "
            "re-run:\n"
            "    scopus-for-dobby serve        # needs the [gui] extra\n"
            f"\nOriginal error: {msg}"
        )
    return msg


def handle_error(func):
    """Decorator for consistent error handling across commands."""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if state.json_output:
                click.echo(json.dumps({"error": _friendly(e), "type": type(e).__name__}))
            else:
                click.echo(f"Error: {_friendly(e)}", err=True)
            if not state.repl_mode:
                sys.exit(1)

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper
