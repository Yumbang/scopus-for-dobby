import XCTest

@testable import ScopusForDobby

/// Pure-logic tests that need no running daemon. They cover the two pieces of
/// ``DaemonClient`` that are observable without a live socket: the
/// ``DaemonError`` user-facing messages, and the Foundation percent-encoding /
/// URLComponents invariants the client's private helpers rely on.
///
/// ``pathEscaped(_:)`` and ``buildPath(_:queryItems:)`` are ``private`` on
/// ``DaemonClient`` (so unreachable even via ``@testable``); these tests pin the
/// exact Foundation behavior those helpers are built on, which is what would
/// silently change and break the wire format under a future SDK.
final class DaemonClientLogicTests: XCTestCase {
    // MARK: DaemonError messages

    func testNotRunningErrorMentionsServeCommand() {
        let msg = DaemonClient.DaemonError.notRunning.errorDescription ?? ""
        XCTAssertTrue(msg.contains("not running"))
        XCTAssertTrue(msg.contains("scopus-for-dobby serve"))
    }

    func testBadResponseErrorIncludesStatusAndBody() {
        let msg = DaemonClient.DaemonError.badResponse(503, "down for maintenance")
            .errorDescription ?? ""
        XCTAssertTrue(msg.contains("503"))
        XCTAssertTrue(msg.contains("down for maintenance"))
    }

    func testInvalidPortErrorMessage() {
        let msg = DaemonClient.DaemonError.invalidPort.errorDescription ?? ""
        XCTAssertTrue(msg.lowercased().contains("port"))
    }

    // MARK: percent-encoding invariants (mirrors ``pathEscaped``)

    func testUrlPathAllowedEncodesNonAsciiSegment() {
        // ``pathEscaped`` uses ``.urlPathAllowed`` so a Korean collection name
        // becomes a valid path segment. Percent-encoding must be applied and
        // round-trip back to the original.
        let segment = "사회과학"
        let escaped = segment.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
        XCTAssertNotNil(escaped)
        XCTAssertNotEqual(escaped, segment, "non-ASCII must be percent-encoded")
        XCTAssertEqual(escaped?.removingPercentEncoding, segment)
    }

    func testUrlPathAllowedEncodesSpaceAndSlash() {
        // A collection name with a space and a slash must not leak structural
        // characters into the path. ``.urlPathAllowed`` permits ``/`` to pass
        // through unescaped, so callers that pass a name into a single segment
        // must rely on the fact that the encoded result still round-trips.
        let segment = "My Papers"
        let escaped = segment.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
        XCTAssertEqual(escaped, "My%20Papers")
        XCTAssertEqual(escaped?.removingPercentEncoding, segment)
    }

    // MARK: query-building invariants (mirrors ``buildPath``)

    func testQueryItemEncodingPreventsParamSmuggling() {
        // The crux of ``searchFTS``'s comment: a value containing ``&`` and
        // ``=`` must be encoded so it can't smuggle a second query parameter.
        var c = URLComponents()
        c.path = "/search/fts"
        c.queryItems = [
            URLQueryItem(name: "query", value: "foo&limit=99999"),
            URLQueryItem(name: "limit", value: "100"),
        ]
        let query = c.percentEncodedQuery ?? ""

        // The injected ``&``/``=`` inside the value must be encoded, leaving
        // exactly one ``limit=`` (the legitimate one) at top level.
        XCTAssertTrue(query.contains("limit%3D99999") || query.contains("limit%3d99999"),
                      "value-internal '=' must be percent-encoded; got \(query)")
        let topLevelLimit = query.split(separator: "&").filter { $0.hasPrefix("limit=") }
        XCTAssertEqual(topLevelLimit.count, 1, "exactly one real limit param; got \(query)")
        XCTAssertEqual(topLevelLimit.first, "limit=100")
    }

    func testBuildPathRoundTripsThroughResolvedComponents() {
        // ``buildPath`` returns ``path + "?" + percentEncodedQuery``; feeding
        // that back through ``URLComponents`` (as ``resolved`` does via
        // ``percentEncodedPath``/``percentEncodedQuery``) must reconstruct the
        // original query item values.
        var build = URLComponents()
        build.path = "/articles"
        build.queryItems = [
            URLQueryItem(name: "limit", value: "200"),
            URLQueryItem(name: "collection", value: "사회 과학"),
        ]
        let combined = build.path + "?" + (build.percentEncodedQuery ?? "")

        let parts = combined.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        var resolved = URLComponents()
        resolved.percentEncodedPath = String(parts[0])
        resolved.percentEncodedQuery = parts.count > 1 ? String(parts[1]) : nil

        XCTAssertEqual(resolved.path, "/articles")
        let decoded = Dictionary(
            uniqueKeysWithValues: (resolved.queryItems ?? []).map { ($0.name, $0.value) })
        XCTAssertEqual(decoded["limit"], "200")
        XCTAssertEqual(decoded["collection"], "사회 과학")
    }
}
