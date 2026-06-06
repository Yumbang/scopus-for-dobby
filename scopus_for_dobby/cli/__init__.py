"""scopus-for-dobby CLI — entry point and command-group registry.

Usage:
    # Setup API key (free tier)
    scopus-for-dobby auth setup --api-key YOUR_KEY

    # Search papers
    scopus-for-dobby search "deep learning" --limit 20 --sort citedby-count

    # Interactive REPL
    scopus-for-dobby
"""

import click

from ._state import state


@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output as JSON")
@click.pass_context
def cli(ctx, use_json):
    """scopus-for-dobby — Search, collect, and manage academic papers.

    Run without a subcommand to enter interactive REPL mode.
    """
    state.json_output = use_json

    # ADR-7: every CLI subcommand routes through the HTTP daemon. The
    # daemon is lazy-spawned by ``cli/_daemon.ensure_daemon()`` on the
    # first call from any subcommand; no guard is needed here.

    if ctx.invoked_subcommand is None:
        from .repl import repl as repl_cmd

        ctx.invoke(repl_cmd)


from . import auth as _auth  # noqa: E402
from . import author as _author  # noqa: E402
from . import collection as _collection  # noqa: E402
from . import db as _db  # noqa: E402
from . import export as _export  # noqa: E402
from . import repl as _repl  # noqa: E402
from . import search as _search  # noqa: E402
from . import serve as _serve  # noqa: E402

_auth.register(cli)
_search.register(cli)
_db.register(cli)
_collection.register(cli)
_author.register(cli)
_export.register(cli)
_serve.register(cli)
_repl.register(cli)


def main():
    cli()


if __name__ == "__main__":
    main()
