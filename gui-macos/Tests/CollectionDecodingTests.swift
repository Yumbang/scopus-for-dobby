import XCTest

@testable import ScopusForDobby

/// Decoding tests for ``CollectionsResponse``. ``GET /collections`` returns a
/// dict keyed by collection name (``list_collections`` in article_db.py), with
/// each value carrying ``article_count`` and ``created`` (note: *not*
/// ``created_at`` on the wire — the model accepts either).
final class CollectionDecodingTests: XCTestCase {
    private let decoder = JSONDecoder()

    func testDecodesDictShapedResponseSortedByName() throws {
        let json = """
        {
          "collections": {
            "Zoology": {"article_count": 3, "created": "2026-01-03T00:00:00"},
            "Anatomy": {"article_count": 10, "created": "2026-01-01T00:00:00"},
            "Botany": {"article_count": 0, "created": "2026-01-02T00:00:00"}
          }
        }
        """
        let resp = try decoder.decode(CollectionsResponse.self, from: Data(json.utf8))

        // Sorted alphabetically by name regardless of dict iteration order.
        XCTAssertEqual(resp.collections.map(\.name), ["Anatomy", "Botany", "Zoology"])
        XCTAssertEqual(resp.collections[0].articleCount, 10)
        XCTAssertEqual(resp.collections[0].createdAt, "2026-01-01T00:00:00")
        XCTAssertEqual(resp.collections[1].articleCount, 0)
        XCTAssertEqual(resp.collections[2].articleCount, 3)
        XCTAssertEqual(resp.collections[0].id, "Anatomy")
    }

    func testAcceptsCreatedAtAlias() throws {
        // The model tolerates a future ``created_at`` rename without blanking
        // the timestamp.
        let json = """
        {"collections": {"Misc": {"article_count": 1, "created_at": "2026-02-02T00:00:00"}}}
        """
        let resp = try decoder.decode(CollectionsResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.collections.count, 1)
        XCTAssertEqual(resp.collections[0].createdAt, "2026-02-02T00:00:00")
    }

    func testMissingCountDefaultsToZero() throws {
        let json = #"{"collections": {"Empty": {"created": "2026-01-01T00:00:00"}}}"#
        let resp = try decoder.decode(CollectionsResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.collections[0].articleCount, 0)
    }

    func testEmptyCreatedStringDecodes() throws {
        // ``list_collections`` substitutes ``""`` for a NULL ``created_at``.
        let json = #"{"collections": {"New": {"article_count": 0, "created": ""}}}"#
        let resp = try decoder.decode(CollectionsResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.collections[0].createdAt, "")
    }

    func testHandlesNonAsciiCollectionName() throws {
        // Korean collection names must survive decoding (parity with the
        // percent-encoding path used to fetch them).
        let json = """
        {"collections": {"사회과학": {"article_count": 5, "created": "2026-01-01T00:00:00"}}}
        """
        let resp = try decoder.decode(CollectionsResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.collections.count, 1)
        XCTAssertEqual(resp.collections[0].name, "사회과학")
        XCTAssertEqual(resp.collections[0].articleCount, 5)
    }

    func testEmptyCollectionsDict() throws {
        let json = #"{"collections": {}}"#
        let resp = try decoder.decode(CollectionsResponse.self, from: Data(json.utf8))

        XCTAssertTrue(resp.collections.isEmpty)
    }
}
