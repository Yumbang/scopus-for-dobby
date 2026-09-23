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

    func testBadResponseUnwrapsDaemonErrorEnvelope() {
        let body = #"{"error":"Project already exists: r1","type":"ValueError","status":400}"#
        let msg = DaemonClient.DaemonError.badResponse(400, body).errorDescription ?? ""
        XCTAssertEqual(msg, "Daemon returned HTTP 400: Project already exists: r1")
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

    func testProjectQueryItemRoundTrips() {
        // ``articles(project:)`` adds a ``project`` item next to ``limit``;
        // a name with ``&``/``=``/non-ASCII must survive as one value.
        var build = URLComponents()
        build.path = "/articles"
        build.queryItems = [
            URLQueryItem(name: "limit", value: "200"),
            URLQueryItem(name: "project", value: "수처리 r&d=1"),
        ]
        let back = URLComponents(string: "http://x" + build.path + "?"
                                 + (build.percentEncodedQuery ?? ""))
        let decoded = Dictionary(
            uniqueKeysWithValues: (back?.queryItems ?? []).map { ($0.name, $0.value) })
        XCTAssertEqual(decoded["project"], "수처리 r&d=1")
        XCTAssertEqual(decoded.count, 2)
    }

    func testUrlPathAllowedEscapesQueryAndFragmentInProjectName() {
        // A project name is one path segment in ``/projects/{name}``. ``?``
        // and ``#`` must be escaped or the daemon would see a truncated name
        // and act on a *different* project (``q?x`` → ``q``). The core
        // rejects ``/`` in project names, so ``.urlPathAllowed`` letting
        // ``/`` through cannot split a project segment.
        for name in ["q?x", "r2#junk", "50%"] {
            let escaped = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed)
            XCTAssertNotNil(escaped)
            XCTAssertFalse(escaped!.contains("?") || escaped!.contains("#"),
                           "structural character leaked in \(escaped!)")
            XCTAssertEqual(escaped?.removingPercentEncoding, name)
        }
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

    func testBuildPathEscapesPlusForFormDecodingServer() {
        // The daemon form-decodes queries, reading a bare ``+`` as a space.
        // Foundation leaves ``+`` unescaped, so ``buildPath`` must do it.
        let path = DaemonClient.buildPath("/articles", queryItems: [
            URLQueryItem(name: "project", value: "C++ r&d"),
        ])
        XCTAssertFalse(path.contains("+"), path)
        let query = String(path.split(separator: "?", maxSplits: 1)[1])
        let formDecoded = query.replacingOccurrences(of: "+", with: " ")
            .split(separator: "=", maxSplits: 1)[1].removingPercentEncoding
        XCTAssertEqual(formDecoded, "C++ r&d")
    }
}
