"""The CLI skill's command table must name every top-level command.

CLAUDE.md makes the skills part of every CLI change, but nothing enforced it:
the table had silently lost `profile`, `skill` and `repl`. An agent that
reads the table to learn the CLI cannot use a command it never sees.
"""

import re
from pathlib import Path

from scopus_for_dobby.cli import cli

SKILL_MD = (
    Path(__file__).parent.parent / "scopus_for_dobby" / "skill" / "scopus-for-dobby" / "SKILL.md"
)


def _table_commands() -> set[str]:
    """First word of the first cell of each row in the `| Command | Does |` table."""
    lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r"\|\s*Command\s*\|", line))
    names = set()
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cell = line.split("|")[1].strip()
        match = re.match(r"`([a-z][\w-]*)", cell)
        if match:
            names.add(match.group(1))
    return names


def test_every_top_level_command_is_in_the_table():
    missing = sorted(set(cli.commands) - _table_commands())
    assert not missing, f"Add these commands to the table in {SKILL_MD}: {missing}"


def test_table_names_no_command_that_does_not_exist():
    extra = sorted(_table_commands() - set(cli.commands))
    assert not extra, f"The table in {SKILL_MD} names commands the CLI lacks: {extra}"
