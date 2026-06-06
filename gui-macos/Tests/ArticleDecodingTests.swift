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
          "_tags": ["to-read", "important"],
          "_notes": "Follow up on section 3.",
          "_added_at": "2026-01-01T12:00:00",
          "_updated_at": "2026-01-02T08:30:00"
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
