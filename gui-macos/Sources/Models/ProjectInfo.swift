import Foundation

/// One project: a named group of collections, one level above them. Matches
/// a value of ``GET /projects`` (``list_projects`` in article_db.py).
///
/// ``articleCount`` counts *distinct* papers across the member collections,
/// so it is usually less than the sum of their counts.
struct ProjectInfo: Identifiable, Hashable {
    let name: String
    let createdAt: String?
    /// Member collection names, sorted.
    let collections: [String]
    let collectionCount: Int
    let articleCount: Int

    var id: String { name }
}

/// Decodes the dict-shaped ``GET /projects`` response into ``[ProjectInfo]``
/// sorted by name, mirroring ``CollectionsResponse``.
struct ProjectsResponse: Decodable {
    let projects: [ProjectInfo]

    private struct Entry: Decodable {
        let created: String?
        let collections: [String]?
        let collectionCount: Int?
        let articleCount: Int?

        enum CodingKeys: String, CodingKey {
            case created
            case collections
            case collectionCount = "collection_count"
            case articleCount = "article_count"
        }
    }

    private enum RootKeys: String, CodingKey { case projects }

    init(from decoder: Decoder) throws {
        let root = try decoder.container(keyedBy: RootKeys.self)
        let dict = try root.decode([String: Entry].self, forKey: .projects)
        self.projects = dict
            .map { name, e in
                let members = (e.collections ?? []).sorted()
                return ProjectInfo(name: name,
                                   createdAt: e.created,
                                   collections: members,
                                   collectionCount: e.collectionCount ?? members.count,
                                   articleCount: e.articleCount ?? 0)
            }
            .sorted { $0.name < $1.name }
    }
}
