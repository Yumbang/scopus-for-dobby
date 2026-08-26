"""Elsevier full-text fetch: cache, entitlement isolation, batch sources."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from scopus_for_dobby.cli import cli as root_cli
from scopus_for_dobby.cli._state import state
from scopus_for_dobby.core import article_db as db_mod
from scopus_for_dobby.core import fulltext as ft
from scopus_for_dobby.utils.api_client import QuotaExceeded

XML_FULL = """\
<?xml version="1.0" encoding="UTF-8"?>
<full-text-retrieval-response xmlns:ce="http://www.elsevier.com/xml/common/dtd">
  <coredata><eid>2-s2.0-105035063878</eid></coredata>
  <originalText>
    <ce:article>
      <ce:head>
        <ce:author-group>
          <ce:author author-id="58041490500">
            <ce:given-name>Jeongwoo</ce:given-name>
            <ce:surname>Moon</ce:surname>
            <ce:cross-ref refid="fn1"/>
          </ce:author>
          <ce:author author-id="59227334200">
            <ce:given-name>Byeongchan</ce:given-name>
            <ce:surname>Yun</ce:surname>
            <ce:cross-ref refid="fn1"/>
          </ce:author>
          <ce:author author-id="56659062100">
            <ce:given-name>Kwanho</ce:given-name>
            <ce:surname>Jeong</ce:surname>
            <ce:cross-ref refid="cor1"/>
          </ce:author>
        </ce:author-group>
        <ce:footnote id="fn1">
          <ce:note-para>These authors contributed equally to this work.</ce:note-para>
        </ce:footnote>
        <ce:correspondence id="cor1">
          <ce:textfn>Corresponding authors.</ce:textfn>
        </ce:correspondence>
      </ce:head>
      <ce:sections>
        <ce:section>
          <ce:section-title>Introduction</ce:section-title>
          <ce:para>Reverse osmosis is the dominant membrane process.</ce:para>
        </ce:section>
      </ce:sections>
    </ce:article>
  </originalText>
</full-text-retrieval-response>
"""

# Carries the <ce:sections marker looks_like_fulltext keys on, but is cut off
# mid-document — what a dropped connection or a truncated proxy response looks like.
XML_TRUNCATED = XML_FULL[: XML_FULL.index("<ce:para>") + 40]

SAMPLE = {
    "dc:title": "Adaptive RL for CCRO",
    "dc:creator": "Moon J.",
    "prism:publicationName": "Water Research",
    "prism:coverDate": "2026-07-01",
    "prism:doi": "10.1016/j.watres.2026.125855",
    "eid": "2-s2.0-105035063878",
    "dc:identifier": "SCOPUS_ID:105035063878",
    "citedby-count": "1",
    "openaccess": "0",
    "prism:aggregationType": "Journal",
    "author": [
        {"authname": "Moon J.", "authid": "58041490500"},
        {"authname": "Yun B.", "authid": "59227334200"},
        {"authname": "Jeong K.", "authid": "56659062100"},
    ],
}

SAMPLE_CLOSED = {
    **SAMPLE,
    "eid": "2-s2.0-closed-1",
    "dc:identifier": "SCOPUS_ID:closed-1",
    "prism:doi": "10.1016/j.watres.2026.999999",
    "dc:title": "Closed paper",
}


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "articles.duckdb"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ft, "CONFIG_DIR", tmp_path)
    state.json_output = True
    state.repl_mode = True
    yield tmp_path
    db_mod.close_cached_connections()
    state.json_output = False
    state.repl_mode = False


def _fake_request(mapping):
    def request(endpoint, params=None, **kwargs):
        for key, payload in mapping.items():
            if key in endpoint:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        return {"status": 404, "text": "", "remaining": None, "reset": None}

    return request


class TestParseRoles:
    def test_equal_contrib_and_corresponding(self):
        roles = ft.parse_roles(XML_FULL)
        assert "58041490500" in roles["first_auids"]
        assert "59227334200" in roles["first_auids"]
        assert "56659062100" in roles["corr_auids"]
        assert "Introduction" in ft.parse_outline(XML_FULL)

    def test_abstract_only_is_not_fulltext(self):
        xml = "<full-text-retrieval-response><coredata/></full-text-retrieval-response>"
        assert not ft.looks_like_fulltext(xml)


class TestFetchOne:
    def test_writes_cache_and_parses(self, tmp_db, monkeypatch):
        monkeypatch.setattr(
            ft,
            "request_elsevier",
            _fake_request(
                {"125855": {"status": 200, "text": XML_FULL, "remaining": 49999, "reset": None}}
            ),
        )
        row = ft.fetch_one(
            {
                "eid": "2-s2.0-105035063878",
                "doi": "10.1016/j.watres.2026.125855",
                "in_db": True,
            },
            request=ft.request_elsevier,
        )
        assert row["status"] == ft.STATUS_FETCHED
        dest = Path(row["path"])
        assert dest.is_dir()
        xml = dest / "xml" / "article.xml"
        assert xml.is_file()
        assert xml.stat().st_mode & 0o777 == 0o600
        assert (dest / "manifest.json").is_file()
        assert (dest / "head.md").is_file()
        assert "58041490500" in row["roles"]["first_auids"]
        assert any("Introduction" in (s.get("title") or "") for s in (row["manifest"] or {}).get("sections") or [])

    def test_cache_hit_skips_http(self, tmp_db, monkeypatch):
        ft.write_source("2-s2.0-105035063878", XML_FULL)

        def boom(*a, **k):
            raise AssertionError("HTTP should not run on cache hit")

        row = ft.fetch_one(
            {"eid": "2-s2.0-105035063878", "doi": "10.1016/j.watres.2026.125855"},
            request=boom,
        )
        assert row["status"] == ft.STATUS_CACHED

    def test_403_is_not_entitled(self, tmp_db, monkeypatch):
        monkeypatch.setattr(
            ft,
            "request_elsevier",
            _fake_request({"999999": {"status": 403, "text": "", "remaining": 10, "reset": None}}),
        )
        row = ft.fetch_one(
            {
                "eid": "2-s2.0-closed-1",
                "doi": "10.1016/j.watres.2026.999999",
                "oa_url": "https://example.org/oa.pdf",
            },
            request=ft.request_elsevier,
        )
        assert row["status"] == ft.STATUS_NOT_ENTITLED
        assert "oa.pdf" in row["reason"]
        assert not ft.has_cache("2-s2.0-closed-1")


class TestFetchBatch:
    def test_entitlement_miss_does_not_abort(self, tmp_db, monkeypatch):
        mapping = {
            "125855": {"status": 200, "text": XML_FULL, "remaining": 10, "reset": None},
            "999999": {"status": 403, "text": "", "remaining": 9, "reset": None},
        }
        monkeypatch.setattr(ft, "request_elsevier", _fake_request(mapping))
        batch = ft.fetch_batch(
            [
                {"eid": "2-s2.0-105035063878", "doi": "10.1016/j.watres.2026.125855"},
                {"eid": "2-s2.0-closed-1", "doi": "10.1016/j.watres.2026.999999"},
            ],
            request=ft.request_elsevier,
        )
        assert batch["counts"][ft.STATUS_FETCHED] == 1
        assert batch["counts"][ft.STATUS_NOT_ENTITLED] == 1
        assert batch["total"] == 2

    def test_429_skips_remainder(self, tmp_db, monkeypatch):
        calls = {"n": 0}

        def request(endpoint, params=None, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise QuotaExceeded("Rate limit exceeded.", reset="1")
            raise AssertionError("must not continue after 429")

        batch = ft.fetch_batch(
            [
                {"eid": "2-s2.0-a", "doi": "10.1/a"},
                {"eid": "2-s2.0-b", "doi": "10.1/b"},
            ],
            request=request,
        )
        assert batch["counts"][ft.STATUS_SKIPPED_QUOTA] == 2
        assert calls["n"] == 1


class TestRecordRoles:
    def test_cofirst_flags(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.record_fulltext_fetch(
            SAMPLE["eid"],
            roles={
                "first_auids": ["58041490500", "59227334200"],
                "first_names": [],
                "corr_auids": ["56659062100"],
                "corr_names": [],
            },
        )
        moon = db_mod.get_author("58041490500")
        yun = db_mod.get_author("59227334200")
        jeong = db_mod.get_author("56659062100")
        assert moon["articles"][0]["is_first_author"] is True
        assert yun["articles"][0]["is_first_author"] is True
        assert jeong["articles"][0]["is_corresponding"] is True
        art = db_mod.get_article(SAMPLE["eid"])
        assert art["fulltext_fetched_at"]

    def test_xml_initials_match_scopus_name(self, tmp_db):
        """XML ``Cho K.`` must match Scopus ``Cho K.H.`` on the same paper."""
        entry = dict(SAMPLE)
        entry["author"] = list(SAMPLE["author"]) + [
            {"authname": "Cho K.H.", "authid": "26022315200"},
        ]
        db_mod.add_entries([entry])
        db_mod.record_fulltext_fetch(
            SAMPLE["eid"],
            roles={
                "first_auids": [],
                "first_names": ["Moon J.", "Yun B."],
                "corr_auids": [],
                "corr_names": ["Jeong K.", "Cho K."],
            },
        )
        cho = db_mod.get_author("26022315200")
        assert cho["articles"][0]["is_corresponding"] is True


class TestCliBatch:
    def test_pipeline_and_direct_eids(self, tmp_db, monkeypatch):
        db_mod.add_entries([SAMPLE, SAMPLE_CLOSED])
        db_mod.create_collection("ccro")
        db_mod.add_to_collection("ccro", [SAMPLE["eid"], SAMPLE_CLOSED["eid"]])

        mapping = {
            "125855": {"status": 200, "text": XML_FULL, "remaining": 10, "reset": None},
            "999999": {"status": 403, "text": "", "remaining": 9, "reset": None},
        }
        monkeypatch.setattr(ft, "request_elsevier", _fake_request(mapping))

        runner = CliRunner()
        result = runner.invoke(
            root_cli,
            ["--json", "fulltext", "--collection", "ccro"],
        )
        assert result.exit_code == 0, result.output
        import json

        body = json.loads(result.output)
        statuses = {i["eid"]: i["status"] for i in body["items"]}
        assert statuses[SAMPLE["eid"]] == "fetched"
        assert statuses[SAMPLE_CLOSED["eid"]] == "not_entitled"

    def test_direct_eid_argument(self, tmp_db, monkeypatch):
        db_mod.add_entries([SAMPLE])
        monkeypatch.setattr(
            ft,
            "request_elsevier",
            _fake_request(
                {"125855": {"status": 200, "text": XML_FULL, "remaining": 10, "reset": None}}
            ),
        )
        runner = CliRunner()
        result = runner.invoke(root_cli, ["--json", "fulltext", SAMPLE["eid"]])
        assert result.exit_code == 0, result.output
        import json

        body = json.loads(result.output)
        assert body["counts"]["fetched"] == 1

    def test_requires_a_source(self, tmp_db):
        state.repl_mode = False
        runner = CliRunner()
        result = runner.invoke(root_cli, ["fulltext"])
        assert result.exit_code != 0
        assert "Provide identifiers" in result.output or "Provide identifiers" in (result.stderr or "")


class TestMalformedPayload:
    """A payload the bundle writer cannot parse is one miss, not a dead run."""

    def test_batch_continues_and_nothing_is_cached(self, tmp_db, monkeypatch):
        batch = ft.fetch_batch(
            [
                {"eid": "2-s2.0-a", "doi": "10.1/aaa"},
                {"eid": "2-s2.0-b", "doi": "10.1/bbb"},
            ],
            request=_fake_request(
                {
                    "aaa": {"status": 200, "text": XML_TRUNCATED, "remaining": None, "reset": None},
                    "bbb": {"status": 200, "text": XML_FULL, "remaining": None, "reset": None},
                }
            ),
        )
        assert batch["total"] == 2
        assert batch["counts"][ft.STATUS_ERROR] == 1
        assert batch["counts"][ft.STATUS_FETCHED] == 1
        assert "malformed XML" in batch["items"][0]["reason"]
        # Caching it would raise on every later call for this paper, --force included.
        assert not ft.has_cache("2-s2.0-a")

    def test_corrupt_bundle_on_disk_self_heals(self, tmp_db):
        """A bundle poisoned by an earlier version must not raise forever."""
        ft.write_source("2-s2.0-a", XML_TRUNCATED)
        calls = {"n": 0}

        def request(endpoint, params=None, **kwargs):
            calls["n"] += 1
            return {"status": 200, "text": XML_FULL, "remaining": None, "reset": None}

        row = ft.fetch_one({"eid": "2-s2.0-a", "doi": "10.1/aaa"}, request=request)
        assert row["status"] == ft.STATUS_FETCHED
        assert calls["n"] == 1

    def test_one_item_raising_does_not_end_the_batch(self, tmp_db):
        def request(endpoint, params=None, **kwargs):
            if "aaa" in endpoint:
                raise ConnectionError("connection reset")
            return {"status": 200, "text": XML_FULL, "remaining": None, "reset": None}

        batch = ft.fetch_batch(
            [
                {"eid": "2-s2.0-a", "doi": "10.1/aaa"},
                {"eid": "2-s2.0-b", "doi": "10.1/bbb"},
            ],
            request=request,
        )
        assert batch["counts"][ft.STATUS_FETCHED] == 1
        assert "connection reset" in batch["items"][0]["reason"]


class TestDoiOnlyCache:
    """A paper outside the library is still cache-first."""

    def test_second_fetch_by_doi_spends_no_quota(self, tmp_db):
        calls = {"n": 0}

        def request(endpoint, params=None, **kwargs):
            calls["n"] += 1
            return {"status": 200, "text": XML_FULL, "remaining": None, "reset": None}

        # No eid: the bundle lands under the EID the payload carries, which a
        # DOI alone cannot reconstruct without the index.
        item = {"eid": "", "doi": "10.1016/j.watres.2026.125855", "in_db": False}
        first = ft.fetch_one(dict(item), request=request)
        assert first["eid"] == "2-s2.0-105035063878"

        second = ft.fetch_one(dict(item), request=request)
        assert second["status"] == ft.STATUS_CACHED
        assert second["eid"] == "2-s2.0-105035063878"
        assert calls["n"] == 1

    def test_index_rebuilds_from_manifests(self, tmp_db):
        """Bundles written before the index existed are still found."""

        def request(endpoint, params=None, **kwargs):
            return {"status": 200, "text": XML_FULL, "remaining": None, "reset": None}

        ft.fetch_one({"eid": "", "doi": "10.1016/j.watres.2026.125855"}, request=request)
        ft._index_path().unlink()

        row = ft.fetch_one(
            {"eid": "", "doi": "10.1016/j.watres.2026.125855"},
            request=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no http")),
        )
        assert row["status"] == ft.STATUS_CACHED


class TestRolesNeverClearFlags:
    """Full text raises role flags; it must never lower one already set."""

    def test_unmatched_names_leave_the_first_author_alone(self, tmp_db):
        db_mod.add_entries([SAMPLE])
        db_mod.record_fulltext_fetch(
            SAMPLE["eid"],
            roles={
                "first_auids": [],
                "first_names": ["Someone Unrelated"],
                "corr_auids": [],
                "corr_names": [],
            },
        )
        moon = db_mod.get_author("58041490500")
        assert moon["articles"][0]["is_first_author"] is True

    def test_given_name_first_matches_scopus_indexed_name(self, tmp_db):
        """``_roles_from_flat_text`` yields "Jeongwoo Moon"; Scopus stores "Moon J."."""
        db_mod.add_entries([SAMPLE])
        db_mod.record_fulltext_fetch(
            SAMPLE["eid"],
            roles={
                "first_auids": [],
                "first_names": ["Jeongwoo Moon", "Byeongchan Yun"],
                "corr_auids": [],
                "corr_names": ["Kwanho Jeong"],
            },
        )
        assert db_mod.get_author("59227334200")["articles"][0]["is_first_author"] is True
        assert db_mod.get_author("56659062100")["articles"][0]["is_corresponding"] is True

    def test_flat_text_fallback_shape_round_trips(self):
        raw = (
            "<full-text-retrieval-response><xocs:rawtext xmlns:xocs='x'>"
            "Jeongwoo Moon a 1 Byeongchan Yun b 1 "
            "1 These authors contributed equally to this work."
            "</xocs:rawtext></full-text-retrieval-response>"
        )
        names = ft.parse_roles(raw)["first_names"]
        assert names and all(db_mod._names_hit("Moon J.", {n}) for n in names[:1])
