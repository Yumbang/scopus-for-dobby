import Foundation

/// Single collection summary. Matches the values returned by
/// ``GET /collections`` (a ``{name: {article_count, created, project}}`` dict).
struct CollectionInfo: Identifiable, Hashable {
    let name: String
    let articleCount: Int
    let createdAt: String?
    /// The project this collection is filed under, or nil when ungrouped.
    /// Absent on daemons older than schema v4, which decodes as nil too.
    var project: String? = nil

    var id: String { name }
}

/// Decodes the dict-shaped ``GET /collections`` response into ``[CollectionInfo]``.
struct CollectionsResponse: Decodable {
    let collections: [CollectionInfo]

    private struct Entry: Decodable {
        let articleCount: Int?
        let createdAt: String?
        let project: String?

        enum CodingKeys: String, CodingKey {
            case articleCount = "article_count"
            // Server emits ``created`` (not ``created_at``); accept either so a
            // future schema rename doesn't blank the sidebar silently.
            case createdAt = "created"
            case createdAtAlt = "created_at"
            case project
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            self.articleCount = try c.decodeIfPresent(Int.self, forKey: .articleCount)
            let primary = try c.decodeIfPresent(String.self, forKey: .createdAt)
            let alt = try c.decodeIfPresent(String.self, forKey: .createdAtAlt)
            self.createdAt = primary ?? alt
            self.project = try c.decodeIfPresent(String.self, forKey: .project)
        }
    }

    private enum RootKeys: String, CodingKey { case collections }

    init(from decoder: Decoder) throws {
        let root = try decoder.container(keyedBy: RootKeys.self)
        let dict = try root.decode([String: Entry].self, forKey: .collections)
        self.collections = dict
            .map { CollectionInfo(name: $0.key,
                                  articleCount: $0.value.articleCount ?? 0,
                                  createdAt: $0.value.createdAt,
                                  project: $0.value.project) }
            .sorted { $0.name < $1.name }
    }
}
