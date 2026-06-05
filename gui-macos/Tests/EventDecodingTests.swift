import XCTest

@testable import ScopusForDobby

/// Decoding tests for ``EventModel`` / ``EventsResponse``. ``GET /events``
/// (``list_events`` in app.py) returns ``{events: [...], max_id: n}`` where each
/// event has ``id, ts, kind, entity_type, entity_id, payload``. The GUI's
/// ``EventModel`` deliberately drops ``payload`` and must ignore it cleanly.
final class EventDecodingTests: XCTestCase {
    private let decoder = JSONDecoder()

    func testDecodesEventIgnoringPayload() throws {
        let json = """
        {
          "id": 17,
          "ts": "2026-06-05 12:00:00",
          "kind": "article.added",
          "entity_type": "article",
          "entity_id": "2-s2.0-85123456789",
          "payload": {"some": "thing", "nested": [1, 2, 3]}
        }
        """
        let event = try decoder.decode(EventModel.self, from: Data(json.utf8))

        XCTAssertEqual(event.id, 17)
        XCTAssertEqual(event.ts, "2026-06-05 12:00:00")
        XCTAssertEqual(event.kind, "article.added")
        XCTAssertEqual(event.entityType, "article")
        XCTAssertEqual(event.entityId, "2-s2.0-85123456789")
    }

    func testDecodesEventWithNullOptionalFields() throws {
        // ``list_events`` emits ``"ts": null`` when the row's timestamp is NULL,
        // and entity fields can be null for collection-level events.
        let json = """
        {
          "id": 1,
          "ts": null,
          "kind": "collection.created",
          "entity_type": null,
          "entity_id": null,
          "payload": {}
        }
        """
        let event = try decoder.decode(EventModel.self, from: Data(json.utf8))

        XCTAssertEqual(event.id, 1)
        XCTAssertNil(event.ts)
        XCTAssertEqual(event.kind, "collection.created")
        XCTAssertNil(event.entityType)
        XCTAssertNil(event.entityId)
    }

    func testMissingKindThrows() {
        // ``kind`` is non-optional; it drives the UI's refresh routing.
        let json = #"{"id": 5, "ts": null, "entity_type": null, "entity_id": null}"#
        XCTAssertThrowsError(try decoder.decode(EventModel.self, from: Data(json.utf8)))
    }

    func testDecodesEventsEnvelope() throws {
        let json = """
        {
          "events": [
            {"id": 10, "ts": "2026-06-05 12:00:00", "kind": "article.added",
             "entity_type": "article", "entity_id": "2-s2.0-1", "payload": {}},
            {"id": 11, "ts": "2026-06-05 12:01:00", "kind": "article.tagged",
             "entity_type": "article", "entity_id": "2-s2.0-1", "payload": {"tag": "x"}}
          ],
          "max_id": 11
        }
        """
        let resp = try decoder.decode(EventsResponse.self, from: Data(json.utf8))

        XCTAssertEqual(resp.events.count, 2)
        XCTAssertEqual(resp.events.map(\.id), [10, 11])
        XCTAssertEqual(resp.maxId, 11)
    }

    func testDecodesEmptyEventsEnvelope() throws {
        // When no rows are newer than ``since``, ``max_id`` echoes ``since``.
        let json = #"{"events": [], "max_id": 42}"#
        let resp = try decoder.decode(EventsResponse.self, from: Data(json.utf8))

        XCTAssertTrue(resp.events.isEmpty)
        XCTAssertEqual(resp.maxId, 42)
    }
}
