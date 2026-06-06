"""Unit tests for the Scopus Search API wrapper and HTTP client.

These tests mock the HTTP layer (requests.get) and never make network calls.
"""

import pytest

from scopus_for_dobby.core import search as search_mod
from scopus_for_dobby.utils import api_client

# ── Fixtures / fakes ──────────────────────────────────────────────────────────


class FakeResponse:
    """Stand-in for requests.Response."""

    def __init__(self, status_code=200, json_data=None, headers=None, text="", reason="OK"):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.text = text
        self.reason = reason

    def json(self):
        return self._json


def _search_results(entries=None, total=2, start=0, per_page=25):
    """Build a Scopus-shaped search-results payload."""
    return {
        "search-results": {
            "opensearch:totalResults": str(total),
            "opensearch:startIndex": str(start),
            "opensearch:itemsPerPage": str(per_page),
            "entry": entries
            if entries is not None
            else [
                {"dc:title": "A"},
                {"dc:title": "B"},
            ],
        }
    }


@pytest.fixture(autouse=True)
def stub_config(monkeypatch):
    """Provide a valid config and disable throttling/quota caching so tests
    neither sleep nor touch the real config file.
    """
    cfg = {"api_key": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4", "tier": "standard"}
    monkeypatch.setattr(api_client, "load_config", lambda: cfg)
    # search.py imports load_config by reference, so patch its namespace too.
    monkeypatch.setattr(search_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(api_client, "_throttle", lambda endpoint: None)
    monkeypatch.setattr(api_client, "_cache_quota", lambda remaining, reset: None)


@pytest.fixture
def capture_get(monkeypatch):
    """Patch requests.get to return a canned response and record the call.

    Returns a dict the test can mutate: set ``calls['response']`` (or a list
    in ``calls['responses']`` for pagination) and read ``calls['params']``.
    """
    calls = {
        "params": [],
        "url": None,
        "response": FakeResponse(json_data={}),
        "responses": None,
        "i": 0,
    }

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["url"] = url
        calls["params"].append(params)
        if calls["responses"] is not None:
            resp = calls["responses"][calls["i"]]
            calls["i"] += 1
            return resp
        return calls["response"]

    monkeypatch.setattr(api_client.requests, "get", fake_get)
    return calls


# ── Query auto-wrapping ───────────────────────────────────────────────────────


class TestQueryWrapping:
    def test_plain_query_wrapped_in_title_abs_key(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        result = search_mod.search("deep learning")
        assert result["query"] == "TITLE-ABS-KEY(deep learning)"
        assert capture_get["params"][0]["query"] == "TITLE-ABS-KEY(deep learning)"

    def test_existing_field_code_not_wrapped(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        result = search_mod.search("AUTH(Kim)")
        assert result["query"] == "AUTH(Kim)"

    def test_title_abs_key_query_not_double_wrapped(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        result = search_mod.search("TITLE-ABS-KEY(neural nets)")
        assert result["query"] == "TITLE-ABS-KEY(neural nets)"

    def test_field_code_with_space_not_wrapped(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        result = search_mod.search("PUBYEAR > 2020")
        assert result["query"] == "PUBYEAR > 2020"


# ── Parameter construction ────────────────────────────────────────────────────


class TestParamConstruction:
    def test_count_capped_at_25(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        search_mod.search("x", count=100)
        assert capture_get["params"][0]["count"] == 25

    def test_start_and_sort_passed_through(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        search_mod.search("x", start=50, sort="citedby-count")
        params = capture_get["params"][0]
        assert params["start"] == 50
        assert params["sort"] == "citedby-count"

    def test_date_and_subj_included_when_set(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        search_mod.search("x", date="2020-2024", subj="COMP")
        params = capture_get["params"][0]
        assert params["date"] == "2020-2024"
        assert params["subj"] == "COMP"

    def test_date_and_subj_omitted_when_none(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        search_mod.search("x")
        params = capture_get["params"][0]
        assert "date" not in params
        assert "subj" not in params

    def test_view_standard_for_non_institutional(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        search_mod.search("x")
        assert capture_get["params"][0]["view"] == "STANDARD"

    def test_view_complete_for_institutional(self, capture_get, monkeypatch):
        inst = {"api_key": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4", "tier": "institutional"}
        monkeypatch.setattr(api_client, "load_config", lambda: inst)
        monkeypatch.setattr(search_mod, "load_config", lambda: inst)
        capture_get["response"] = FakeResponse(json_data=_search_results())
        search_mod.search("x")
        assert capture_get["params"][0]["view"] == "COMPLETE"

    def test_explicit_view_overrides_tier(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        search_mod.search("x", view="COMPLETE")
        assert capture_get["params"][0]["view"] == "COMPLETE"

    def test_author_id_query_construction(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        result = search_mod.search_by_author_id("12345678")
        assert result["query"] == "AU-ID(12345678)"
        assert capture_get["params"][0]["sort"] == "-pubyear"


# ── Result parsing ────────────────────────────────────────────────────────────


class TestResultParsing:
    def test_counts_coerced_to_int(self, capture_get):
        capture_get["response"] = FakeResponse(
            json_data=_search_results(total=42, start=25, per_page=25)
        )
        result = search_mod.search("x")
        assert result["total_results"] == 42
        assert result["start_index"] == 25
        assert result["items_per_page"] == 25

    def test_error_entries_filtered_out(self, capture_get):
        entries = [{"dc:title": "Good"}, {"error": "Result set was empty"}]
        capture_get["response"] = FakeResponse(json_data=_search_results(entries=entries, total=1))
        result = search_mod.search("x")
        assert len(result["entries"]) == 1
        assert result["entries"][0]["dc:title"] == "Good"

    def test_missing_search_results_defaults(self, capture_get):
        capture_get["response"] = FakeResponse(json_data={})
        result = search_mod.search("x")
        assert result["total_results"] == 0
        assert result["entries"] == []


# ── Rate-limit header extraction ──────────────────────────────────────────────


class TestRateLimit:
    def test_rate_limit_extracted_from_headers(self, capture_get):
        capture_get["response"] = FakeResponse(
            json_data=_search_results(),
            headers={"X-RateLimit-Remaining": "19999", "X-RateLimit-Reset": "1700000000"},
        )
        result = search_mod.search("x")
        assert result["_rate_limit"]["remaining"] == 19999
        assert result["_rate_limit"]["reset"] == "1700000000"

    def test_rate_limit_absent_when_no_header(self, capture_get):
        capture_get["response"] = FakeResponse(json_data=_search_results())
        result = search_mod.search("x")
        assert result["_rate_limit"] is None

    def test_quota_cached_on_success(self, capture_get, monkeypatch):
        cached = {}
        monkeypatch.setattr(
            api_client,
            "_cache_quota",
            lambda remaining, reset: cached.update(remaining=remaining, reset=reset),
        )
        capture_get["response"] = FakeResponse(
            json_data=_search_results(),
            headers={"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "1700000000"},
        )
        search_mod.search("x")
        assert cached == {"remaining": 100, "reset": "1700000000"}


# ── Pagination ────────────────────────────────────────────────────────────────


class TestPagination:
    def test_fetches_multiple_pages(self, capture_get):
        page1 = _search_results(entries=[{"dc:title": f"P1-{i}"} for i in range(25)], total=40)
        page2 = _search_results(
            entries=[{"dc:title": f"P2-{i}"} for i in range(15)], total=40, start=25
        )
        capture_get["responses"] = [
            FakeResponse(json_data=page1),
            FakeResponse(json_data=page2),
        ]
        result = search_mod.search_all_pages("x", max_results=100)
        assert result["fetched"] == 40
        assert len(result["entries"]) == 40
        # start advanced by the number of entries on page 1
        assert capture_get["params"][0]["start"] == 0
        assert capture_get["params"][1]["start"] == 25

    def test_stops_at_max_results(self, capture_get):
        page1 = _search_results(entries=[{"dc:title": f"P1-{i}"} for i in range(25)], total=1000)
        capture_get["responses"] = [FakeResponse(json_data=page1)]
        result = search_mod.search_all_pages("x", max_results=10)
        # Truncated to max_results; only one page requested
        assert result["fetched"] == 10
        assert len(capture_get["params"]) == 1

    def test_stops_on_empty_page(self, capture_get):
        empty = _search_results(entries=[], total=0)
        capture_get["responses"] = [FakeResponse(json_data=empty)]
        result = search_mod.search_all_pages("x", max_results=100)
        assert result["fetched"] == 0
        assert result["entries"] == []

    def test_progress_callback_invoked(self, capture_get):
        page1 = _search_results(entries=[{"dc:title": f"P-{i}"} for i in range(25)], total=25)
        capture_get["responses"] = [FakeResponse(json_data=page1)]
        seen = []
        search_mod.search_all_pages(
            "x", max_results=100, progress_callback=lambda f, t: seen.append((f, t))
        )
        assert seen == [(25, 25)]


# ── Error handling / sanitization ─────────────────────────────────────────────


class TestErrorHandling:
    def test_non_200_does_not_leak_body(self, capture_get):
        sensitive_body = "SECRET-leaked-in-body-should-not-surface"
        capture_get["response"] = FakeResponse(
            status_code=500, text=sensitive_body, reason="Internal Server Error"
        )
        with pytest.raises(RuntimeError) as exc:
            search_mod.search("x")
        msg = str(exc.value)
        assert sensitive_body not in msg
        assert "500" in msg
        assert "/content/search/scopus" in msg
        assert "Internal Server Error" in msg

    def test_raw_body_logged_at_debug(self, capture_get, caplog):
        import logging

        raw_body = "diagnostic-body-payload"
        capture_get["response"] = FakeResponse(status_code=502, text=raw_body, reason="Bad Gateway")
        with (
            caplog.at_level(logging.DEBUG, logger=api_client.__name__),
            pytest.raises(RuntimeError),
        ):
            search_mod.search("x")
        # The raw body is available for diagnostics via the debug log only.
        assert raw_body in caplog.text

    def test_429_raises_rate_limit_error(self, capture_get):
        capture_get["response"] = FakeResponse(
            status_code=429,
            headers={"X-RateLimit-Reset": "1700000000"},
            text="quota body",
        )
        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            search_mod.search("x")

    def test_401_raises_auth_error(self, capture_get):
        capture_get["response"] = FakeResponse(
            status_code=401, text="unauthorized body", reason="Unauthorized"
        )
        with pytest.raises(RuntimeError, match="Authentication failed") as exc:
            search_mod.search("x")
        assert "unauthorized body" not in str(exc.value)

    def test_403_raises_authorization_error(self, capture_get):
        capture_get["response"] = FakeResponse(
            status_code=403, text="forbidden body", reason="Forbidden"
        )
        with pytest.raises(RuntimeError, match="Authorization error") as exc:
            search_mod.search("x")
        assert "forbidden body" not in str(exc.value)

    def test_reason_fallback_when_missing(self, capture_get):
        capture_get["response"] = FakeResponse(status_code=503, text="body", reason="")
        with pytest.raises(RuntimeError, match="request failed"):
            search_mod.search("x")
