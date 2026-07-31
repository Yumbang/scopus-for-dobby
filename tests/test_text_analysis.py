"""Corpus profiling maths.

Every article here is hand-built so each expected count is verifiable by
reading the fixture. The interesting cases are the degenerate ones: an empty
corpus, articles missing the field entirely, and vocabulary values arriving as
JSON strings instead of lists (which is what the daemon and older rows hand
back). None of those may raise.
"""

import pytest

from scopus_for_dobby.core import text_analysis as ta


def _art(eid, **kw):
    """An article dict with only what a test cares about set."""
    return {"eid": eid, **kw}


# ── Label extraction ─────────────────────────────────────────────────────────


class TestLabels:
    def test_list_of_strings(self):
        art = _art("a", openalex_topics=["Ecology", "Remote Sensing"])
        assert ta.labels(art, "openalex_topics") == ["Ecology", "Remote Sensing"]

    def test_json_string_matches_list(self):
        as_json = _art("a", openalex_topics='["Ecology", "Remote Sensing"]')
        as_list = _art("b", openalex_topics=["Ecology", "Remote Sensing"])
        assert ta.labels(as_json, "openalex_topics") == ta.labels(as_list, "openalex_topics")

    def test_dicts_use_name_key(self):
        art = _art("a", subject_areas=[{"name": "Environmental Science", "abbrev": "ENVI"}])
        assert ta.labels(art, "subject_areas") == ["Environmental Science"]

    def test_free_text_keywords_split_on_pipes(self):
        art = _art("a", keywords="lidar | canopy height ; biomass")
        assert ta.labels(art, "keywords") == ["lidar", "canopy height", "biomass"]

    def test_missing_and_empty_fields(self):
        assert ta.labels(_art("a"), "openalex_topics") == []
        assert ta.labels(_art("a", openalex_topics=[]), "openalex_topics") == []
        assert ta.labels(_art("a", openalex_topics="[]"), "openalex_topics") == []
        assert ta.labels(_art("a", openalex_topics=""), "openalex_topics") == []
        assert ta.labels(_art("a", openalex_topics=None), "openalex_topics") == []

    def test_duplicates_within_an_article_collapse(self):
        art = _art("a", openalex_topics=["Ecology", "ecology", " Ecology "])
        assert ta.labels(art, "openalex_topics") == ["Ecology"]

    def test_malformed_json_string_is_not_fatal(self):
        art = _art("a", openalex_topics='["Ecology"')
        assert ta.labels(art, "openalex_topics") == ['["Ecology"']


# ── vocabulary_profile ───────────────────────────────────────────────────────


class TestVocabularyProfile:
    def test_empty_corpus(self):
        result = ta.vocabulary_profile([], field="openalex_topics")
        assert result["total"] == 0
        assert result["with_field"] == 0
        assert result["coverage"] == 0.0
        assert result["labels"] == []

    def test_articles_without_the_field(self):
        result = ta.vocabulary_profile([_art("a"), _art("b")], field="openalex_topics")
        assert result["with_field"] == 0
        assert result["labels"] == []

    def test_counts_and_share_use_the_covered_denominator(self):
        # 4 articles, 2 carry topics: Ecology on both, Genomics on one.
        articles = [
            _art("a", openalex_topics=["Ecology", "Genomics"]),
            _art("b", openalex_topics=["Ecology"]),
            _art("c"),
            _art("d", openalex_topics=[]),
        ]
        result = ta.vocabulary_profile(articles, field="openalex_topics")
        assert result["total"] == 4
        assert result["with_field"] == 2
        assert result["coverage"] == 0.5
        assert result["distinct"] == 2
        assert result["labels"][0] == {"label": "Ecology", "count": 2, "share": 1.0}
        assert result["labels"][1] == {"label": "Genomics", "count": 1, "share": 0.5}

    def test_case_insensitive_grouping_keeps_first_spelling(self):
        articles = [
            _art("a", index_keywords=["Remote sensing"]),
            _art("b", index_keywords=["REMOTE SENSING"]),
        ]
        result = ta.vocabulary_profile(articles, field="index_keywords")
        assert result["distinct"] == 1
        assert result["labels"][0]["label"] == "Remote sensing"
        assert result["labels"][0]["count"] == 2

    def test_top_truncates(self):
        articles = [_art(str(i), openalex_topics=[f"T{i}"]) for i in range(10)]
        assert len(ta.vocabulary_profile(articles, field="openalex_topics", top=3)["labels"]) == 3


# ── coverage / best_field ────────────────────────────────────────────────────


class TestCoverage:
    @pytest.fixture
    def corpus(self):
        return [
            _art("a", title="One", openalex_topics=["Ecology"], index_keywords=["lidar"]),
            _art("b", title="Two", openalex_topics=["Genomics"]),
            _art("c", title="Three"),
            _art("d"),
        ]

    def test_empty_corpus_reports_zeroes(self):
        result = ta.coverage([])
        assert result["total"] == 0
        assert all(f["count"] == 0 and f["share"] == 0.0 for f in result["fields"].values())

    def test_counts_per_field(self, corpus):
        fields = ta.coverage(corpus)["fields"]
        assert fields["openalex_topics"] == {"count": 2, "share": 0.5}
        assert fields["index_keywords"] == {"count": 1, "share": 0.25}
        assert fields["subject_areas"] == {"count": 0, "share": 0.0}
        assert fields["title"]["count"] == 3

    def test_best_field_picks_the_richest(self, corpus):
        pick = ta.best_field(corpus)
        assert pick["field"] == "openalex_topics"
        assert pick["coverage"] == 0.5

    def test_best_field_breaks_ties_by_preference_order(self):
        articles = [_art("a", openalex_topics=["Ecology"], index_keywords=["lidar"])]
        assert ta.best_field(articles)["field"] == "openalex_topics"

    def test_best_field_none_when_no_vocabulary(self):
        pick = ta.best_field([_art("a", title="Only a title")])
        assert pick["field"] is None
        assert pick["coverage"] == 0.0

    def test_best_field_on_empty_corpus(self):
        assert ta.best_field([])["field"] is None


# ── distinctive_terms ────────────────────────────────────────────────────────


class TestDistinctiveTerms:
    @pytest.fixture
    def groups(self):
        # "Ecology" is on every article in both groups — maximally frequent,
        # zero information. The group-specific labels are what we want ranked.
        return {
            "field": [_art(f"f{i}", openalex_topics=["Ecology", "Remote Sensing"])
                      for i in range(4)],
            "lab": [_art(f"l{i}", openalex_topics=["Ecology", "Genomics"]) for i in range(4)],
        }

    def test_empty_input(self):
        assert ta.distinctive_terms({}) == {"field": "openalex_topics", "total": 0, "groups": []}

    def test_group_with_no_articles(self):
        result = ta.distinctive_terms({"empty": []})
        assert result["groups"][0]["articles"] == 0
        assert result["groups"][0]["terms"] == []

    def test_distinguishing_term_outranks_ubiquitous_one(self, groups):
        result = ta.distinctive_terms(groups)
        by_group = {g["group"]: g for g in result["groups"]}

        assert by_group["field"]["terms"][0]["term"] == "Remote Sensing"
        assert by_group["lab"]["terms"][0]["term"] == "Genomics"

        scores = {t["term"]: t["score"] for t in by_group["field"]["terms"]}
        # Same raw count (4/4) as the distinctive term, but present everywhere.
        assert scores["Ecology"] == pytest.approx(0.0, abs=1e-9)
        assert scores["Remote Sensing"] > scores["Ecology"]

    def test_prevalence_weighting_beats_a_lone_exotic_term(self):
        # "Hydrology" is unique to group A but on one article of twenty;
        # "Remote Sensing" is on most of A and none of B. Ratio alone would
        # rank the singleton first, prevalence weighting must not.
        a = [_art(f"a{i}", openalex_topics=["Remote Sensing"]) for i in range(9)]
        a.append(_art("a9", openalex_topics=["Hydrology"]))
        b = [_art(f"b{i}", openalex_topics=["Genomics"]) for i in range(10)]
        result = ta.distinctive_terms({"a": a, "b": b})
        terms = [t["term"] for t in result["groups"][0]["terms"]]
        assert terms[0] == "Remote Sensing"
        assert terms.index("Hydrology") > 0

    def test_min_count_drops_singletons(self):
        a = [_art(f"a{i}", openalex_topics=["Remote Sensing"]) for i in range(3)]
        a.append(_art("a4", openalex_topics=["Hydrology"]))
        result = ta.distinctive_terms({"a": a, "b": [_art("b", openalex_topics=["Genomics"])]},
                                      min_count=2)
        assert [t["term"] for t in result["groups"][0]["terms"]] == ["Remote Sensing"]

    def test_free_text_mode(self):
        groups = {
            "a": [_art(f"a{i}", title="Lidar canopy height retrieval") for i in range(3)],
            "b": [_art(f"b{i}", title="Genome assembly of conifers") for i in range(3)],
        }
        result = ta.distinctive_terms(groups, field=None)
        assert "lidar" in [t["term"] for t in result["groups"][0]["terms"]]

    def test_accepts_pairs_as_well_as_mapping(self, groups):
        as_pairs = ta.distinctive_terms(list(groups.items()))
        assert [g["group"] for g in as_pairs["groups"]] == ["field", "lab"]


# ── term_frequency ───────────────────────────────────────────────────────────


class TestTermFrequency:
    def test_empty_corpus(self):
        result = ta.term_frequency([])
        assert result["terms"] == []
        assert result["with_text"] == 0

    def test_articles_without_titles(self):
        assert ta.term_frequency([_art("a"), _art("b", title="")])["terms"] == []

    def test_stopwords_and_domain_noise_are_dropped(self):
        articles = [_art("a", title="A Study of Deep Learning Using a Novel Approach")]
        terms = [t["term"] for t in ta.term_frequency(articles)["terms"]]
        assert terms == ["deep", "learning"]

    def test_custom_stopwords_replace_the_default_list(self):
        articles = [_art("a", title="Deep learning study")]
        terms = [t["term"] for t in ta.term_frequency(articles, stopwords=["deep"])["terms"]]
        assert terms == ["learning", "study"]

    def test_min_length(self):
        articles = [_art("a", title="CNN and RNN for canopy mapping")]
        terms = [t["term"] for t in ta.term_frequency(articles, min_length=4)["terms"]]
        assert "cnn" not in terms
        assert "canopy" in terms

    def test_repeats_within_one_article_count_once(self):
        articles = [_art("a", title="Canopy canopy canopy height")]
        counts = {t["term"]: t["count"] for t in ta.term_frequency(articles)["terms"]}
        assert counts["canopy"] == 1

    def test_bigrams(self):
        articles = [_art(str(i), title="Deep learning for climate models") for i in range(3)]
        result = ta.term_frequency(articles, ngram=2)
        assert [(t["term"], t["count"]) for t in result["terms"]] == [("deep learning", 3)]

    def test_bigrams_do_not_bridge_stopwords(self):
        # "canopy" and "biomass" are adjacent only after "of" is removed.
        articles = [_art("a", title="Canopy of biomass")]
        terms = [t["term"] for t in ta.term_frequency(articles, ngram=2)["terms"]]
        assert "canopy biomass" not in terms

    def test_multiple_fields(self):
        articles = [_art("a", title="Canopy height", abstract="Lidar retrieval of canopy")]
        counts = {
            t["term"]: t["count"]
            for t in ta.term_frequency(articles, fields=("title", "abstract"))["terms"]
        }
        assert counts["lidar"] == 1
        assert counts["canopy"] == 1  # counted once despite appearing in both fields


# ── co_occurrence ────────────────────────────────────────────────────────────


class TestCoOccurrence:
    def test_empty_corpus(self):
        result = ta.co_occurrence([])
        assert result["pairs"] == []
        assert result["distinct_pairs"] == 0

    def test_missing_field(self):
        assert ta.co_occurrence([_art("a"), _art("b")])["pairs"] == []

    def test_single_label_articles_produce_no_pairs(self):
        assert ta.co_occurrence([_art("a", openalex_topics=["Ecology"])])["pairs"] == []

    def test_pair_counts(self):
        articles = [
            _art("a", openalex_topics=["Ecology", "Genomics"]),
            _art("b", openalex_topics=["Genomics", "Ecology"]),  # order must not matter
            _art("c", openalex_topics=["Ecology", "Hydrology"]),
        ]
        result = ta.co_occurrence(articles, min_count=1)
        pairs = {(p["a"], p["b"]): p["count"] for p in result["pairs"]}
        assert pairs == {("Ecology", "Genomics"): 2, ("Ecology", "Hydrology"): 1}

    def test_min_count_filters(self):
        articles = [
            _art("a", openalex_topics=["Ecology", "Genomics"]),
            _art("b", openalex_topics=["Ecology", "Genomics"]),
            _art("c", openalex_topics=["Ecology", "Hydrology"]),
        ]
        result = ta.co_occurrence(articles, min_count=2)
        assert [(p["a"], p["b"], p["count"]) for p in result["pairs"]] == [
            ("Ecology", "Genomics", 2)
        ]

    def test_jaccard(self):
        # Ecology on 3, Genomics on 2, together on 2 -> 2 / (3 + 2 - 2).
        articles = [
            _art("a", openalex_topics=["Ecology", "Genomics"]),
            _art("b", openalex_topics=["Ecology", "Genomics"]),
            _art("c", openalex_topics=["Ecology"]),
        ]
        pair = ta.co_occurrence(articles, min_count=1)["pairs"][0]
        assert pair["jaccard"] == pytest.approx(2 / 3, abs=1e-4)


# ── year_distribution ────────────────────────────────────────────────────────


class TestYearDistribution:
    def test_empty_corpus(self):
        result = ta.year_distribution([])
        assert result == {
            "total": 0, "with_year": 0, "missing": 0, "years": {},
            "median": None, "earliest": None, "latest": None,
        }

    def test_parses_partial_and_full_dates(self):
        articles = [
            _art("a", cover_date="2019-01-01"),
            _art("b", cover_date="2019"),
            _art("c", cover_date="2020-05"),
        ]
        result = ta.year_distribution(articles)
        assert result["years"] == {2019: 2, 2020: 1}
        assert result["median"] == 2019
        assert (result["earliest"], result["latest"]) == (2019, 2020)

    def test_malformed_and_missing_dates_count_as_missing(self):
        articles = [
            _art("a", cover_date=""),
            _art("b", cover_date=None),
            _art("c", cover_date="n/a"),
            _art("d"),
            _art("e", cover_date="20199-01-01"),  # not a plausible year
            _art("f", cover_date="0999-01-01"),  # out of range
            _art("g", cover_date="2021-01-01"),
        ]
        result = ta.year_distribution(articles)
        assert result["with_year"] == 1
        assert result["missing"] == 6
        assert result["years"] == {2021: 1}

    def test_median_is_a_real_year_even_for_even_counts(self):
        articles = [_art("a", cover_date="2018"), _art("b", cover_date="2021")]
        assert ta.year_distribution(articles)["median"] == 2018


class TestAuthorKeywordsAreReachable:
    """Regression: an 84%-covered field was reported but unselectable.

    `keywords` (author-supplied, free text) sat in COVERAGE_FIELDS but not
    VOCAB_FIELDS, so `--field auto` could never choose it and no `--field`
    value mapped to it — while the coverage table advertised it at 84%.
    """

    def test_author_keywords_are_a_vocabulary(self):
        assert "keywords" in ta.VOCAB_FIELDS

    def test_auto_can_select_author_keywords(self):
        articles = [{"keywords": "membranes; fouling"} for _ in range(5)]
        assert ta.best_field(articles)["field"] == "keywords"

    def test_cli_exposes_an_explicit_name_for_each_field(self):
        from scopus_for_dobby.cli.profile import _FIELD_MAP

        assert _FIELD_MAP["author-keywords"] == "keywords"
        assert _FIELD_MAP["index-keywords"] == "index_keywords"
        # every vocabulary must be reachable by some explicit --field value
        assert set(ta.VOCAB_FIELDS) <= set(_FIELD_MAP.values())
