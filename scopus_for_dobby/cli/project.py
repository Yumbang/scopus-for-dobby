"""Project management subcommands — projects group collections."""

import fnmatch

import click

from . import _client as db_mod
from ._output import handle_error, output
from ._state import state


def _resolve_names(names, patterns, candidates) -> list[str]:
    """Union explicit NAMES with the CANDIDATES matching any --match PATTERN.

    Order-preserving and deduplicated. Raises UsageError when nothing was
    asked for, or when any pattern matched nothing — the likeliest cause is a
    typo, and silently acting on the rest hides it.
    """
    if not names and not patterns:
        raise click.UsageError("Name at least one COLLECTION or pass --match GLOB.")
    resolved = list(names)
    for pattern in patterns:
        matched = [c for c in sorted(candidates) if fnmatch.fnmatchcase(c, pattern)]
        if not matched:
            raise click.UsageError(f"--match '{pattern}' matched no collections.")
        resolved.extend(matched)
    return list(dict.fromkeys(resolved))


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


@click.group("project")
def project_cmd():
    """Project management (projects group collections)."""


@project_cmd.command("list")
@handle_error
def project_list():
    """List projects, their collections, and ungrouped collections."""
    result = db_mod.list_projects()
    if state.json_output:
        output(result)
        return
    projects = result.get("projects", {})
    colls = db_mod.list_collections().get("collections", {})
    ungrouped = sum(1 for meta in colls.values() if meta.get("project") is None)

    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()

    if not projects:
        skin.info("No projects yet. Group collections with: project add <project> <collection>...")
    else:
        skin.section("Projects")
        for name, meta in sorted(projects.items()):
            skin.status(
                name,
                f"{_n(meta['collection_count'], 'collection')}, "
                f"{_n(meta['article_count'], 'paper')} (created {meta['created']})",
            )
            for coll in meta["collections"]:
                count = colls.get(coll, {}).get("article_count", 0)
                skin.hint(f"    {coll} — {_n(count, 'article')}")
    skin.hint(f"Ungrouped: {_n(ungrouped, 'collection')}")


@project_cmd.command("create")
@click.argument("name")
@handle_error
def project_create(name):
    """Create a new, empty project."""
    result = db_mod.create_project(name)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    ReplSkin().success(f"Project '{name}' created")


@project_cmd.command("add")
@click.argument("project")
@click.argument("collections", nargs=-1)
@click.option(
    "--match",
    "-m",
    "patterns",
    multiple=True,
    help="Glob over collection names (repeatable), e.g. --match 'thesis-*'",
)
@click.option("--dry-run", is_flag=True, help="Show what would change; change nothing")
@handle_error
def project_add(project, collections, patterns, dry_run):
    """Put collections into PROJECT (created if missing).

    A collection belongs to at most one project, so one already in another
    project is moved. Nothing changes unless every named collection exists.

    \b
    Examples:
      scopus-for-dobby project add thesis ch1-refs ch2-refs
      scopus-for-dobby project add thesis --match 'thesis-*' --dry-run
    """
    colls = db_mod.list_collections().get("collections", {})
    names = _resolve_names(collections, patterns, list(colls))

    if dry_run:
        unknown = [n for n in names if n not in colls]
        already_in = [n for n in names if n in colls and colls[n].get("project") == project]
        would_assign = [n for n in names if n in colls and n not in already_in]
        would_move_from = {
            n: colls[n]["project"] for n in would_assign if colls[n].get("project") is not None
        }
        result = {
            "dry_run": True,
            "project": project,
            "would_create_project": project not in db_mod.list_projects().get("projects", {}),
            "would_assign": would_assign,
            "would_move_from": would_move_from,
            "already_in": already_in,
            "unknown": unknown,
        }
        if state.json_output:
            output(result)
            return
        from scopus_for_dobby.utils.repl_skin import ReplSkin

        skin = ReplSkin()
        skin.info(f"Dry run — nothing changed. Target project: '{project}'")
        if result["would_create_project"]:
            skin.hint(f"would create project '{project}'")
        for n in would_assign:
            moved = f" (moved from {would_move_from[n]})" if n in would_move_from else ""
            skin.hint(f"would assign: {n}{moved}")
        for n in already_in:
            skin.hint(f"already in:   {n}")
        if unknown:
            skin.warning(f"Not found: {', '.join(unknown)} — a real run would change nothing")
        return

    result = db_mod.assign_collections(project, names)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    if result.get("created"):
        skin.info(f"Created project '{project}'")
    moved_from = result.get("moved_from", {})
    for n in result["assigned"]:
        moved = f" (moved from {moved_from[n]})" if n in moved_from else ""
        skin.success(f"{n} → '{project}'{moved}")
    if not result["assigned"]:
        skin.info(f"Nothing to do — already in '{project}'")


@project_cmd.command("remove")
@click.argument("project")
@click.argument("collections", nargs=-1)
@click.option(
    "--match",
    "-m",
    "patterns",
    multiple=True,
    help="Glob over the collections in PROJECT (repeatable)",
)
@handle_error
def project_remove(project, collections, patterns):
    """Take collections out of PROJECT (the collections are kept, ungrouped).

    \b
    Example:
      scopus-for-dobby project remove thesis ch1-refs
    """
    members = []
    if patterns:
        projects = db_mod.list_projects().get("projects", {})
        if project not in projects:
            raise click.ClickException(f"Project '{project}' does not exist.")
        members = projects[project]["collections"]
    names = _resolve_names(collections, patterns, members)

    result = db_mod.unassign_collections(project, names)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    for n in result["unassigned"]:
        skin.success(f"{n} removed from '{project}' (collection kept)")


@project_cmd.command("rename")
@click.argument("old")
@click.argument("new")
@handle_error
def project_rename(old, new):
    """Rename a project (keeps its collections and created date)."""
    result = db_mod.rename_project(old, new)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    if result.get("noop"):
        skin.info(f"old == new ('{old}'); no-op.")
        return
    skin.success(f"Renamed '{result['renamed_from']}' → '{result['renamed_to']}'")


@project_cmd.command("delete")
@click.argument("name")
@click.option("--confirm", is_flag=True, help="Skip confirmation")
@handle_error
def project_delete(name, confirm):
    """Delete a project (its collections and articles are kept, ungrouped)."""
    if not confirm and not state.repl_mode and not state.json_output:
        click.confirm(f"Delete project '{name}'? Its collections are kept.", abort=True)
    result = db_mod.delete_project(name)
    if state.json_output:
        output(result)
        return
    from scopus_for_dobby.utils.repl_skin import ReplSkin

    skin = ReplSkin()
    skin.success(f"Project '{name}' deleted")
    released = result.get("released", [])
    if released:
        skin.hint(f"Collections kept, now ungrouped: {', '.join(released)}")
    else:
        skin.hint("It held no collections.")


def register(cli_group):
    cli_group.add_command(project_cmd)
