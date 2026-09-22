import XCTest

@testable import ScopusForDobby

/// Decoding tests for ``Article`` / ``ArticleListResponse``. The JSON payloads
/// here mirror what ``scopus_for_dobby/core/article_db.py`` emits: user-metadata
/// fields under leading-underscore names (``_tags`` etc.), snake_case Scopus
/// columns (``cover_date``, ``cited_by``, ``first_author``, ``all_authors``),
/// and the ``{articles, total_matching, total_in_db}`` list envelope from
/// ``GET /articles``.
final class ArticleDecodingTests: XCTestCase {
    private let decoder = JSONDecoder()

    func testDecodesFullArticleRow() throws {
        // Shape from ``_row_to_dict`` after the ``_tags``/``_notes`` rename.
        let json = """
        {
          "eid": "2-s2.0-85123456789",
          "scopus_id": "85123456789",
          "doi": "10.1000/xyz123",
          "title": "A Study of Things",
          "first_author": "Doe J.",
          "all_authors": [
            {"auid": "7001234567", "name": "Doe J."},
            {"auid": "7009876543", "name": "Roe R."}
          ],
          "journal": "Journal of Things",
          "volume": "12",
          "issue": "3",
          "pages": "100-110",
          "cover_date": "2021-05-01",
          "cited_by": 42,
          "open_access": true,
          "abstract": "We studied things.",
          "keywords": "things; stuff",
          "issn": "1234-5678",
          "source_type": "j",
          "affiliations": ["Institute of Things"],
          "index_keywords": ["Thing analysis", "Stuff"],
          "subject_areas": [{"name": "Environmental Science", "code": "2300", "abbrev": "ENVI"}],
          "_tags": ["to-read", "important"],
          "_notes": "Follow up on section 3.",
          "_added_at": "2026-01-01T12:00:00",
          "_updated_at": "2026-01-02T08:30:00",
          "openalex_id": "W2741809807",
          "oa_status": "gold",
          "oa_url": "https://example.org/free.pdf",
          "openalex_cited_by": 51,
          "openalex_topics": ["Membrane Fouling", "Water Treatment"],
          "openalex_enriched_at": "2026-02-01 09:15:00",
          "fulltext_fetched_at": "2026-02-02 10:00:00"
        }
        """
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertEqual(article.eid, "2-s2.0-85123456789")
        XCTAssertEqual(article.id, "2-s2.0-85123456789")
        XCTAssertEqual(article.scopusId, "85123456789")
        XCTAssertEqual(article.doi, "10.1000/xyz123")
        XCTAssertEqual(article.title, "A Study of Things")
        XCTAssertEqual(article.firstAuthor, "Doe J.")
        XCTAssertEqual(article.allAuthors?.count, 2)
        XCTAssertEqual(article.allAuthors?.first?.auid, "7001234567")
        XCTAssertEqual(article.allAuthors?.first?.name, "Doe J.")
        XCTAssertEqual(article.journal, "Journal of Things")
        XCTAssertEqual(article.volume, "12")
        XCTAssertEqual(article.issue, "3")
        XCTAssertEqual(article.pages, "100-110")
        XCTAssertEqual(article.coverDate, "2021-05-01")
        XCTAssertEqual(article.citedBy, 42)
        XCTAssertEqual(article.openAccess, true)
        XCTAssertEqual(article.abstract, "We studied things.")
        XCTAssertEqual(article.keywords, "things; stuff")
        XCTAssertEqual(article.issn, "1234-5678")
        XCTAssertEqual(article.sourceType, "j")
        XCTAssertEqual(article.tags, ["to-read", "important"])
        XCTAssertEqual(article.notes, "Follow up on section 3.")
        XCTAssertEqual(article.addedAt, "2026-01-01T12:00:00")
        XCTAssertEqual(article.updatedAt, "2026-01-02T08:30:00")
        XCTAssertEqual(article.affiliations, ["Institute of Things"])
        XCTAssertEqual(article.indexKeywords, ["Thing analysis", "Stuff"])
        XCTAssertEqual(article.subjectAreas, ["Environmental Science"])
        XCTAssertEqual(article.openalexId, "W2741809807")
        XCTAssertEqual(article.oaStatus, "gold")
        XCTAssertEqual(article.oaUrl, "https://example.org/free.pdf")
        XCTAssertEqual(article.openalexCitedBy, 51)
        XCTAssertEqual(article.openalexTopics, ["Membrane Fouling", "Water Treatment"])
        XCTAssertEqual(article.openalexEnrichedAt, "2026-02-01 09:15:00")
        XCTAssertEqual(article.fulltextFetchedAt, "2026-02-02 10:00:00")
        // Absent from a ``SELECT *`` row — only ``GET /articles/{eid}`` adds it.
        XCTAssertNil(article.collections)
    }

    func testDecodesMinimalArticleWithOnlyEid() throws {
        // Every field but ``eid`` is optional; a row stripped of blanks must
        // still decode rather than throw.
        let json = #"{"eid": "2-s2.0-1"}"#
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertEqual(article.eid, "2-s2.0-1")
        XCTAssertNil(article.title)
        XCTAssertNil(article.citedBy)
        XCTAssertNil(article.openAccess)
        XCTAssertNil(article.tags)
        XCTAssertNil(article.allAuthors)
        // The v2/v3 columns, and the per-article ``collections`` key, are all
        // absent here. Absent must mean nil, not a thrown error — a throw
        // would take the whole row out of a list response (``LossyArticle``).
        XCTAssertNil(article.affiliations)
        XCTAssertNil(article.indexKeywords)
        XCTAssertNil(article.subjectAreas)
        XCTAssertNil(article.openalexId)
        XCTAssertNil(article.oaStatus)
        XCTAssertNil(article.oaUrl)
        XCTAssertNil(article.openalexCitedBy)
        XCTAssertNil(article.openalexTopics)
        XCTAssertNil(article.openalexEnrichedAt)
        XCTAssertNil(article.fulltextFetchedAt)
        XCTAssertNil(article.collections)
    }

    func testNullJsonColumnsDecodeAsNil() throws {
        // ``affiliations`` has no DEFAULT in the v1 schema, so a row written
        // before the column was populated comes back as SQL NULL.
        let json = """
        {"eid": "2-s2.0-1", "affiliations": null, "subject_areas": null,
         "openalex_topics": null, "oa_status": null}
        """
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertNil(article.affiliations)
        XCTAssertNil(article.subjectAreas)
        XCTAssertNil(article.openalexTopics)
        XCTAssertNil(article.oaStatus)
    }

    func testEmptyJsonArraysDecodeAsEmptyNotNil() throws {
        // The v2 columns default to ``'[]'``, which is the overwhelmingly
        // common shape for a library that has never run ``openalex enrich``.
        let json = #"{"eid": "2-s2.0-1", "openalex_topics": [], "index_keywords": []}"#
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertEqual(article.openalexTopics, [])
        XCTAssertEqual(article.indexKeywords, [])
    }

    // MARK: - Heterogeneous JSON-array columns
    //
    // ``affiliations`` is written by two ingest paths with two different
    // element shapes; ``subject_areas`` is always objects. Decoding either
    // strictly as ``[String]`` would throw — and a throw in a list response
    // drops the entire article, not the one field.

    func testAffiliationsFromSearchPathDecodeAsStrings() throws {
        // ``core/article_db.py::_normalize_entry`` writes bare affilnames.
        let json = #"{"eid": "x", "affiliations": ["KAIST", "UNIST"]}"#
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertEqual(article.affiliations, ["KAIST", "UNIST"])
    }

    func testAffiliationsFromAbstractPathDecodeAsNames() throws {
        // ``core/abstract.py`` writes ``{"name","city","country"}`` objects
        // into the same column.
        let json = """
        {"eid": "x", "affiliations": [
            {"name": "KAIST", "city": "Daejeon", "country": "South Korea"},
            {"name": "UNIST", "city": "Ulsan", "country": "South Korea"}
        ]}
        """
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertEqual(article.affiliations, ["KAIST", "UNIST"])
    }

    func testSubjectAreasTakeTheirNameFromTheObject() throws {
        let json = """
        {"eid": "x", "subject_areas": [
            {"name": "Environmental Engineering", "code": "2305", "abbrev": "ENVI"},
            {"code": "9999", "abbrev": "XXXX"}
        ]}
        """
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        // The label-less entry is skipped rather than rendered as a blank chip.
        XCTAssertEqual(article.subjectAreas, ["Environmental Engineering"])
    }

    func testObjectShapedColumnDoesNotDropTheRowFromAList() throws {
        // The regression this guards: a strict ``[String]`` decode throws on
        // the object shape, ``LossyArticle`` swallows it, and every enriched
        // article silently disappears from the GUI.
        let json = """
        {
          "articles": [
            {"eid": "2-s2.0-1", "title": "Objects",
             "affiliations": [{"name": "KAIST"}],
             "subject_areas": [{"name": "Chemistry"}]},
            {"eid": "2-s2.0-2", "title": "Strings", "affiliations": ["UNIST"]}
          ],
          "total_matching": 2,
          "total_in_db": 2
        }
        """
        let resp = try decoder.decode(ArticleListResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.articles.map(\.eid), ["2-s2.0-1", "2-s2.0-2"])
        XCTAssertEqual(resp.articles.first?.affiliations, ["KAIST"])
        XCTAssertEqual(resp.articles.first?.subjectAreas, ["Chemistry"])
    }

    // MARK: - collections (single-article endpoint only)

    func testCollectionsDecodeOnSingleArticlePayload() throws {
        let json = #"{"eid": "x", "collections": ["fouling", "to-review"]}"#
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertEqual(article.collections, ["fouling", "to-review"])
    }

    // MARK: - derived reads

    func testOpenAccessStatusPrefersOpenAlexColourOverScopusFlag() throws {
        let gold = try decoder.decode(
            Article.self,
            from: Data(#"{"eid": "x", "oa_status": "GOLD ", "open_access": false}"#.utf8))
        XCTAssertEqual(gold.openAccessStatus, "gold")
        XCTAssertTrue(gold.isFreeToRead)

        // "closed" is a positive finding: enriched, and there is no free copy.
        // It must beat a stale Scopus flag rather than be overridden by it.
        let closed = try decoder.decode(
            Article.self,
            from: Data(#"{"eid": "x", "oa_status": "closed", "open_access": true}"#.utf8))
        XCTAssertEqual(closed.openAccessStatus, "closed")
        XCTAssertFalse(closed.isFreeToRead)
    }

    func testEmptyOaStatusFallsBackToScopusFlag() throws {
        // Never enriched: the column holds ``''`` (its DDL default), not null.
        let json = #"{"eid": "x", "oa_status": "", "open_access": true}"#
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertNil(article.openAccessStatus)
        XCTAssertTrue(article.isFreeToRead)
    }

    func testFreeCopyAndFulltextAndNoteReads() throws {
        let json = """
        {"eid": "x", "oa_url": "https://example.org/a.pdf",
         "fulltext_fetched_at": "2026-02-02 10:00:00", "_notes": "  "}
        """
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertEqual(article.freeCopyURL?.absoluteString, "https://example.org/a.pdf")
        XCTAssertTrue(article.hasCachedFulltext)
        // Whitespace-only is not a note — the daemon defaults ``_notes`` to "".
        XCTAssertFalse(article.hasNote)

        let bare = try decoder.decode(
            Article.self, from: Data(#"{"eid": "x", "oa_url": "", "fulltext_fetched_at": ""}"#.utf8))
        XCTAssertNil(bare.freeCopyURL)
        XCTAssertFalse(bare.hasCachedFulltext)
    }

    func testMissingEidThrows() {
        // ``eid`` is non-optional and is the identity key; its absence must
        // fail decoding so a malformed row can be skipped by the lossy list.
        let json = #"{"title": "No identity"}"#
        XCTAssertThrowsError(try decoder.decode(Article.self, from: Data(json.utf8)))
    }

    func testAuthorTolerantOfMissingFields() throws {
        // ``add_entries`` falls back to ``[{"name": first_author}]`` with no
        // ``auid`` when only a creator string is known.
        let json = #"{"eid": "x", "all_authors": [{"name": "Solo Author"}]}"#
        let article = try decoder.decode(Article.self, from: Data(json.utf8))

        XCTAssertEqual(article.allAuthors?.count, 1)
        XCTAssertNil(article.allAuthors?.first?.auid)
        XCTAssertEqual(article.allAuthors?.first?.name, "Solo Author")
    }

    func testListResponseDecodesEnvelopeAndArticles() throws {
        // ``GET /articles`` envelope: ``{articles, total_matching, total_in_db}``.
        let json = """
        {
          "articles": [
            {"eid": "2-s2.0-1", "title": "First"},
            {"eid": "2-s2.0-2", "title": "Second", "cited_by": 7}
          ],
          "total_matching": 2,
          "total_in_db": 99
        }
        """
        let resp = try decoder.decode(ArticleListResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.articles.count, 2)
        XCTAssertEqual(resp.articles.map(\.eid), ["2-s2.0-1", "2-s2.0-2"])
        XCTAssertEqual(resp.totalMatching, 2)
        XCTAssertEqual(resp.totalInDb, 99)
        XCTAssertNil(resp.total)
    }

    func testListResponseDecodesFtsTotalKey() throws {
        // ``GET /search/fts`` uses ``total`` rather than ``total_matching``.
        let json = """
        {"articles": [{"eid": "2-s2.0-3"}], "total": 1}
        """
        let resp = try decoder.decode(ArticleListResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.articles.count, 1)
        XCTAssertEqual(resp.total, 1)
        XCTAssertNil(resp.totalMatching)
        XCTAssertNil(resp.totalInDb)
    }

    func testListResponseSkipsMalformedRows() throws {
        // A single bad row (missing ``eid``) must be dropped, not poison the
        // whole list — the documented LossyArticle behavior.
        let json = """
        {
          "articles": [
            {"eid": "2-s2.0-1", "title": "Good"},
            {"title": "Bad - no eid"},
            {"eid": "2-s2.0-2", "title": "Also good"}
          ],
          "total_matching": 3
        }
        """
        let resp = try decoder.decode(ArticleListResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.articles.map(\.eid), ["2-s2.0-1", "2-s2.0-2"])
        // The envelope total is server-reported and is *not* recomputed from
        // the surviving rows.
        XCTAssertEqual(resp.totalMatching, 3)
    }

    func testListResponseEmptyArticles() throws {
        let json = #"{"articles": [], "total_matching": 0, "total_in_db": 0}"#
        let resp = try decoder.decode(ArticleListResponse.self, from: Data(json.utf8))

        XCTAssertTrue(resp.articles.isEmpty)
        XCTAssertEqual(resp.totalMatching, 0)
    }
}
