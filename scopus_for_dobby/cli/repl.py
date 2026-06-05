"""Interactive REPL subcommand."""

import click

from scopus_for_dobby.core import auth as auth_mod
from scopus_for_dobby.core.session import get_session

from . import _client as db_mod
from ._output import handle_error
from ._state import state


@click.command()
@handle_error
def repl():
    """Start interactive REPL session."""
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    state.repl_mode = True

    skin = ReplSkin()
    skin.print_banner()

    pt_session = skin.create_prompt_session()

    _repl_commands = {
        "auth": "setup | upgrade | downgrade | status | quota | logout",
        "search": "<query> [--limit N] [--sort FIELD] [--year RANGE]",
        "search-all": "<query> [--max N] — fetch multiple pages",
        "abstract": "<DOI|EID|ID> — get paper details",
        "db": "add | list | remove | tag | untag | note | info | stats",
        "author": "list | info | fetch | coauthors | note",
        "collection": "list | create | delete | add | remove | set | unset | current",
        "export": "--format xlsx|bibtex|ris [--collection NAME]",
        "help": "Show this help",
        "quit": "Exit REPL",
    }

    try:
        status = auth_mod.get_status()
        if status.get("api_connected"):
            remaining = status.get("rate_limit_remaining")
            skin.update_quota(remaining)
            skin.success(
                f"Connected ({status.get('tier', 'free')} tier) — "
                f"quota remaining: {remaining if remaining is not None else '?'}"
            )
        elif status.get("configured"):
            skin.warning("API key configured but connection failed. Check your key.")
        else:
            skin.info("Not configured. Run: auth setup --api-key YOUR_KEY")
    except Exception:
        skin.info("Run 'auth setup --api-key YOUR_KEY' to get started.")

    try:
        st = db_mod.stats()
        if st["total_articles"] > 0:
            skin.info(
                f"Local DB: {st['total_articles']} articles, {st['total_collections']} collections"
            )
    except Exception:
        pass

    from scopus_for_dobby.cli import cli as _cli_root

    while True:
        try:
            session = get_session()
            ctx_parts = []
            tier = ""
            try:
                config = auth_mod.load_config()
                tier = config.get("tier", "")
            except Exception:
                pass
            if tier:
                ctx_parts.append(tier)
            if session.working_collection:
                ctx_parts.append(f"coll:{session.working_collection}")

            context = " | ".join(ctx_parts) if ctx_parts else ""

            line = skin.get_input(pt_session, context=context)
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                skin.print_goodbye()
                break
            if line.lower() == "help":
                skin.help(_repl_commands)
                continue

            args = line.split()
            try:
                _cli_root.main(args, standalone_mode=False)
            except SystemExit:
                pass
            except click.exceptions.UsageError as e:
                skin.warning(f"Usage: {e}")
            except Exception as e:
                skin.error(str(e))

        except (EOFError, KeyboardInterrupt):
            skin.print_goodbye()
            break

    state.repl_mode = False


def register(cli_group):
    cli_group.add_command(repl)
