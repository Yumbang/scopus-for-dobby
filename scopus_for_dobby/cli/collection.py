"""Collection management subcommands."""

import click

from scopus_for_dobby.core.session import get_session

from . import _client as db_mod
from ._output import handle_error, output
from ._state import state


@click.group("collection")
def collection_cmd():
    """Collection management."""


@collection_cmd.command("list")
@handle_error
def collection_list():
    """List all collections."""
    result = db_mod.list_collections()
    if state.json_output:
        output(result)
        return
    colls = result.get("collections", {})

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    if not colls:
        skin.info("No collections yet. Create one with: collection create <name>")
        return

    skin.section("Collections")
    for name, meta in colls.items():
        skin.status(name, f"{meta['article_count']} articles (created {meta['created']})")


@collection_cmd.command("create")
@click.argument("name")
@handle_error
def collection_create(name):
    """Create a new collection."""
    result = db_mod.create_collection(name)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Collection '{name}' created")


@collection_cmd.command("delete")
@click.argument("name")
@click.option("--confirm", is_flag=True, help="Skip confirmation")
@handle_error
def collection_delete(name, confirm):
    """Delete a collection (articles are kept in DB)."""
    if not confirm and not state.repl_mode and not state.json_output:
        click.confirm(f"Delete collection '{name}'?", abort=True)
    result = db_mod.delete_collection(name)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Collection '{name}' deleted")


@collection_cmd.command("merge")
@click.argument("src")
@click.argument("dst")
@handle_error
def collection_merge(src, dst):
    """Merge collection SRC into DST (set union, then delete SRC).

    \b
    Example:
      scopus-for-dobby collection merge old-name new-name
    """
    result = db_mod.merge_collections(src, dst)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    if result.get("noop"):
        skin.info(f"src == dst ('{src}'); no-op.")
        return
    skin.success(
        f"Merged '{result['merged_from']}' → '{result['merged_to']}' "
        f"({result['moved']} moved)"
    )


@collection_cmd.command("rename")
@click.argument("old")
@click.argument("new")
@handle_error
def collection_rename(old, new):
    """Rename a collection (preserves created_at and article membership).

    \b
    Example:
      scopus-for-dobby collection rename old-name new-name
    """
    result = db_mod.rename_collection(old, new)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    if result.get("noop"):
        skin.info(f"old == new ('{old}'); no-op.")
        return
    skin.success(f"Renamed '{result['renamed_from']}' → '{result['renamed_to']}'")


def _resolve_eids(eid_tuple, indices, eids_from_stdin, eids_from_file) -> list[str]:
    """Resolve --eid / --indices / --eids-from-stdin / --eids-from-file into a list."""
    eids = list(eid_tuple)
    if indices:
        session = get_session()
        idx_list = [int(x.strip()) for x in indices.split(",") if x.strip()]
        entries = session.get_entries_by_indices(idx_list)
        eids.extend(e.get("eid", "") for e in entries if e.get("eid"))
    if eids_from_file:
        with open(eids_from_file) as f:
            eids.extend(line.strip() for line in f if line.strip())
    if eids_from_stdin:
        import sys

        eids.extend(line.strip() for line in sys.stdin if line.strip())
    return [e for e in eids if e]


@collection_cmd.command("add")
@click.argument("name")
@click.option("--indices", "-i", default=None, help="Comma-separated indices from last list/search")
@click.option("--eid", "-e", multiple=True, help="EID(s) to add")
@click.option(
    "--eids-from-stdin",
    is_flag=True,
    help="Read newline-delimited EIDs from stdin",
)
@click.option(
    "--eids-from-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Read newline-delimited EIDs from a file",
)
@handle_error
def collection_add(name, indices, eid, eids_from_stdin, eids_from_file):
    """Add articles to a collection.

    \b
    Examples:
      scopus-for-dobby collection add thesis-refs --indices 1,3,5
      scopus-for-dobby collection add thesis-refs --eid 2-s2.0-85012345678
      cat eids.txt | scopus-for-dobby collection add thesis-refs --eids-from-stdin
    """
    eids = _resolve_eids(eid, indices, eids_from_stdin, eids_from_file)

    if not eids:
        click.echo("No articles specified.", err=True)
        return

    result = db_mod.add_to_collection(name, eids)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Added {result['added']} to '{name}' ({result['total']} total)")


@collection_cmd.command("remove")
@click.argument("name")
@click.option("--indices", "-i", default=None, help="Comma-separated indices")
@click.option("--eid", "-e", multiple=True, help="EID(s) to remove")
@click.option(
    "--eids-from-stdin",
    is_flag=True,
    help="Read newline-delimited EIDs from stdin",
)
@click.option(
    "--eids-from-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Read newline-delimited EIDs from a file",
)
@handle_error
def collection_remove(name, indices, eid, eids_from_stdin, eids_from_file):
    """Remove articles from a collection."""
    eids = _resolve_eids(eid, indices, eids_from_stdin, eids_from_file)

    result = db_mod.remove_from_collection(name, eids)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Removed {result['removed']} from '{name}' ({result['total']} remaining)")


def register(cli_group):
    cli_group.add_command(collection_cmd)
