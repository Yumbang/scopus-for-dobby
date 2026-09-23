import XCTest

@testable import ScopusForDobby

/// Decoding tests for ``ProjectsResponse``. ``GET /projects`` returns a dict
/// keyed by project name (``list_projects`` in article_db.py); each value
/// carries ``created``, sorted member ``collections``, ``collection_count``
/// and a *distinct* ``article_count``.
final class ProjectDecodingTests: XCTestCase {
    private let decoder = JSONDecoder()

    func testDecodesDictShapedResponseSortedByName() throws {
        let json = """
        {
          "projects": {
            "r1": {"created": "2026-09-23 20:00:00", "collections": ["r1-b", "r1-a"],
                   "collection_count": 2, "article_count": 3},
            "pemwe": {"created": "2026-09-22 10:00:00", "collections": [],
                      "collection_count": 0, "article_count": 0}
          }
        }
        """
        let resp = try decoder.decode(ProjectsResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.projects.map(\.name), ["pemwe", "r1"])
        let r1 = resp.projects[1]
        XCTAssertEqual(r1.id, "r1")
        XCTAssertEqual(r1.collections, ["r1-a", "r1-b"], "members are sorted")
        XCTAssertEqual(r1.collectionCount, 2)
        XCTAssertEqual(r1.articleCount, 3)
        XCTAssertEqual(r1.createdAt, "2026-09-23 20:00:00")
        XCTAssertEqual(resp.projects[0].collections, [])
    }

    func testMissingCountsFallBack() throws {
        // Absent counts must not throw: collection_count falls back to the
        // member list, article_count to zero.
        let json = #"{"projects": {"p": {"collections": ["a", "b"]}}}"#
        let resp = try decoder.decode(ProjectsResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.projects[0].collectionCount, 2)
        XCTAssertEqual(resp.projects[0].articleCount, 0)
        XCTAssertNil(resp.projects[0].createdAt)
    }

    func testEmptyResponse() throws {
        let resp = try decoder.decode(ProjectsResponse.self, from: Data(#"{"projects": {}}"#.utf8))
        XCTAssertTrue(resp.projects.isEmpty)
    }

    func testHandlesKoreanNames() throws {
        let json = #"{"projects": {"수처리 연구": {"collections": ["막 오염"], "article_count": 5}}}"#
        let resp = try decoder.decode(ProjectsResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.projects[0].name, "수처리 연구")
        XCTAssertEqual(resp.projects[0].collections, ["막 오염"])
        XCTAssertEqual(resp.projects[0].articleCount, 5)
    }
}
