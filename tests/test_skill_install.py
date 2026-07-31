"""`scopus-for-dobby skill install` — the agent-integration installer.

The skill ships as package data so the CLI can plant it into whatever agent the
user runs, at global or project scope. Two failure modes are silent and so are
covered deliberately here: shipping a skill the packaging leaves out of the
wheel, and clobbering a user's existing AGENTS.md.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import skill as skill_mod

SKILL = skill_mod.SKILL_NAME
PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


class TestPackagedSkill:
    def test_every_registered_skill_is_present(self):
        """A registry entry without files fails only for real users."""
        for name, skill in skill_mod.SKILLS.items():
            assert (skill.src / "SKILL.md").is_file(), f"{name}: no packaged SKILL.md"

    def test_declared_as_package_data(self):
        """Without these globs the skills are absent from a built wheel.

        Read as text rather than parsed: `tomllib` is 3.11+, and the floor is
        3.10. The CI `skill-packaging` job proves the wheel end to end. The
        globs must be per-skill (`skill/*/...`) now that skills are nested.
        """
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
        assert "[tool.setuptools.package-data]" in pyproject
        assert "skill/*/SKILL.md" in pyproject
        assert "skill/*/references/*.md" in pyproject

    def test_references_are_shipped(self):
        for name, skill in skill_mod.SKILLS.items():
            assert list((skill.src / "references").glob("*.md")), f"{name}: no references"

    def test_evals_are_not_payload(self):
        """Eval cases live beside a skill but are development material.

        Excluded from both the wheel and the install, so an editable install
        and a wheel install produce identical agent directories.
        """
        for name in skill_mod.SKILLS:
            assert not any(f.startswith("evals") for f in skill_mod.payload_files(name))

    def test_unknown_skill_lists_known_ones(self):
        with pytest.raises(skill_mod.SkillInstallError, match="scopus-for-dobby"):
            skill_mod.resolve_skill("nope")


class TestTargets:
    def test_claude_paths(self, home):
        fake_home, project = home
        assert skill_mod.destination("claude", "global") == (
            fake_home / ".claude/skills" / SKILL
        )
        assert skill_mod.destination("claude", "project", project) == (
            project / ".claude/skills" / SKILL
        )

    def test_scope_aliases(self, home):
        assert skill_mod.normalize_scope("user") == "global"
        assert skill_mod.normalize_scope("local") == "project"

    def test_unknown_agent_lists_known_ones(self):
        with pytest.raises(skill_mod.SkillInstallError, match="claude"):
            skill_mod.resolve_target("emacs-doctor")

    def test_unknown_scope_rejected(self):
        with pytest.raises(skill_mod.SkillInstallError, match="global"):
            skill_mod.normalize_scope("somewhere")


class TestInstall:
    def test_global_install(self, home, runner):
        fake_home, _ = home
        result = runner.invoke(root_cli, ["skill", "install"])
        assert result.exit_code == 0, result.output
        dest = fake_home / ".claude/skills" / SKILL
        assert (dest / "SKILL.md").is_file()
        assert list((dest / "references").glob("*.md"))

    def test_project_install(self, home, runner):
        _, project = home
        result = runner.invoke(root_cli, ["skill", "install", "claude", "--project"])
        assert result.exit_code == 0, result.output
        assert (project / ".claude/skills" / SKILL / "SKILL.md").is_file()

    def test_claude_writes_no_pointer_file(self, home, runner):
        """Claude auto-discovers skills — nothing else should be touched."""
        _, project = home
        runner.invoke(root_cli, ["skill", "install", "claude", "--project"])
        assert not (project / "AGENTS.md").exists()
        assert not (project / "CLAUDE.md").exists()

    def test_dry_run_writes_nothing(self, home, runner):
        fake_home, _ = home
        result = runner.invoke(root_cli, ["skill", "install", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert not (fake_home / ".claude").exists()

    def test_reinstall_is_clean(self, home, runner):
        """A stale file from an old version must not survive an upgrade."""
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        stale = fake_home / ".claude/skills" / SKILL / "references" / "removed.md"
        stale.write_text("from an older release")
        runner.invoke(root_cli, ["skill", "install"])
        assert not stale.exists()

    def test_install_omits_evals(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        assert not (fake_home / ".claude/skills" / SKILL / "evals").exists()

    def test_custom_dir(self, home, runner, tmp_path):
        target = tmp_path / "elsewhere"
        result = runner.invoke(root_cli, ["skill", "install", "--dir", str(target)])
        assert result.exit_code == 0, result.output
        assert (target / SKILL / "SKILL.md").is_file()

    def test_conflicting_scope_flags_rejected(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "install", "--global", "--project"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_json_output(self, home, runner):
        result = runner.invoke(root_cli, ["--json", "skill", "install"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["agent"] == "claude"
        assert data["scope"] == "global"
        assert len(data["files"]) >= 2

    def test_installs_every_registered_skill_by_default(self, home, runner):
        fake_home, _ = home
        result = runner.invoke(root_cli, ["--json", "skill", "install"])
        data = json.loads(result.output)
        assert {e["skill"] for e in data["skills"]} == set(skill_mod.SKILLS)
        for entry in data["skills"]:
            assert (fake_home / ".claude/skills" / entry["skill"] / "SKILL.md").is_file()

    def test_skill_selector_installs_only_that_one(self, home, runner):
        result = runner.invoke(
            root_cli, ["--json", "skill", "install", "--skill", SKILL]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert [e["skill"] for e in data["skills"]] == [SKILL]

    def test_unknown_skill_is_rejected(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "install", "--skill", "nope"])
        assert result.exit_code != 0
        assert "Unknown skill" in result.output


class TestAgentsTarget:
    def test_project_install_writes_pointer(self, home, runner):
        _, project = home
        result = runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        assert result.exit_code == 0, result.output
        assert (project / ".agents/skills" / SKILL / "SKILL.md").is_file()
        body = (project / "AGENTS.md").read_text()
        assert SKILL in body
        assert ".agents/skills" in body

    def test_existing_agents_md_is_preserved(self, home, runner):
        _, project = home
        (project / "AGENTS.md").write_text("# Mine\n\nDo not clobber this line.\n")
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        body = (project / "AGENTS.md").read_text()
        assert "Do not clobber this line." in body
        assert body.startswith("# Mine")

    def test_repeated_installs_do_not_duplicate(self, home, runner):
        _, project = home
        for _ in range(3):
            runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        body = (project / "AGENTS.md").read_text()
        assert body.count("BEGIN scopus-for-dobby skill") == 1

    def test_section_is_refreshed_in_place(self, home, runner):
        _, project = home
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        path = project / "AGENTS.md"
        path.write_text(
            path.read_text().replace("Scopus search", "STALE TEXT")
        )
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        assert "STALE TEXT" not in path.read_text()

    def test_opt_out(self, home, runner):
        _, project = home
        result = runner.invoke(
            root_cli, ["skill", "install", "agents", "--project", "--no-agents-md"]
        )
        assert result.exit_code == 0, result.output
        assert (project / ".agents/skills" / SKILL / "SKILL.md").is_file()
        assert not (project / "AGENTS.md").exists()

    def test_global_scope_skips_pointer_and_says_why(self, home, runner):
        fake_home, _ = home
        result = runner.invoke(root_cli, ["skill", "install", "agents", "--global"])
        assert result.exit_code == 0, result.output
        assert (fake_home / ".agents/skills" / SKILL / "SKILL.md").is_file()
        assert not (fake_home / "AGENTS.md").exists()
        assert "per-project" in result.output


class TestListAndPath:
    def test_list_shows_every_target(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "list"])
        assert result.exit_code == 0, result.output
        for agent in skill_mod.TARGETS:
            assert agent in result.output

    def test_list_json(self, home, runner):
        result = runner.invoke(root_cli, ["--json", "skill", "list"])
        assert result.exit_code == 0, result.output
        targets = json.loads(result.output)["targets"]
        assert {t["agent"] for t in targets} == set(skill_mod.TARGETS)
        for t in targets:
            assert set(t["paths"]) == set(t["scopes"])

    def test_path_points_at_real_files(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "path"])
        assert result.exit_code == 0, result.output
        assert result.output.strip() == str(skill_mod.SKILLS_ROOT)

    def test_list_shows_every_skill(self, home, runner):
        result = runner.invoke(root_cli, ["skill", "list"])
        assert result.exit_code == 0, result.output
        for name in skill_mod.SKILLS:
            assert name in result.output


class TestMultipleSkills:
    """Two skills must coexist without trampling each other."""

    def test_each_skill_gets_its_own_directory(self, home, runner):
        fake_home, _ = home
        runner.invoke(root_cli, ["skill", "install"])
        for name in skill_mod.SKILLS:
            assert (fake_home / ".claude/skills" / name / "SKILL.md").is_file()

    def test_agents_md_holds_one_block_per_skill(self, home, runner):
        _, project = home
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        body = (project / "AGENTS.md").read_text()
        for name in skill_mod.SKILLS:
            assert body.count(f"BEGIN {name} skill") == 1

    def test_repeated_installs_do_not_duplicate_either_block(self, home, runner):
        _, project = home
        for _ in range(3):
            runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        body = (project / "AGENTS.md").read_text()
        for name in skill_mod.SKILLS:
            assert body.count(f"BEGIN {name} skill") == 1

    def test_installing_one_leaves_the_others_block_alone(self, home, runner):
        _, project = home
        runner.invoke(root_cli, ["skill", "install", "agents", "--project"])
        runner.invoke(
            root_cli,
            ["skill", "install", "agents", "--project", "--skill", SKILL],
        )
        body = (project / "AGENTS.md").read_text()
        # Re-installing one skill must not remove the other's section.
        for name in skill_mod.SKILLS:
            assert f"BEGIN {name} skill" in body

    def test_skill_descriptions_do_not_collide(self):
        """Overlapping trigger text makes the wrong skill load."""
        descriptions = {}
        for name, skill in skill_mod.SKILLS.items():
            front = (skill.src / "SKILL.md").read_text().split("---", 2)[1]
            line = next(x for x in front.splitlines() if x.startswith("description:"))
            descriptions[name] = line.lower()
        analysis = descriptions["citation-analysis"]
        # The analysis skill must not claim the search/export surface.
        assert "citation" in analysis
        assert "export references" not in analysis
