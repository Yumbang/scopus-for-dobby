"""Install the bundled agent skill into whatever agent the user runs.

The skill (``scopus_for_dobby/skill/``) ships as package data, so it travels
with the CLI — ``uv tool install scopus-for-dobby`` then
``scopus-for-dobby skill install`` works with no repo checkout and no
agent-specific package registry.

Two targets, deliberately:

``claude``
    A skill directory (``SKILL.md`` + ``references/``) under ``.claude/skills/``.
    Claude Code discovers it from the frontmatter ``description`` on its own, so
    nothing else is written — no CLAUDE.md edit is needed or made.

``agents``
    The same directory under ``.agents/skills/``, plus a pointer section in
    ``AGENTS.md`` — the cross-agent convention that Codex, Cursor, Zed, Aider
    and others already read. Unlike Claude, those agents have no skill
    auto-discovery, so without the pointer the directory is never found: here
    the section is the discovery mechanism, not a convenience. It can still be
    declined with ``agents_md=False``, and is skipped in global scope, where no
    equivalent convention exists.

Each target installs at either scope:

``global``
    Under the home directory — available in every project. (``user`` is
    accepted as an alias.)

``project``
    Under the current directory — travels with the repo, so collaborators and
    CI get it by checking out.

``install``, ``uninstall`` and ``status`` are one lifecycle: whatever options
place a skill take it back out again, and ``status`` compares an installed
copy's content hash against the packaged one. That comparison is the point of
``status`` — an install goes stale on any upgrade the user does not re-run
``skill install`` for, and a skill documenting behaviour the CLI no longer has
is worse than no skill at all, because the agent follows it confidently.

Adding a target is one entry in ``TARGETS``. Paths are only claimed for
layouts that can actually be verified; inventing a path for an agent nobody
tested installs a skill that silently never loads.
"""

from __future__ import annotations

import hashlib
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

#: Root holding one directory per packaged skill.
SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skill"

#: The CLI this documentation drives — used in the AGENTS.md pointer text.
CLI_NAME = "scopus-for-dobby"


@dataclass(frozen=True)
class Skill:
    """One packaged skill directory."""

    name: str
    #: One line describing what it teaches, for `skill list` and AGENTS.md.
    summary: str

    @property
    def src(self) -> Path:
        return SKILLS_ROOT / self.name

    @property
    def mark_begin(self) -> str:
        return f"<!-- BEGIN {self.name} skill -->"

    @property
    def mark_end(self) -> str:
        return f"<!-- END {self.name} skill -->"


SKILLS: dict[str, Skill] = {
    "scopus-for-dobby": Skill(
        name="scopus-for-dobby",
        summary=(
            "Driving the CLI: Scopus query syntax, the stateful library model, "
            "collections and tags, OpenAlex enrichment, and export."
        ),
    ),
    "paper-fulltext": Skill(
        name="paper-fulltext",
        summary=(
            "Reading the article itself: when the body is worth fetching, the "
            "markdown bundle it lands in, and the Article Retrieval quota."
        ),
    ),
    "citation-analysis": Skill(
        name="citation-analysis",
        summary=(
            "Reading a citation graph: what a search found, what it missed, and "
            "what to read next — plus which metrics the graph's shape supports."
        ),
    ),
    "corpus-profiling": Skill(
        name="corpus-profiling",
        summary=(
            "Characterising a set of papers too large to read: topic and keyword "
            "profiles, distinctive terms, coverage caveats."
        ),
    ),
}

#: Back-compat for callers that assumed a single skill.
SKILL_NAME = "scopus-for-dobby"


def resolve_skill(name: str) -> Skill:
    try:
        return SKILLS[name]
    except KeyError:
        known = ", ".join(sorted(SKILLS))
        raise SkillInstallError(f"Unknown skill: {name!r}. Known skills: {known}") from None


@dataclass(frozen=True)
class Target:
    """One agent's on-disk convention."""

    name: str
    label: str
    #: Directory holding skill dirs, relative to the scope root.
    skills_subdir: str
    #: Scopes this target supports, first entry is the default.
    scopes: tuple[str, ...]
    #: Append a pointer section to AGENTS.md alongside the skill directory.
    #: Only meaningful for agents without their own skill discovery.
    writes_agents_md: bool = False
    #: Why no pointer file is written — shown to the user, so the silence
    #: reads as a decision rather than an omission.
    discovery_note: str = ""


TARGETS: dict[str, Target] = {
    "claude": Target(
        name="claude",
        label="Claude Code",
        skills_subdir=".claude/skills",
        scopes=("global", "project"),
        discovery_note="Claude Code auto-discovers skills; no CLAUDE.md edit needed.",
    ),
    "agents": Target(
        name="agents",
        label="AGENTS.md-compatible agents (Codex, Cursor, Zed, Aider, …)",
        skills_subdir=".agents/skills",
        scopes=("project", "global"),
        writes_agents_md=True,
        discovery_note="These agents have no skill auto-discovery — AGENTS.md is what points at it.",
    ),
}

#: Accepted spellings for each scope. ``user`` is what Claude Code's own docs
#: call the home-directory scope; ``global`` is what most CLIs call it.
SCOPE_ALIASES = {"global": "global", "user": "global", "project": "project", "local": "project"}


class SkillInstallError(RuntimeError):
    """Raised when the skill cannot be installed."""


def normalize_scope(scope: str) -> str:
    try:
        return SCOPE_ALIASES[scope]
    except KeyError:
        raise SkillInstallError(
            f"Unknown scope: {scope!r} (expected 'global' or 'project')"
        ) from None


def scope_root(scope: str, project_dir: Path | None = None) -> Path:
    scope = normalize_scope(scope)
    if scope == "global":
        return Path.home()
    return (project_dir or Path.cwd()).resolve()


def resolve_target(agent: str) -> Target:
    try:
        return TARGETS[agent]
    except KeyError:
        known = ", ".join(sorted(TARGETS))
        raise SkillInstallError(f"Unknown agent: {agent!r}. Known agents: {known}") from None


def destination(
    agent: str, scope: str, project_dir: Path | None = None, skill: str = SKILL_NAME
) -> Path:
    """Where a skill directory would land for this agent and scope."""
    target = resolve_target(agent)
    scope = normalize_scope(scope)
    if scope not in target.scopes:
        raise SkillInstallError(
            f"{target.label} does not support scope {scope!r} "
            f"(supported: {', '.join(target.scopes)})"
        )
    return scope_root(scope, project_dir) / target.skills_subdir / resolve_skill(skill).name


#: Directories under a skill source that are development-only and never
#: installed into an agent directory.
_NOT_PAYLOAD = {"evals", "__pycache__"}

#: Files that are never payload wherever they turn up. The Finder scatters
#: `.DS_Store` through installed directories, and treating one as content
#: would report an otherwise pristine install as stale.
_NOT_PAYLOAD_FILES = {".DS_Store"}


def _is_payload(rel: Path) -> bool:
    """Whether a path relative to a skill root counts as installed content."""
    return (
        not (_NOT_PAYLOAD & set(rel.parts))
        and rel.name not in _NOT_PAYLOAD_FILES
        and rel.suffix != ".pyc"
    )


def _tree_files(root: Path) -> list[str]:
    """Payload files under ``root``, relative to it, sorted."""
    if not root.is_dir():
        return []
    return sorted(
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and _is_payload(p.relative_to(root))
    )


def payload_files(skill: str = SKILL_NAME) -> list[str]:
    """The files an install would actually place, relative to the source."""
    return _tree_files(resolve_skill(skill).src)


def installed_files(path: Path) -> list[str]:
    """The payload files present in an installed skill directory.

    Filtered exactly like the source side, so the two lists are comparable:
    anything the install would have skipped is skipped here too.
    """
    return _tree_files(path)


def skill_content_hash(skill: str | Skill, root: Path | None = None) -> str:
    """SHA-256 over a skill's payload — sorted relative paths plus file bytes.

    Both sides of a staleness check run through this one function: the
    packaged source (``root`` omitted) and an installed copy (``root`` set to
    the installed directory), so "identical content" means the same thing on
    either side. Paths are hashed alongside the bytes, which makes a rename or
    a stray extra file a change rather than a silent match.
    """
    obj = skill if isinstance(skill, Skill) else resolve_skill(skill)
    tree = obj.src if root is None else root
    digest = hashlib.sha256()
    for rel in _tree_files(tree):
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update((tree / rel).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_skill(src: Path, dest: Path) -> list[str]:
    """Copy a packaged skill to ``dest``, replacing it. Returns file names."""
    if not (src / "SKILL.md").is_file():
        raise SkillInstallError(
            f"Packaged skill is missing or incomplete at {src}. Reinstall the package."
        )
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Skip caches, editor cruft, and `evals/` — the eval cases live beside the
    # skill because they test it, but they are development material and the
    # wheel does not ship them. Excluding them here keeps an editable install
    # and a wheel install producing byte-identical agent directories.
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "evals"),
    )
    return sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())


def agents_md_section(skill: Skill, skill_dir: Path, root: Path) -> str:
    """The pointer block written into AGENTS.md for one skill."""
    try:
        shown = skill_dir.relative_to(root)
    except ValueError:  # pragma: no cover — global install from elsewhere
        shown = skill_dir
    return (
        f"{skill.mark_begin}\n"
        f"## {skill.name}\n\n"
        f"{skill.summary}\n\n"
        f"**Before using it, read `{shown}/SKILL.md`.** Deeper references are in "
        f"`{shown}/references/`.\n\n"
        f"Check the CLI is available first: `{CLI_NAME} --help`\n"
        f"{skill.mark_end}"
    )


def update_agents_md(path: Path, section: str, skill: Skill) -> str:
    """Insert or replace one skill's section in AGENTS.md.

    Returns ``"created"``, ``"updated"``, or ``"unchanged"``. Sections are
    delimited per skill, so several coexist and each refreshes in place.
    Content outside the markers is never touched — the file is the user's.
    """
    mark_begin, mark_end = skill.mark_begin, skill.mark_end
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# AGENTS.md\n\n{section}\n")
        return "created"

    original = path.read_text()
    if mark_begin in original and mark_end in original:
        head, rest = original.split(mark_begin, 1)
        _, tail = rest.split(mark_end, 1)
        updated = f"{head}{section}{tail}"
    else:
        sep = "" if original.endswith("\n\n") else ("\n" if original.endswith("\n") else "\n\n")
        updated = f"{original}{sep}{section}\n"

    if updated == original:
        return "unchanged"
    path.write_text(updated)
    return "updated"


def has_agents_md_section(path: Path, skill: Skill) -> bool:
    """Whether AGENTS.md currently carries this skill's marker block."""
    if not path.is_file():
        return False
    body = path.read_text()
    return skill.mark_begin in body and skill.mark_end in body


def _rejoin(head: str, tail: str) -> str:
    """Splice the text around a removed block back together.

    Only the run of newlines at the seam is normalised — to one blank line,
    the same separation an install writes. Every other byte on both sides is
    the user's and is passed through untouched, so repeated
    install/uninstall cycles neither eat prose nor stack blank lines.
    """
    head, tail = head.rstrip("\n"), tail.lstrip("\n")
    if not head:
        return tail
    if not tail:
        return f"{head}\n"
    return f"{head}\n\n{tail}"


def remove_agents_md_section(path: Path, skill: Skill) -> str:
    """Remove one skill's section from AGENTS.md.

    Returns ``"removed"``, ``"absent"`` (file exists, no such block) or
    ``"missing"`` (no file at all). The markers make this surgical: the block
    goes and nothing else does. The file itself is never deleted, even when
    the last block leaves only a heading behind — the CLI may have created it
    once, but what is in it now is the user's.
    """
    if not path.exists():
        return "missing"
    original = path.read_text()
    if not (skill.mark_begin in original and skill.mark_end in original):
        return "absent"

    head, rest = original.split(skill.mark_begin, 1)
    _, tail = rest.split(skill.mark_end, 1)
    path.write_text(_rejoin(head, tail))
    return "removed"


def install(
    agent: str,
    *,
    scope: str | None = None,
    project_dir: Path | None = None,
    dest: Path | None = None,
    skills: list[str] | None = None,
    agents_md: bool = True,
    dry_run: bool = False,
) -> dict:
    """Install bundled skills for ``agent``. Defaults to all of them.

    ``dest`` overrides the computed destination entirely (and suppresses the
    AGENTS.md write, since there is no scope root to anchor it to).
    ``agents_md=False`` declines the pointer section for targets that use one.
    """
    target = resolve_target(agent)
    effective_scope = normalize_scope(scope) if scope else target.scopes[0]
    chosen = [resolve_skill(n) for n in (skills or list(SKILLS))]

    root = None if dest is not None else scope_root(effective_scope, project_dir)

    # AGENTS.md is a per-project convention: there is no agreed home-directory
    # equivalent, so a global install places the skills and stops there.
    wants_pointer = target.writes_agents_md and agents_md
    write_pointer = wants_pointer and root is not None and effective_scope == "project"

    if write_pointer:
        note = ""
    elif not target.writes_agents_md:
        note = target.discovery_note
    elif not agents_md:
        note = "AGENTS.md not written (declined)."
    elif effective_scope != "project":
        note = "AGENTS.md not written — it is a per-project file; use --project for one."
    else:  # pragma: no cover — custom dest
        note = "AGENTS.md not written (custom destination)."

    installed = []
    for skill in chosen:
        if dest is not None:
            skill_dir = Path(dest).expanduser().resolve() / skill.name
        else:
            skill_dir = destination(agent, effective_scope, project_dir, skill.name)

        entry = {"skill": skill.name, "path": str(skill_dir), "files": []}
        if dry_run:
            entry["files"] = payload_files(skill.name)
        else:
            entry["files"] = _copy_skill(skill.src, skill_dir)
            if write_pointer:
                entry["agents_md_status"] = update_agents_md(
                    root / "AGENTS.md",
                    agents_md_section(skill, skill_dir, root),
                    skill,
                )
        installed.append(entry)

    return {
        "agent": target.name,
        "label": target.label,
        "scope": effective_scope if dest is None else "custom",
        "dry_run": dry_run,
        "agents_md": str(root / "AGENTS.md") if write_pointer else None,
        "note": note,
        "skills": installed,
        # Flattened conveniences for humans and simple --json consumers.
        "paths": [e["path"] for e in installed],
        "files": sorted({f for e in installed for f in e["files"]}),
    }


def uninstall(
    agent: str,
    *,
    scope: str | None = None,
    project_dir: Path | None = None,
    dest: Path | None = None,
    skills: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Remove installed skills for ``agent``. Defaults to all of them.

    The option surface mirrors :func:`install` so the two are symmetric:
    whatever arguments put a skill somewhere take it back out again.

    Removing something that was never installed is reported as
    ``"not_installed"``, not raised: the caller asked for a state and that
    state already holds. Only the skill directory and this skill's AGENTS.md
    block are touched — nothing the CLI did not write is removed.
    """
    target = resolve_target(agent)
    effective_scope = normalize_scope(scope) if scope else target.scopes[0]
    chosen = [resolve_skill(n) for n in (skills or list(SKILLS))]
    root = None if dest is not None else scope_root(effective_scope, project_dir)

    # A pointer section is only ever written for a project-scope install, so
    # that is the only place there can be one to take back out.
    agents_md_path = (
        root / "AGENTS.md"
        if target.writes_agents_md and root is not None and effective_scope == "project"
        else None
    )

    removed = []
    for skill in chosen:
        if dest is not None:
            skill_dir = Path(dest).expanduser().resolve() / skill.name
        else:
            skill_dir = destination(agent, effective_scope, project_dir, skill.name)

        present = skill_dir.is_dir()
        entry = {
            "skill": skill.name,
            "path": str(skill_dir),
            "files": installed_files(skill_dir),
            "status": ("would_remove" if dry_run else "removed") if present else "not_installed",
        }
        if present and not dry_run:
            shutil.rmtree(skill_dir)

        if agents_md_path is not None:
            if dry_run:
                entry["agents_md_status"] = (
                    "would_remove" if has_agents_md_section(agents_md_path, skill) else "absent"
                )
            else:
                entry["agents_md_status"] = remove_agents_md_section(agents_md_path, skill)
        removed.append(entry)

    return {
        "agent": target.name,
        "label": target.label,
        "scope": effective_scope if dest is None else "custom",
        "dry_run": dry_run,
        "agents_md": str(agents_md_path) if agents_md_path is not None else None,
        "skills": removed,
        # Flattened conveniences, matching `install`'s shape.
        "paths": [e["path"] for e in removed if e["status"] != "not_installed"],
        "removed": [e["skill"] for e in removed if e["status"] != "not_installed"],
    }


def _status_entry(target: Target, scope: str, skill: Skill, project_dir: Path | None) -> dict:
    """One agent × scope × skill row: installed, current or stale, and why."""
    path = destination(target.name, scope, project_dir, skill.name)
    packaged = payload_files(skill.name)
    entry = {
        "agent": target.name,
        "label": target.label,
        "scope": scope,
        "skill": skill.name,
        "path": str(path),
        "installed": path.is_dir(),
        "state": "not_installed",
        "packaged_hash": skill_content_hash(skill),
        "installed_hash": None,
        "packaged_files": len(packaged),
        "installed_files": 0,
        "missing_files": [],
        "extra_files": [],
        "modified_files": [],
        "agents_md": None,
    }

    if target.writes_agents_md and scope == "project":
        agents_md = scope_root(scope, project_dir) / "AGENTS.md"
        entry["agents_md"] = {
            "path": str(agents_md),
            "section": has_agents_md_section(agents_md, skill),
        }

    if not entry["installed"]:
        return entry

    found = installed_files(path)
    entry["installed_files"] = len(found)
    entry["installed_hash"] = skill_content_hash(skill, root=path)
    entry["state"] = "current" if entry["installed_hash"] == entry["packaged_hash"] else "stale"
    if entry["state"] == "stale":
        # Name the difference: "stale" on its own tells nobody what to look at.
        packaged_set, found_set = set(packaged), set(found)
        entry["missing_files"] = [f for f in packaged if f not in found_set]
        entry["extra_files"] = [f for f in found if f not in packaged_set]
        entry["modified_files"] = [
            f
            for f in packaged
            if f in found_set and (path / f).read_bytes() != (skill.src / f).read_bytes()
        ]
    return entry


def status(
    agent: str | None = None,
    *,
    scope: str | None = None,
    project_dir: Path | None = None,
    skills: list[str] | None = None,
) -> dict:
    """Where every packaged skill stands, per agent and scope.

    Staleness is the reason this exists. An installed copy silently drifts
    out of date on every upgrade the user does not re-run ``skill install``
    for, and a skill that documents behaviour the CLI no longer has is worse
    than none at all — the agent confidently follows it. Comparing content
    hashes surfaces that; the file lists say what changed.
    """
    targets = [resolve_target(agent)] if agent else list(TARGETS.values())
    chosen = [resolve_skill(n) for n in (skills or list(SKILLS))]
    wanted = normalize_scope(scope) if scope else None

    entries = []
    for target in targets:
        scopes = [s for s in target.scopes if wanted in (None, s)]
        if not scopes and agent:
            raise SkillInstallError(
                f"{target.label} does not support scope {wanted!r} "
                f"(supported: {', '.join(target.scopes)})"
            )
        for target_scope in scopes:
            for skill in chosen:
                entries.append(_status_entry(target, target_scope, skill, project_dir))

    states = Counter(e["state"] for e in entries)
    return {
        "project_dir": str((project_dir or Path.cwd()).resolve()),
        "scope": wanted,
        "entries": entries,
        "summary": {
            "installed": sum(1 for e in entries if e["installed"]),
            "current": states["current"],
            "stale": states["stale"],
            "not_installed": states["not_installed"],
        },
    }


def list_skills() -> list[dict]:
    """Every packaged skill, with whether its source is actually present."""
    return [
        {
            "skill": s.name,
            "summary": s.summary,
            "available": (s.src / "SKILL.md").is_file(),
            "files": len(payload_files(s.name)) if (s.src / "SKILL.md").is_file() else 0,
        }
        for s in SKILLS.values()
    ]


def list_targets(project_dir: Path | None = None) -> list[dict]:
    """Every target with the paths it would resolve to."""
    rows = []
    for target in TARGETS.values():
        rows.append(
            {
                "agent": target.name,
                "label": target.label,
                "default_scope": target.scopes[0],
                "scopes": list(target.scopes),
                "writes_agents_md": target.writes_agents_md,
                "discovery_note": target.discovery_note,
                "paths": {
                    s: str(
                        scope_root(s, project_dir) / target.skills_subdir
                    )
                    for s in target.scopes
                },
            }
        )
    return rows
