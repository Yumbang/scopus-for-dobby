import XCTest

@testable import ScopusForDobby

/// The Choose-collections filter's glob. It replaced ``NSPredicate LIKE``,
/// which crashed the app on a trailing backslash, so odd input is the point.
final class GlobMatchTests: XCTestCase {
    private func m(_ p: String, _ s: String) -> Bool {
        AssignCollectionsSheet.globMatches(p, s)
    }

    func testStarAndQuestionMark() {
        XCTAssertTrue(m("r1-*", "r1-fouling"))
        XCTAssertTrue(m("r1-*", "R1-"))
        XCTAssertFalse(m("r1-*", "xr1-a"))
        XCTAssertTrue(m("*fouling*", "membrane fouling review"))
        XCTAssertTrue(m("r?-a", "r2-a"))
        XCTAssertFalse(m("r?-a", "r22-a"))
        XCTAssertTrue(m("**", ""))
        XCTAssertTrue(m("a*b*c", "aXXbYYc"))
        XCTAssertFalse(m("a*b*c", "aXXbYY"))
    }

    func testRegexAndLikeMetacharactersAreLiteral() {
        XCTAssertTrue(m("*\\", "path\\"))
        XCTAssertFalse(m("*\\", "path"))
        XCTAssertTrue(m("[*", "[draft] a"))
        XCTAssertTrue(m("50%*", "50% done"))
        XCTAssertTrue(m("*.+", "c.+"))
        XCTAssertFalse(m("*.+", "cx"))
    }

    func testNonAsciiIsCaseFoldedPerCharacter() {
        XCTAssertTrue(m("수처리*", "수처리 공정"))
        XCTAssertTrue(m("ÉTUDE-?", "étude-1"))
    }
}
