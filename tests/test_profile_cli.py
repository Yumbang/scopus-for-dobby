"""``profile`` at the CLI boundary.

The point of this command is that it never presents a vocabulary profile
without its denominator, so the tests care as much about the coverage line and
the low-coverage warning as about the counts themselves.
"""

import json

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import article_db as db_mod


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "articles.duckdb")
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    yield
    db_mod.close_cached_connections()


@pytest.fixture
def runner():
    state.json_output = False
    state.repl_mode = False
    yield CliRunner()
    state.json_output = False


def _entry(eid, *, title="A paper", date="2020-01-01", index_keywords=None, subject_areas=None):
    """A pre-normalized article — `add_entries` accepts these directly."""
    return {
        "eid": eid,
        "title": title,
        "first_author": "Tester",
        "journal": "J. Testing",
        "cover_date": date,
        "cited_by": 1,
        "index_keywords": index_keywords or [],
        "subject_areas": subject_areas or [],
    }


def _add(entries, *, collection=None, tags=None):
    db_mod.add_entries(entries, tags=tags, collection=collection)


def _enrich(eid, topics):
    db_mod.enrich_articles([{"eid": eid, "openalex_id": f"W{eid}", "topics": topics}])


@pytest.fixture
def corpus():
    """8 articles: 6 with topics, 2 bare. Ecology on 5, Remote Sensing on 4."""
    _add([_entry(f"e{i}", title=f"Canopy height mapping study {i}") for i in range(8)])
    for i in range(4):
        _enrich(f"e{i}", ["Ecology", "Remote Sensing"])
    _enrich("e4", ["Ecology"])
    _enrich("e5", ["Ecology", "Genomics"])
    return 8


class TestHumanOutput:
    def test_leads_with_coverage_then_profile(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile"])
        assert result.exit_code == 0, result.output
        out = result.output
        assert "Field coverage" in out
        assert "openalex_topics" in out
        assert out.index("Field coverage") < out.index("OpenAlex topics")
        assert "Ecology" in out
        assert "Remote Sensing" in out

    def test_reports_counts_and_shares(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile"])
        # Ecology is on 6 of the 6 articles carrying topics.
        assert "6/8" in result.output
        assert "100%" in result.output

    def test_empty_database(self, runner):
        result = runner.invoke(root_cli, ["profile"])
        assert result.exit_code == 0, result.output
        assert "No articles matched" in result.output

    def test_year_span(self, runner):
        _add([_entry("y1", date="2011-01-01"), _entry("y2", date="2024-06-01")])
        result = runner.invoke(root_cli, ["profile"])
        assert "2011-2024" in result.output

    def test_eids_scope(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile", "e0", "e1"])
        assert result.exit_code == 0, result.output
        assert "2 named article(s)" in result.output

    def test_unknown_eid_errors(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile", "nope"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()


class TestFieldSelection:
    def test_auto_announces_choice_and_coverage(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile"])
        assert "Auto-selected openalex_topics" in result.output
        assert "75% coverage" in result.output  # 6 of 8

    def test_auto_prefers_the_better_covered_field(self, runner):
        # Index keywords on 3 of 4; topics on only 1.
        _add([_entry(f"k{i}", index_keywords=["lidar", "canopy"]) for i in range(3)])
        _add([_entry("k3")])
        _enrich("k0", ["Ecology"])
        result = runner.invoke(root_cli, ["profile"])
        assert "Auto-selected index_keywords" in result.output
        assert "lidar" in result.output

    def test_auto_falls_back_to_title_terms(self, runner):
        _add([_entry(f"t{i}", title="Lidar canopy height retrieval") for i in range(3)])
        result = runner.invoke(root_cli, ["profile"])
        assert "No controlled vocabulary present" in result.output
        assert "Title words" in result.output
        assert "lidar" in result.output

    def test_explicit_field_is_not_second_guessed(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile", "--field", "subjects"])
        assert result.exit_code == 0, result.output
        assert "Auto-selected" not in result.output
        assert "No article carries subject_areas" in result.output

    def test_collection_scope(self, runner, corpus):
        _add([_entry("c1", title="Scoped paper")], collection="thesis")
        _enrich("c1", ["Hydrology"])
        result = runner.invoke(root_cli, ["profile", "--collection", "thesis"])
        assert "collection 'thesis'" in result.output
        assert "Hydrology" in result.output
        assert "Ecology" not in result.output

    def test_tag_scope(self, runner, corpus):
        _add([_entry("g1", title="Tagged paper")], tags=["ml"])
        _enrich("g1", ["Genomics"])
        result = runner.invoke(root_cli, ["profile", "--tag", "ml"])
        assert "tag 'ml'" in result.output
        assert "Genomics" in result.output


class TestCoverageWarning:
    def test_warns_when_most_articles_lack_the_field(self, runner):
        _add([_entry(f"p{i}") for i in range(10)])
        _enrich("p0", ["Ecology"])
        _enrich("p1", ["Ecology"])
        result = runner.invoke(root_cli, ["profile", "--field", "topics"])
        assert "Only 20% coverage" in result.output
        assert "describes 2 of 10 articles" in result.output

    def test_no_warning_when_coverage_is_good(self, runner):
        _add([_entry(f"p{i}") for i in range(4)])
        for i in range(4):
            _enrich(f"p{i}", ["Ecology"])
        result = runner.invoke(root_cli, ["profile", "--field", "topics"])
        assert "not the corpus" not in result.output
        assert "Only" not in result.output


class TestOptionalSections:
    def test_terms_flag(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile", "--terms"])
        assert "Title words" in result.output
        assert "Title bigrams" in result.output
        assert "canopy height" in result.output  # bigram survives the stopword filter
        assert "study" not in result.output.lower()  # ...but the noise word does not

    def test_co_occurrence_flag(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile", "--co-occurrence"])
        assert "Co-occurring labels" in result.output
        assert "Ecology" in result.output and "Remote Sensing" in result.output

    def test_sections_absent_by_default(self, runner, corpus):
        result = runner.invoke(root_cli, ["profile"])
        assert "Title bigrams" not in result.output
        assert "Co-occurring labels" not in result.output


class TestJsonOutput:
    def test_shape(self, runner, corpus):
        result = runner.invoke(root_cli, ["--json", "profile"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        assert data["articles"] == 8
        assert data["field"] == {
            "requested": "auto",
            "chosen": "openalex_topics",
            "coverage": 0.75,
            "note": "Auto-selected openalex_topics — 75% coverage",
        }
        assert data["coverage"]["fields"]["openalex_topics"] == {"count": 6, "share": 0.75}

        profile = data["profile"]
        assert profile["with_field"] == 6
        assert profile["labels"][0] == {"label": "Ecology", "count": 6, "share": 1.0}
        assert {"label": "Remote Sensing", "count": 4, "share": 0.6667} in profile["labels"]

        assert data["years"]["median"] == 2020
        assert "terms" not in data
        assert "co_occurrence" not in data

    def test_optional_sections(self, runner, corpus):
        result = runner.invoke(root_cli, ["--json", "profile", "--terms", "--co-occurrence"])
        data = json.loads(result.output)
        pairs = {(p["a"], p["b"]): p["count"] for p in data["co_occurrence"]["pairs"]}
        assert pairs[("Ecology", "Remote Sensing")] == 4
        assert data["terms"]["words"]["terms"][0]["term"] in {"canopy", "height", "mapping"}
        assert data["terms"]["bigrams"]["terms"][0]["count"] == 8

    def test_empty_database(self, runner):
        result = runner.invoke(root_cli, ["--json", "profile"])
        data = json.loads(result.output)
        assert data["articles"] == 0
        assert data["coverage"]["total"] == 0
        assert data["years"]["with_year"] == 0
        # Shape stays stable on an empty corpus — no key appears or vanishes.
        assert data["field"] == {
            "requested": "auto", "chosen": None, "coverage": 0.0, "note": None,
        }
        assert "profile" not in data

    def test_top_limits_entries(self, runner, corpus):
        result = runner.invoke(root_cli, ["--json", "profile", "--top", "1"])
        data = json.loads(result.output)
        assert len(data["profile"]["labels"]) == 1
