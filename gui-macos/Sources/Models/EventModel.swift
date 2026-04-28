import Foundation

/// One row from the ``events`` table. Used to drive incremental UI
/// refreshes — the GUI tracks ``MAX(id)`` and polls
/// ``GET /events?since=<last_id>`` on a timer.
struct EventModel: Decodable, Identifiable, Hashable {
    let id: Int
    let ts: String?
    let kind: String
    let entityType: String?
    let entityId: String?

    enum CodingKeys: String, CodingKey {
        case id, ts, kind
        case entityType = "entity_type"
        case entityId = "entity_id"
        // payload omitted from the skeleton — pull on demand if a view needs it
    }
}

struct EventsResponse: Decodable {
    let events: [EventModel]
    let maxId: Int

    enum CodingKeys: String, CodingKey {
        case events
        case maxId = "max_id"
    }
}
