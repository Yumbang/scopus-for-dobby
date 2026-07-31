"""`scopus-for-dobby skill` — install the bundled agent skill.

The skill ships inside the package, so this works from any install without a
repo checkout or an agent-specific registry.
"""

from __future__ import annotations

from pathlib import Path

import click

from scopus_for_dobby.core import skill as skill_mod

from ._output import handle_error, output
from ._state import state


def _scope_from_flags(scope, is_global, is_project):
    """Resolve --scope / --global / --project into one scope, or None."""
    chosen = [
        name
        for name, on in (("global", is_global), ("project", is_project))
        if on
    ]
    if len(chosen) > 1:
        raise click.UsageError("--global and --project are mutually exclusive.")
    if chosen and scope:
        raise click.UsageError(f"Use either --scope or --{chosen[0]}, not both.")
    return chosen[0] if chosen else scope


def register(cli):
    @cli.group("skill")
    def skill_grp():
        """Install the agent skill that teaches an LLM to drive this CLI."""

    @skill_grp.command("install")
    @click.argument("agent", default="claude")
    @click.option(
        "--scope",
        type=click.Choice(["global", "project", "user", "local"]),
        default=None,
        help="Where to install (default: the agent's usual scope).",
    )
    @click.option("--global", "is_global", is_flag=True, help="Shorthand for --scope global.")
    @click.option("--project", "is_project", is_flag=True, help="Shorthand for --scope project.")
    @click.option(
        "--dir",
        "dest",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="Install into this directory instead of the standard location.",
    )
    @click.option(
        "--skill",
        "skills",
        multiple=True,
        help="Install only this skill (repeatable). Default: all of them.",
    )
    @click.option(
        "--no-agents-md",
        "agents_md",
        is_flag=True,
        default=True,
        flag_value=False,
        help="Don't write the AGENTS.md pointer section.",
    )
    @click.option("--dry-run", is_flag=True, help="Show what would happen, write nothing.")
    @handle_error
    def install_cmd(agent, scope, is_global, is_project, dest, skills, agents_md, dry_run):
        """Install the bundled skills for AGENT (default: claude).

        \b
        Examples:
          scopus-for-dobby skill install                     # all skills, Claude, global
          scopus-for-dobby skill install claude --project    # into ./.claude/skills/
          scopus-for-dobby skill install agents              # AGENTS.md-based agents
          scopus-for-dobby skill install --skill citation-analysis
          scopus-for-dobby skill install --dry-run
        """
        result = skill_mod.install(
            agent,
            scope=_scope_from_flags(scope, is_global, is_project),
            dest=dest,
            skills=list(skills) or None,
            agents_md=agents_md,
            dry_run=dry_run,
        )

        if state.json_output:
            output(result)
            return

        verb = "Would install" if dry_run else "Installed"
        count = len(result["skills"])
        noun = "skill" if count == 1 else "skills"
        click.echo(f"{verb} {count} {noun} for {result['label']}  (scope: {result['scope']})")
        for entry in result["skills"]:
            click.echo(f"  {entry['skill']}  →  {entry['path']}  ({len(entry['files'])} files)")
        if result.get("agents_md"):
            statuses = {e.get("agents_md_status", "would update") for e in result["skills"]}
            click.echo(f"  AGENTS.md: {result['agents_md']} ({', '.join(sorted(statuses))})")
        if result.get("note"):
            click.echo(f"  note:  {result['note']}")
        if not dry_run:
            click.echo("\nStart a new agent session to pick them up.")

    @skill_grp.command("list")
    @handle_error
    def list_cmd():
        """Show the bundled skills and where each agent would install them."""
        skills = skill_mod.list_skills()
        targets = skill_mod.list_targets()

        if state.json_output:
            output({"skills": skills, "targets": targets})
            return

        click.echo("Skills:")
        for s in skills:
            mark = " " if s["available"] else "!"
            click.echo(f" {mark}{s['skill']} ({s['files']} files)")
            click.echo(f"    {s['summary']}")
            if not s["available"]:
                click.echo("    NOT PACKAGED — reinstall the package")
        click.echo()

        click.echo("Agents:")
        for t in targets:
            click.echo(f"  {t['agent']} — {t['label']}")
            for scope, path in t["paths"].items():
                default = "  (default)" if scope == t["default_scope"] else ""
                click.echo(f"    {scope:8} {path}/<skill>{default}")
            if t["discovery_note"]:
                click.echo(f"    {t['discovery_note']}")

    @skill_grp.command("path")
    @handle_error
    def path_cmd():
        """Print where the bundled skill sources live."""
        root = skill_mod.SKILLS_ROOT
        if state.json_output:
            output(
                {
                    "root": str(root),
                    "exists": root.is_dir(),
                    "skills": {n: str(s.src) for n, s in skill_mod.SKILLS.items()},
                }
            )
            return
        click.echo(str(root))
