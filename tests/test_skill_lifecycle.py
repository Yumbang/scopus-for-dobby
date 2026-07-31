"""`scopus-for-dobby skill uninstall` / `skill status` — the other half of install.

Two things here are worth failing a build over. Uninstall edits a file the user
owns (AGENTS.md), so it must take out its own marker block and nothing else.
And status exists to catch drift: an installed skill silently stops matching the
packaged one on every upgrade the user does not re-run `skill install` for, and
a skill documenting removed behaviour is worse than no skill — the agent follows
it confidently.
"""

import json

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import skill as skill_mod

SKILL = skill_mod.SKILL_NAME
OTHER = "citation-analysis"


@pytest.fixture
def runner():
    state.json_output = False
    state.repl_mode = False
    yield CliRunner()
    state.json_output = False


@pytest.fixture
def home(monkeypatch, tmp_path):
    """An isolated home + project dir; never touch the real ones."""
    fake_home = tmp_path / "home"
    project = tmp_path / "project"
    fake_home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(skill_mod.Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.chdir(project)
    return fake_home, project


def _json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


class TestUninstall:
    def test_removes_the_installed_directory(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        dest = fake_home / ".claude/skills" / SKILL
        assert dest.is_dir()

        result = runner.invoke(root_cli, ["skill", "uninstall"])
        assert result.exit_code == 0, result.output
        assert not dest.exists()

    def test_second_uninstall_is_not_an_error(self, home, runner):
        """The caller asked for a state, and that state already holds."""
        runner.invoke(root_cli, ["skill", "install"])
        runner.invoke(root_cli, ["skill", "uninstall"])

        result = runner.invoke(root_cli, ["--json", "skill", "uninstall"])
        data = _json(result)
        assert {e["status"] for e in data["skills"]} == {"not_installed"}
        assert data["removed"] == []

    def test_uninstall_without_install_is_not_an_error(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "uninstall"])
        assert result.exit_code == 0, result.output
        assert "not installed" in result.output

    def test_skill_selector_leaves_the_others_installed(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        result = runner.invoke(root_cli, ["skill", "uninstall", "--skill", SKILL])
        assert result.exit_code == 0, result.output
        assert not (fake_home / ".claude/skills" / SKILL).exists()
        assert (fake_home / ".claude/skills" / OTHER / "SKILL.md").is_file()

    def test_project_scope_leaves_the_global_install_alone(self, home, runner):
        """Scope is the whole point of the flag: one must not reach the other."""
        fake_home, project = home
        runner.invoke(root_cli, ["skill", "install", "claude", "--global"])
        runner.invoke(root_cli, ["skill", "install", "claude", "--project"])

        runner.invoke(root_cli, ["skill", "uninstall", "claude", "--project"])
        assert not (project / ".claude/skills" / SKILL).exists()
        assert (fake_home / ".claude/skills" / SKILL / "SKILL.md").is_file()

    def test_custom_dir(self, home, runner, tmp_path):
        target = tmp_path / "elsewhere"
        runner.invoke(root_cli, ["skill", "install", "--dir", str(target)])
        result = runner.invoke(root_cli, ["skill", "uninstall", "--dir", str(target)])
        assert result.exit_code == 0, result.output
        assert not (target / SKILL).exists()

    def test_conflicting_scope_flags_rejected(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "uninstall", "--global", "--project"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_unknown_skill_is_rejected(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "uninstall", "--skill", "nope"])
        assert result.exit_code != 0
        assert "Unknown skill" in result.output

    def test_dry_run_writes_nothing(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        result = runner.invoke(root_cli, ["skill", "uninstall", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Would remove" in result.output
        for name in skill_mod.SKILLS:
            assert (fake_home / ".claude/skills" / name / "SKILL.md").is_file()

    def test_json_shape(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        data = _json(runner.invoke(root_cli, ["--json", "skill", "uninstall"]))
        assert data["agent"] == "claude"
        assert data["scope"] == "global"
        assert data["dry_run"] is False
        assert data["agents_md"] is None  # Claude never gets a pointer file
        assert set(data["removed"]) == set(skill_mod.SKILLS)
        entry = next(e for e in data["skills"] if e["skill"] == SKILL)
        assert entry["status"] == "removed"
        assert entry["path"] == str(fake_home / ".claude/skills" / SKILL)
        assert "SKILL.md" in entry["files"]

    def test_json_dry_run_is_distinguishable(self, home, runner):
        """A consumer must not mistake a rehearsal for the real thing."""
        runner.invoke(root_cli, ["skill", "install"])
        data = _json(runner.invoke(root_cli, ["--json", "skill", "uninstall", "--dry-run"]))
        assert data["dry_run"] is True
        assert {e["status"] for e in data["skills"]} == {"would_remove"}


class TestUninstallAgentsMd:
    """AGENTS.md is the user's file; only our own marker block may go."""

    HEAD = "# Team notes\n\nRead the runbook before deploying.\n"
    TAIL = "## Local conventions\n\nRun `make check` before pushing.\n"

    def _install_between_prose(self, runner, project):
        """Install both skills into an AGENTS.md that has prose on both sides."""
        path = project / "AGENTS.md"
        path.write_text(self.HEAD)
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        path.write_text(path.read_text() + "\n" + self.TAIL)
        return path

    def test_removes_only_the_named_skills_block(self, home, runner):
        _, project = home
        path = self._install_between_prose(runner, project)

        result = runner.invoke(
            root_cli, ["skill", "uninstall", "agents", "--project", "--skill", SKILL]
        )
        assert result.exit_code == 0, result.output
        body = path.read_text()
        assert f"BEGIN {SKILL} skill" not in body
        assert body.count(f"BEGIN {OTHER} skill") == 1
        assert body.count(f"END {OTHER} skill") == 1

    def test_surrounding_prose_survives_byte_for_byte(self, home, runner):
        _, project = home
        path = self._install_between_prose(runner, project)
        runner.invoke(root_cli, ["skill", "uninstall", "agents", "--project", "--skill", SKILL])

        body = path.read_text()
        assert body.startswith(self.HEAD)
        assert body.endswith(self.TAIL)

    def test_removing_every_block_keeps_the_prose(self, home, runner):
        """With the last block gone, what remains must be exactly the user's file."""
        _, project = home
        path = self._install_between_prose(runner, project)
        runner.invoke(root_cli, ["skill", "uninstall", "agents", "--project"])

        body = path.read_text()
        assert body.startswith(self.HEAD)
        assert body.endswith(self.TAIL)
        for name in skill_mod.SKILLS:
            assert f"BEGIN {name} skill" not in body

    def test_file_survives_even_when_only_a_heading_is_left(self, home, runner):
        """We may have created it, but we did not write what is in it now."""
        _, project = home
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        runner.invoke(root_cli, ["skill", "uninstall", "agents", "--project"])

        path = project / "AGENTS.md"
        assert path.is_file()
        assert path.read_text().strip() == "# AGENTS.md"

    def test_install_uninstall_cycles_do_not_stack_blank_lines(self, home, runner):
        _, project = home
        path = project / "AGENTS.md"
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        first = path.read_text()
        for _ in range(3):
            runner.invoke(root_cli, ["skill", "uninstall", "agents", "--project"])
            runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        assert path.read_text() == first

    def test_global_scope_never_looks_for_a_pointer(self, home, runner):
        """None is written at global scope, so none is taken away."""
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install", "agents", "--global"])
        data = _json(
            runner.invoke(root_cli, ["--json", "skill", "uninstall", "agents", "--global"])
        )
        assert data["agents_md"] is None
        assert not (fake_home / "AGENTS.md").exists()

    def test_dry_run_leaves_the_section_in_place(self, home, runner):
        _, project = home
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        before = (project / "AGENTS.md").read_text()
        data = _json(
            runner.invoke(
                root_cli, ["--json", "skill", "uninstall", "agents", "--project", "--dry-run"]
            )
        )
        assert {e["agents_md_status"] for e in data["skills"]} == {"would_remove"}
        assert (project / "AGENTS.md").read_text() == before

    def test_status_reports_when_the_pointer_is_gone(self, home, runner):
        """A skill dir with no AGENTS.md section is one those agents never find."""
        _, project = home
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        (project / "AGENTS.md").write_text("# AGENTS.md\n")

        data = _json(
            runner.invoke(root_cli, ["--json", "skill", "status", "agents", "--scope", "project"])
        )
        entry = next(e for e in data["entries"] if e["skill"] == SKILL)
        assert entry["installed"] is True
        assert entry["agents_md"]["section"] is False


class TestStatus:
    def test_fresh_install_is_current(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        data = _json(runner.invoke(root_cli, ["--json", "skill", "status", "claude"]))

        entry = next(e for e in data["entries"] if e["skill"] == SKILL and e["scope"] == "global")
        assert entry["installed"] is True
        assert entry["state"] == "current"
        assert entry["path"] == str(fake_home / ".claude/skills" / SKILL)
        assert entry["installed_hash"] == entry["packaged_hash"]
        assert entry["missing_files"] == entry["extra_files"] == entry["modified_files"] == []

    def test_empty_home_reports_not_installed(self, home, runner):
        data = _json(runner.invoke(root_cli, ["--json", "skill", "status"]))
        assert data["summary"]["installed"] == 0
        assert data["summary"]["current"] == 0
        assert all(e["state"] == "not_installed" for e in data["entries"])
        assert all(e["installed_hash"] is None for e in data["entries"])

    def test_empty_home_human_output(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "status"])
        assert result.exit_code == 0, result.output
        assert "not installed" in result.output
        assert "0 current" in result.output

    def test_edited_file_is_stale_and_named(self, home, runner):
        """The failure this catches: a copy that drifted and said nothing."""
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        edited = fake_home / ".claude/skills" / SKILL / "SKILL.md"
        edited.write_text(edited.read_text() + "\n\nSomething the package never said.\n")

        data = _json(runner.invoke(root_cli, ["--json", "skill", "status", "claude"]))
        entry = next(e for e in data["entries"] if e["skill"] == SKILL and e["scope"] == "global")
        assert entry["state"] == "stale"
        assert entry["installed_hash"] != entry["packaged_hash"]
        assert entry["modified_files"] == ["SKILL.md"]
        assert entry["missing_files"] == entry["extra_files"] == []

    def test_deleted_file_is_reported_as_missing(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        reference = sorted((fake_home / ".claude/skills" / SKILL / "references").glob("*.md"))[0]
        reference.unlink()

        data = _json(runner.invoke(root_cli, ["--json", "skill", "status", "claude"]))
        entry = next(e for e in data["entries"] if e["skill"] == SKILL and e["scope"] == "global")
        assert entry["state"] == "stale"
        assert entry["missing_files"] == [f"references/{reference.name}"]

    def test_leftover_file_is_reported_as_extra(self, home, runner):
        """This is the shape of an upgrade that dropped a reference file."""
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        (fake_home / ".claude/skills" / SKILL / "references" / "from-an-old-release.md").write_text(
            "documents a flag that no longer exists"
        )

        data = _json(runner.invoke(root_cli, ["--json", "skill", "status", "claude"]))
        entry = next(e for e in data["entries"] if e["skill"] == SKILL and e["scope"] == "global")
        assert entry["state"] == "stale"
        assert entry["extra_files"] == ["references/from-an-old-release.md"]

    def test_stale_is_visible_in_human_output(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        edited = fake_home / ".claude/skills" / SKILL / "SKILL.md"
        edited.write_text("replaced wholesale")

        result = runner.invoke(root_cli, ["skill", "status", "claude"])
        assert result.exit_code == 0, result.output
        assert "STALE" in result.output
        assert "modified: SKILL.md" in result.output
        assert "1 stale" in result.output

    def test_reinstall_makes_it_current_again(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        edited = fake_home / ".claude/skills" / SKILL / "SKILL.md"
        edited.write_text("stale")
        runner.invoke(root_cli, ["skill", "install"])

        data = _json(runner.invoke(root_cli, ["--json", "skill", "status", "claude"]))
        assert data["summary"]["stale"] == 0

    def test_covers_every_agent_scope_and_skill(self, home, runner):
        data = _json(runner.invoke(root_cli, ["--json", "skill", "status"]))
        expected = {
            (t.name, scope, skill)
            for t in skill_mod.TARGETS.values()
            for scope in t.scopes
            for skill in skill_mod.SKILLS
        }
        assert {(e["agent"], e["scope"], e["skill"]) for e in data["entries"]} == expected

    def test_scope_filter(self, home, runner):
        data = _json(runner.invoke(root_cli, ["--json", "skill", "status", "--scope", "project"]))
        assert {e["scope"] for e in data["entries"]} == {"project"}

    def test_scope_alias(self, home, runner):
        data = _json(runner.invoke(root_cli, ["--json", "skill", "status", "--scope", "user"]))
        assert {e["scope"] for e in data["entries"]} == {"global"}

    def test_unknown_agent_is_rejected(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "status", "emacs-doctor"])
        assert result.exit_code != 0
        assert "Unknown agent" in result.output

    def test_uninstall_returns_status_to_not_installed(self, home, runner):
        runner.invoke(root_cli, ["skill", "install"])
        runner.invoke(root_cli, ["skill", "uninstall"])
        data = _json(runner.invoke(root_cli, ["--json", "skill", "status", "claude"]))
        assert data["summary"]["installed"] == 0


class TestContentHash:
    def test_install_reproduces_the_packaged_hash(self, home, runner):
        """The comparison only means anything if a clean install matches."""
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        installed = fake_home / ".claude/skills" / SKILL
        assert skill_mod.skill_content_hash(SKILL, root=installed) == skill_mod.skill_content_hash(
            SKILL
        )

    def test_one_changed_byte_changes_the_hash(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        installed = fake_home / ".claude/skills" / SKILL
        target = installed / "SKILL.md"
        target.write_text(target.read_text() + " ")
        assert skill_mod.skill_content_hash(SKILL, root=installed) != skill_mod.skill_content_hash(
            SKILL
        )

    def test_a_renamed_file_changes_the_hash(self, home, runner):
        """Same bytes, different layout — content alone would miss this."""
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        installed = fake_home / ".claude/skills" / SKILL
        reference = sorted((installed / "references").glob("*.md"))[0]
        reference.rename(reference.with_name("renamed.md"))
        assert skill_mod.skill_content_hash(SKILL, root=installed) != skill_mod.skill_content_hash(
            SKILL
        )

    def test_finder_droppings_are_not_content(self, home, runner):
        """A .DS_Store beside the skill must not read as a stale install."""
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        installed = fake_home / ".claude/skills" / SKILL
        (installed / ".DS_Store").write_bytes(b"\x00\x01")
        assert skill_mod.skill_content_hash(SKILL, root=installed) == skill_mod.skill_content_hash(
            SKILL
        )

    def test_missing_directory_hashes_to_the_empty_tree(self, home):
        fake_home, _ = home
        empty = skill_mod.skill_content_hash(SKILL, root=fake_home / "nowhere")
        assert empty != skill_mod.skill_content_hash(SKILL)
